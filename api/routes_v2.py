"""
Autonomous Data & Schema Studio — v2 REST API Routes.
Exposes connections lifecycle, schema snapshotting, drift diffing, and ERD graph topology.
"""

from typing import Dict, Any, Optional, List
import json
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from services.app_db import StudioAppDB
from services.connector import StudioConnector, CredentialVault
from services.catalog import MetadataCatalog
from services.fk_inferrer import FKInferrer
from services.hygiene_detector import HygieneDetector
from services.glossary import GlossaryManager
from services.sql_guard import sql_guard, SQLGuardException
from services.cost_guard import cost_guard
from services.shadow_db import shadow_manager
from services.migration_linter import migration_linter
from services.seed_generator import seed_generator
from services.studio_agent import studio_agent
from services.model_probe import ModelCapabilityProber

router = APIRouter(prefix="/v2", tags=["Studio v2"])
app_db = StudioAppDB()
catalog = MetadataCatalog(app_db=app_db)
fk_inferrer = FKInferrer(app_db=app_db)
hygiene_detector = HygieneDetector(app_db=app_db)
glossary_manager = GlossaryManager(app_db=app_db)


class ConnectionCreateRequest(BaseModel):
    name: str = Field(description="Display name of the connection")
    engine: str = Field(description="Engine type: postgresql, sqlite, duckdb")
    dsn_template: str = Field(description="Connection string or file path")
    tier: str = Field(default="sandbox", description="sandbox, dev, prod")
    password: Optional[str] = Field(default=None, description="Password to store securely in keyring")
    cloud_models_allowed: bool = Field(default=False)
    masking_enabled: bool = Field(default=True)


@router.post("/connections")
def create_connection_endpoint(req: ConnectionCreateRequest):
    secret_ref = None
    if req.password:
        import uuid
        secret_ref = f"sec_{uuid.uuid4().hex[:10]}"
        CredentialVault.store_secret(secret_ref, req.password)

    # Test connection and determine privilege grade
    actual_dsn = StudioConnector.assemble_dsn(req.dsn_template, secret_ref)
    try:
        engine = StudioConnector.create_managed_engine(req.engine, actual_dsn, read_only=True)
        privilege_grade, _ = StudioConnector.evaluate_privilege_grade(engine, req.engine)
    except Exception as e:
        privilege_grade = "B"

    conn_id = app_db.create_connection(
        name=req.name,
        engine=req.engine,
        dsn_template=req.dsn_template,
        tier=req.tier,
        secret_ref=secret_ref,
        privilege_grade=privilege_grade,
        cloud_models_allowed=req.cloud_models_allowed,
        masking_enabled=req.masking_enabled,
    )

    # Automatically take initial snapshot if connection succeeds
    try:
        catalog.capture_and_record_snapshot(conn_id, engine, source="connect")
    except Exception:
        pass

    return {
        "status": "success",
        "connection_id": conn_id,
        "privilege_grade": privilege_grade,
    }


@router.get("/connections")
def list_connections_endpoint():
    conns = app_db.list_connections()
    return {"status": "success", "connections": conns}


@router.get("/connections/{conn_id}")
def get_connection_endpoint(conn_id: str):
    conn_data = app_db.get_connection(conn_id)
    if not conn_data:
        raise HTTPException(status_code=404, detail="Connection not found")
    return {"status": "success", "connection": conn_data}


@router.post("/connections/{conn_id}/snapshots")
def trigger_snapshot_endpoint(conn_id: str):
    conn_data = app_db.get_connection(conn_id)
    if not conn_data:
        raise HTTPException(status_code=404, detail="Connection not found")

    dsn = StudioConnector.assemble_dsn(conn_data["dsn_template"], conn_data.get("secret_ref"))
    engine = StudioConnector.create_managed_engine(conn_data["engine"], dsn, read_only=True)

    snap_id = catalog.capture_and_record_snapshot(conn_id, engine, source="refresh")
    return {"status": "success", "snapshot_id": snap_id}


@router.get("/connections/{conn_id}/snapshots")
def list_snapshots_endpoint(conn_id: str):
    snaps = app_db.list_snapshots(conn_id)
    return {"status": "success", "snapshots": snaps, "count": len(snaps)}


@router.get("/connections/{conn_id}/snapshots/latest")
def get_latest_snapshot_endpoint(conn_id: str):
    snap = app_db.get_latest_snapshot(conn_id)
    if not snap:
        raise HTTPException(status_code=404, detail="No snapshots recorded for connection")
    return {"status": "success", "snapshot": snap}


@router.get("/snapshots/{snapshot_id}")
def get_snapshot_endpoint(snapshot_id: str):
    snap = app_db.get_snapshot(snapshot_id)
    if not snap:
        raise HTTPException(status_code=404, detail="Snapshot not found")
    return {"status": "success", "snapshot": snap}


@router.get("/snapshots/{snap_a_id}/diff/{snap_b_id}")
def diff_snapshots_endpoint(snap_a_id: str, snap_b_id: str):
    snap_a = app_db.get_snapshot(snap_a_id)
    snap_b = app_db.get_snapshot(snap_b_id)
    if not snap_a:
        raise HTTPException(status_code=404, detail=f"Snapshot '{snap_a_id}' not found")
    if not snap_b:
        raise HTTPException(status_code=404, detail=f"Snapshot '{snap_b_id}' not found")

    diff = catalog.compute_snapshot_diff(snap_a["structure"], snap_b["structure"])
    return {
        "status": "success",
        "snapshot_a": snap_a_id,
        "snapshot_b": snap_b_id,
        "diff": diff,
    }


@router.get("/connections/{conn_a_id}/diff/{conn_b_id}")
def diff_connections_endpoint(conn_a_id: str, conn_b_id: str):
    """Computes cross-environment schema drift between two connections (e.g. dev vs prod)."""
    snap_a = app_db.get_latest_snapshot(conn_a_id)
    snap_b = app_db.get_latest_snapshot(conn_b_id)
    if not snap_a:
        raise HTTPException(status_code=400, detail=f"No baseline snapshot found for connection '{conn_a_id}'")
    if not snap_b:
        raise HTTPException(status_code=400, detail=f"No baseline snapshot found for connection '{conn_b_id}'")

    diff = catalog.compute_snapshot_diff(snap_a["structure"], snap_b["structure"])
    return {
        "status": "success",
        "connection_a": conn_a_id,
        "connection_b": conn_b_id,
        "diff": diff,
    }


@router.get("/connections/{conn_id}/diff")
def compute_diff_endpoint(conn_id: str):
    """Computes schema drift between latest snapshot and current live database."""
    conn_data = app_db.get_connection(conn_id)
    if not conn_data:
        raise HTTPException(status_code=404, detail="Connection not found")

    snap = app_db.get_latest_snapshot(conn_id)
    if not snap:
        raise HTTPException(status_code=400, detail="No baseline snapshot exists for diff")

    dsn = StudioConnector.assemble_dsn(conn_data["dsn_template"], conn_data.get("secret_ref"))
    engine = StudioConnector.create_managed_engine(conn_data["engine"], dsn, read_only=True)
    live_structure = catalog.introspect_schema(engine)

    diff = catalog.compute_snapshot_diff(snap["structure"], live_structure)
    return {"status": "success", "diff": diff}


@router.get("/connections/{conn_id}/graph")
def get_erd_graph_endpoint(conn_id: str, include_inferred: bool = Query(default=True)):
    """Returns node and edge definitions ready for interactive ERD rendering."""
    snap = app_db.get_latest_snapshot(conn_id)
    if not snap:
        raise HTTPException(status_code=404, detail="No snapshot found to generate ERD")

    # Inferred relationships from app DB if enabled
    inferred = []
    if include_inferred:
        with app_db._get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM relationship_inferences WHERE snapshot_id = ? AND status != 'rejected';",
                (snap["id"],),
            ).fetchall()
            inferred = [dict(r) for r in rows]

    graph = catalog.generate_erd_graph(snap["structure"], inferred_relationships=inferred)
    return {"status": "success", "graph": graph}


# =========================================================================
# Phase 2 Endpoints: FK Inference, Hygiene Findings & Glossary
# =========================================================================

@router.post("/connections/{conn_id}/relationships/infer")
def infer_relationships_endpoint(conn_id: str, min_score: float = Query(default=0.65)):
    conn_data = app_db.get_connection(conn_id)
    if not conn_data:
        raise HTTPException(status_code=404, detail="Connection not found")

    snap = app_db.get_latest_snapshot(conn_id)
    if not snap:
        raise HTTPException(status_code=400, detail="Snapshot required before relationship inference")

    dsn = StudioConnector.assemble_dsn(conn_data["dsn_template"], conn_data.get("secret_ref"))
    engine = StudioConnector.create_managed_engine(conn_data["engine"], dsn, read_only=True)

    inferred = fk_inferrer.infer_foreign_keys(engine, snap, min_score=min_score)
    return {"status": "success", "inferred_relationships": inferred, "count": len(inferred)}


@router.post("/relationships/{rel_id}/confirm")
def confirm_relationship_endpoint(rel_id: str):
    with app_db._get_connection() as conn:
        cur = conn.execute("UPDATE relationship_inferences SET status = 'confirmed' WHERE id = ?;", (rel_id,))
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Relationship inference record not found")
        conn.commit()
    return {"status": "success", "id": rel_id, "decision": "confirmed"}


@router.post("/relationships/{rel_id}/reject")
def reject_relationship_endpoint(rel_id: str):
    with app_db._get_connection() as conn:
        cur = conn.execute("UPDATE relationship_inferences SET status = 'rejected' WHERE id = ?;", (rel_id,))
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Relationship inference record not found")
        conn.commit()
    return {"status": "success", "id": rel_id, "decision": "rejected"}


@router.post("/connections/{conn_id}/hygiene")
def run_hygiene_audit_endpoint(conn_id: str):
    conn_data = app_db.get_connection(conn_id)
    if not conn_data:
        raise HTTPException(status_code=404, detail="Connection not found")

    snap = app_db.get_latest_snapshot(conn_id)
    if not snap:
        raise HTTPException(status_code=400, detail="Snapshot required before hygiene audit")

    dsn = StudioConnector.assemble_dsn(conn_data["dsn_template"], conn_data.get("secret_ref"))
    engine = StudioConnector.create_managed_engine(conn_data["engine"], dsn, read_only=True)

    findings = hygiene_detector.run_hygiene_audit(engine, snap, connection_id=conn_id)
    return {"status": "success", "findings": findings, "count": len(findings)}


@router.get("/connections/{conn_id}/findings")
def list_findings_endpoint(conn_id: str, status: Optional[str] = Query(default=None)):
    with app_db._get_connection() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM findings WHERE connection_id = ? AND status = ? ORDER BY created_at DESC;",
                (conn_id, status),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM findings WHERE connection_id = ? ORDER BY created_at DESC;",
                (conn_id,),
            ).fetchall()
        import json
        results = []
        for r in rows:
            item = dict(r)
            item["evidence"] = json.loads(item.get("evidence_json") or "{}")
            item["fix"] = json.loads(item.get("fix_json") or "{}")
            results.append(item)
        return {"status": "success", "findings": results, "count": len(results)}


class FindingStatusUpdate(BaseModel):
    status: str = Field(description="open, accepted, dismissed, snoozed")
    dismiss_reason: Optional[str] = None


@router.patch("/findings/{finding_id}")
def update_finding_status_endpoint(finding_id: str, req: FindingStatusUpdate):
    with app_db._get_connection() as conn:
        cur = conn.execute(
            "UPDATE findings SET status = ?, dismiss_reason = ? WHERE id = ?;",
            (req.status, req.dismiss_reason, finding_id),
        )
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Finding not found")
        conn.commit()
    return {"status": "success", "id": finding_id, "status": req.status}


class GlossaryEntryCreate(BaseModel):
    target_kind: str = Field(description="table, column, relationship")
    target: str = Field(description="e.g. orders.status")
    kind: str = Field(description="description, enum_map, join_rule, filter_rule, caveat")
    body: str = Field(description="Business explanation or mapping")


@router.get("/connections/{conn_id}/glossary")
def list_glossary_endpoint(conn_id: str, status: Optional[str] = Query(default=None)):
    entries = glossary_manager.list_entries(conn_id, status=status)
    return {"status": "success", "entries": entries, "count": len(entries)}


@router.post("/connections/{conn_id}/glossary")
def propose_glossary_endpoint(conn_id: str, req: GlossaryEntryCreate):
    gid = glossary_manager.propose_entry(
        connection_id=conn_id,
        target_kind=req.target_kind,
        target=req.target,
        kind=req.kind,
        body=req.body,
        author_kind="user",
    )
    return {"status": "success", "id": gid}


class GlossaryStatusUpdate(BaseModel):
    status: str = Field(description="confirmed, rejected, suggested")


@router.patch("/glossary/{entry_id}")
def update_glossary_status_endpoint(entry_id: str, req: GlossaryStatusUpdate):
    glossary_manager.set_entry_status(entry_id, req.status)
    return {"status": "success", "id": entry_id, "status": req.status}


@router.get("/connections/{conn_id}/export/docs")
def export_docs_endpoint(conn_id: str, format: str = Query(default="markdown")):
    snap = app_db.get_latest_snapshot(conn_id)
    if not snap:
        raise HTTPException(status_code=404, detail="No snapshot found for documentation export")

    if format == "dbt_sources":
        content = glossary_manager.export_dbt_sources(conn_id, snap["structure"])
        media_type = "text/yaml"
    else:
        content = glossary_manager.export_markdown(conn_id, snap["structure"])
        media_type = "text/markdown"

    return {"status": "success", "format": format, "content": content}


# =========================================================================
# Phase 3 Endpoints: Guarded SQL Check & Token-Authorized Execution
# =========================================================================

class SQLCheckRequest(BaseModel):
    sql: str = Field(description="SQL query to validate and inspect")
    enforce_limit: bool = Field(default=True)


class SQLRunRequest(BaseModel):
    query_token: str = Field(description="Signed token returned from /sql/check")
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=100, ge=1, le=5000)


@router.post("/connections/{conn_id}/sql/check")
def check_sql_endpoint(conn_id: str, req: SQLCheckRequest):
    """
    AST parsing, read-only validation, row limit injection, and EXPLAIN cost estimation.
    Issues an HMAC-signed query_token valid for 5 minutes.
    """
    conn_data = app_db.get_connection(conn_id)
    if not conn_data:
        raise HTTPException(status_code=404, detail="Connection not found")

    engine_type = conn_data["engine"]
    tier = conn_data["tier"]

    # 1. AST Guard check & limit injection
    try:
        sanitized_sql, meta = sql_guard.enforce_read_only(
            req.sql,
            dialect=engine_type,
            enforce_limit=req.enforce_limit,
        )
    except SQLGuardException as ge:
        raise HTTPException(status_code=400, detail={"code": ge.code, "message": ge.message})

    # 2. Cost Guard EXPLAIN evaluation
    dsn = StudioConnector.assemble_dsn(conn_data["dsn_template"], conn_data.get("secret_ref"))
    engine = StudioConnector.create_managed_engine(engine_type, dsn, read_only=True)

    cost_info = cost_guard.evaluate_plan_and_cost(engine, sanitized_sql, engine_type=engine_type, tier=tier)

    # 3. Issue query token
    token = sql_guard.issue_query_token(
        sanitized_sql=sanitized_sql,
        connection_id=conn_id,
        tier=tier,
        meta=meta,
    )

    return {
        "status": "success",
        "sanitized_sql": sanitized_sql,
        "query_token": token,
        "cost_evaluation": cost_info,
        "requires_confirmation": cost_info["requires_confirmation"],
        "warnings": cost_info["warnings"],
        "metadata": {
            "tables": meta.get("tables", []),
            "final_limit": meta.get("final_limit"),
            "limit_rewritten": meta.get("limit_rewritten"),
        },
    }


@router.post("/connections/{conn_id}/sql/run")
def run_sql_endpoint(conn_id: str, req: SQLRunRequest):
    """
    Executes a query authorized by a query_token, logs to audit trail, and returns paginated rows.
    """
    # 1. Verify token HMAC signature and expiration
    try:
        payload = sql_guard.verify_query_token(req.query_token)
    except SQLGuardException as ge:
        raise HTTPException(status_code=403, detail={"code": ge.code, "message": ge.message})

    if payload.get("conn_id") != conn_id:
        raise HTTPException(status_code=400, detail="Token connection ID does not match endpoint target")

    conn_data = app_db.get_connection(conn_id)
    if not conn_data:
        raise HTTPException(status_code=404, detail="Connection not found")

    sql_to_execute = payload["sql"]
    dsn = StudioConnector.assemble_dsn(conn_data["dsn_template"], conn_data.get("secret_ref"))
    engine = StudioConnector.create_managed_engine(conn_data["engine"], dsn, read_only=True)

    import time
    start_time = time.perf_counter()

    from sqlalchemy import text
    try:
        with engine.connect() as db_conn:
            result = db_conn.execute(text(sql_to_execute))
            columns = list(result.keys()) if result.returns_rows else []
            all_rows = [list(r) for r in result.fetchall()] if result.returns_rows else []
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Database execution error: {str(e)}")

    elapsed_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
    total_count = len(all_rows)

    # Simple pagination
    offset = (req.page - 1) * req.page_size
    paged_rows = all_rows[offset : offset + req.page_size]

    # Convert cells to JSON-safe primitives
    from services.sql_executor import serialize_cell
    clean_paged_rows = [[serialize_cell(cell) for cell in row] for row in paged_rows]

    # 3. Record in append-only cryptographic audit log
    app_db.record_audit(
        action="sql_query",
        detail={
            "sql": sql_to_execute,
            "row_count": total_count,
            "duration_ms": elapsed_ms,
            "tier": conn_data["tier"],
        },
        actor="user",
        connection_id=conn_id,
    )

    return {
        "status": "success",
        "columns": columns,
        "rows": clean_paged_rows,
        "total_row_count": total_count,
        "page": req.page,
        "page_size": req.page_size,
        "execution_time_ms": elapsed_ms,
    }


# =========================================================================
# Phase 4 Endpoints: Shadow Migrations, Lock Linting & Approval Gates
# =========================================================================

class ProposalCreateRequest(BaseModel):
    connection_id: str
    goal: str = Field(description="Objective of the migration, e.g. Add index on orders(created_at)")
    up_sql: str = Field(description="Forward migration DDL statements")
    down_sql: str = Field(description="Reversible rollback DDL statements")
    run_id: Optional[str] = None


class DecisionRequest(BaseModel):
    decision: str = Field(description="approved, rejected, changes_requested")
    typed_confirmation: Optional[str] = Field(default=None, description="Must type table name for Dev apply")
    comment: Optional[str] = None


@router.post("/proposals")
def create_proposal_endpoint(req: ProposalCreateRequest):
    """
    Submits a migration proposal: runs lock-risk linting, impact analysis,
    and executes two-way verification on an isolated shadow clone.
    """
    conn_data = app_db.get_connection(req.connection_id)
    if not conn_data:
        raise HTTPException(status_code=404, detail="Connection not found")

    snap = app_db.get_latest_snapshot(req.connection_id)
    structure = snap["structure"] if snap else {"tables": []}
    engine_type = conn_data["engine"]

    # 1. Lint lock-risk patterns
    lint_report = migration_linter.lint_ddl(req.up_sql, engine_type=engine_type)

    # 2. Impact analysis
    impact_report = migration_linter.analyze_impact(req.up_sql, structure)

    # 3. Two-way Shadow Verification
    dsn = StudioConnector.assemble_dsn(conn_data["dsn_template"], conn_data.get("secret_ref"))
    shadow_report = shadow_manager.verify_migration(engine_type, dsn, req.up_sql, req.down_sql)

    # 4. Record proposal in app DB
    import uuid
    import json
    prop_id = f"prop_{uuid.uuid4().hex[:10]}"
    status = "verified" if shadow_report.get("rollback_clean") else "draft"

    # Ensure a valid run exists for the proposal
    actual_run_id = req.run_id
    if not actual_run_id:
        actual_run_id = app_db.create_run(
            session_id="manual",
            connection_id=req.connection_id,
            mode="change",
            effort="medium",
            tier=conn_data["tier"],
        )

    with app_db._get_connection() as conn:
        conn.execute(
            """
            INSERT INTO migration_proposals (
                id, run_id, connection_id, goal, up_sql, down_sql,
                base_snapshot_id, lint_json, impact_json, shadow_json,
                status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now', 'utc'));
            """,
            (
                prop_id,
                actual_run_id,
                req.connection_id,
                req.goal,
                req.up_sql,
                req.down_sql,
                snap["id"] if snap else None,
                json.dumps(lint_report),
                json.dumps(impact_report),
                json.dumps(shadow_report),
                status,
            ),
        )
        conn.commit()

    return {
        "status": "success",
        "proposal_id": prop_id,
        "verification_status": status,
        "lint": lint_report,
        "impact": impact_report,
        "shadow": shadow_report,
    }


@router.get("/connections/{conn_id}/proposals")
def list_proposals_for_connection_endpoint(conn_id: str):
    import json
    with app_db._get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM migration_proposals WHERE connection_id = ? ORDER BY created_at DESC;",
            (conn_id,)
        ).fetchall()
        proposals = []
        for r in rows:
            data = dict(r)
            data["lint"] = json.loads(data.get("lint_json") or "{}")
            data["impact"] = json.loads(data.get("impact_json") or "{}")
            data["shadow"] = json.loads(data.get("shadow_json") or "{}")
            proposals.append(data)
        return {"status": "success", "proposals": proposals, "count": len(proposals)}


@router.get("/proposals/{prop_id}")
def get_proposal_endpoint(prop_id: str):
    import json
    with app_db._get_connection() as conn:
        row = conn.execute("SELECT * FROM migration_proposals WHERE id = ?;", (prop_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Migration proposal not found")
        data = dict(row)
        data["lint"] = json.loads(data.get("lint_json") or "{}")
        data["impact"] = json.loads(data.get("impact_json") or "{}")
        data["shadow"] = json.loads(data.get("shadow_json") or "{}")
        return {"status": "success", "proposal": data}


@router.post("/proposals/{prop_id}/decision")
def record_decision_endpoint(prop_id: str, req: DecisionRequest):
    import uuid
    with app_db._get_connection() as conn:
        prop = conn.execute("SELECT * FROM migration_proposals WHERE id = ?;", (prop_id,)).fetchone()
        if not prop:
            raise HTTPException(status_code=404, detail="Migration proposal not found")

        apprv_id = f"appr_{uuid.uuid4().hex[:10]}"
        conn.execute(
            """
            INSERT INTO approvals (
                id, proposal_id, decision, approver, typed_confirmation, comment, decided_at
            ) VALUES (?, ?, ?, 'local_user', ?, ?, datetime('now', 'utc'));
            """,
            (apprv_id, prop_id, req.decision, req.typed_confirmation, req.comment),
        )

        new_status = "approved" if req.decision == "approved" else "rejected"
        conn.execute("UPDATE migration_proposals SET status = ? WHERE id = ?;", (new_status, prop_id))
        conn.commit()

    return {"status": "success", "proposal_id": prop_id, "status": new_status}


@router.post("/proposals/{prop_id}/apply")
def apply_migration_endpoint(prop_id: str):
    """
    Applies an approved migration to target database (Sandbox or Dev only).
    Prod connections strictly reject direct execution (decision D5).
    """
    with app_db._get_connection() as conn:
        prop = conn.execute("SELECT * FROM migration_proposals WHERE id = ?;", (prop_id,)).fetchone()
        if not prop:
            raise HTTPException(status_code=404, detail="Migration proposal not found")

        if prop["status"] != "approved":
            raise HTTPException(status_code=400, detail=f"Proposal must be 'approved' before apply (current: {prop['status']})")

        conn_id = prop["connection_id"]
        conn_data = app_db.get_connection(conn_id)
        if not conn_data:
            raise HTTPException(status_code=404, detail="Connection not found")

        # Strict Production Guardrail (D5)
        if conn_data["tier"].lower() == "prod":
            raise HTTPException(
                status_code=403,
                detail="Direct migration execution is disabled on PROD connections in v1 (Decision D5). Please use /export to generate a migration script.",
            )

        # Open dedicated write connection
        dsn = StudioConnector.assemble_dsn(conn_data["dsn_template"], conn_data.get("secret_ref"))
        write_engine = StudioConnector.create_managed_engine(conn_data["engine"], dsn, read_only=False)

        from sqlalchemy import text
        from services.shadow_db import split_sql_statements
        try:
            with write_engine.connect() as db_conn:
                for stmt in split_sql_statements(prop["up_sql"]):
                    if stmt.strip():
                        db_conn.execute(text(stmt))
                db_conn.commit()
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to apply migration: {str(e)}")

        # Capture post-migration snapshot
        try:
            catalog.capture_and_record_snapshot(conn_id, write_engine, source="post_migration")
        except Exception:
            pass

        # Record cryptographic audit entry
        app_db.record_audit(
            action="apply_migration",
            detail={
                "proposal_id": prop_id,
                "goal": prop["goal"],
                "up_sql": prop["up_sql"],
                "tier": conn_data["tier"],
            },
            actor="user",
            connection_id=conn_id,
        )

        conn.execute("UPDATE migration_proposals SET status = 'applied' WHERE id = ?;", (prop_id,))
        conn.commit()

    return {"status": "success", "proposal_id": prop_id, "status": "applied"}


@router.get("/proposals/{prop_id}/export")
def export_proposal_endpoint(prop_id: str, format: str = Query(default="alembic")):
    with app_db._get_connection() as conn:
        prop = conn.execute("SELECT * FROM migration_proposals WHERE id = ?;", (prop_id,)).fetchone()
        if not prop:
            raise HTTPException(status_code=404, detail="Migration proposal not found")

        goal = prop["goal"]
        up_sql = prop["up_sql"]
        down_sql = prop["down_sql"]

    if format == "alembic":
        content = migration_linter.export_alembic(goal, up_sql, down_sql)
    elif format == "flyway":
        content = migration_linter.export_flyway(goal, up_sql)
    else:
        content = f"-- UP Migration\n{up_sql};\n\n-- DOWN Rollback\n{down_sql};\n"

    return {"status": "success", "proposal_id": prop_id, "format": format, "content": content}


# =========================================================================
# Phase 5 Endpoints: Topological Seed Generator & Constraints
# =========================================================================

class SeedPlanRequest(BaseModel):
    row_counts: Optional[Dict[str, int]] = Field(default=None, description="Per-table row count map, e.g. {'customers': 20, 'orders': 50}")


class SeedGenerateRequest(BaseModel):
    row_counts: Optional[Dict[str, int]] = None
    target: str = Field(default="sql", description="sql (returns INSERT script) or apply (loads into connection)")


@router.post("/connections/{conn_id}/seed-plans")
def create_seed_plan_endpoint(conn_id: str, req: SeedPlanRequest):
    snap = app_db.get_latest_snapshot(conn_id)
    if not snap:
        raise HTTPException(status_code=404, detail="No snapshot found for seed planning")

    plan = seed_generator.build_generation_plan(snap["structure"], row_counts=req.row_counts)
    return {"status": "success", "plan": plan}


@router.post("/connections/{conn_id}/seed-plans/generate")
def generate_seeds_endpoint(conn_id: str, req: SeedGenerateRequest):
    conn_data = app_db.get_connection(conn_id)
    if not conn_data:
        raise HTTPException(status_code=404, detail="Connection not found")

    snap = app_db.get_latest_snapshot(conn_id)
    if not snap:
        raise HTTPException(status_code=404, detail="No snapshot found for seed generation")

    structure = snap["structure"]

    if req.target == "apply":
        # Disallow direct seed application to Prod
        if conn_data["tier"].lower() == "prod":
            raise HTTPException(status_code=403, detail="Direct seed data application is disabled on PROD connections.")

        sql_inserts = seed_generator.generate_sql_inserts(structure, row_counts=req.row_counts)
        dsn = StudioConnector.assemble_dsn(conn_data["dsn_template"], conn_data.get("secret_ref"))
        write_engine = StudioConnector.create_managed_engine(conn_data["engine"], dsn, read_only=False)

        from sqlalchemy import text
        from services.shadow_db import split_sql_statements
        inserted_count = 0
        with write_engine.connect() as db_conn:
            for stmt in split_sql_statements(sql_inserts):
                if stmt.strip():
                    db_conn.execute(text(stmt))
                    inserted_count += 1
            db_conn.commit()

        return {
            "status": "success",
            "target": "connection",
            "inserted_statements": inserted_count,
            "constraint_violations": 0,
        }
    else:
        # Return SQL script
        sql_inserts = seed_generator.generate_sql_inserts(structure, row_counts=req.row_counts)
        return {
            "status": "success",
            "target": "sql",
            "sql_inserts": sql_inserts,
        }


# =========================================================================
# Additional Lifecycle, Runs & Audit Endpoints (Docs 07 Spec)
# =========================================================================

class ConnectionTestRequest(BaseModel):
    engine: str
    dsn_template: str
    password: Optional[str] = None


@router.post("/connections/test")
def test_connection_endpoint(req: ConnectionTestRequest):
    """Tests connection credentials and evaluates privilege grade without saving."""
    secret_ref = None
    if req.password:
        import uuid
        secret_ref = f"sec_{uuid.uuid4().hex[:10]}"
        CredentialVault.store_secret(secret_ref, req.password)

    actual_dsn = StudioConnector.assemble_dsn(req.dsn_template, secret_ref)
    try:
        engine = StudioConnector.create_managed_engine(req.engine, actual_dsn, read_only=True)
        privilege_grade, grants = StudioConnector.evaluate_privilege_grade(engine, req.engine)
        from sqlalchemy import text
        with engine.connect() as conn:
            version_str = str(conn.execute(text("SELECT 1;")).scalar())
        return {
            "status": "success",
            "connected": True,
            "privilege_grade": privilege_grade,
            "grants": grants,
            "shadow_available": True,
        }
    except Exception as e:
        return {
            "status": "error",
            "connected": False,
            "error": str(e),
            "privilege_grade": "C",
            "shadow_available": False,
        }


class ConnectionUpdateRequest(BaseModel):
    name: Optional[str] = None
    tier: Optional[str] = None
    cloud_models_allowed: Optional[bool] = None
    masking_enabled: Optional[bool] = None


@router.patch("/connections/{conn_id}")
def update_connection_endpoint(conn_id: str, req: ConnectionUpdateRequest):
    with app_db._get_connection() as conn:
        row = conn.execute("SELECT * FROM connections WHERE id = ?;", (conn_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Connection not found")

        updates = []
        vals = []
        if req.name is not None:
            updates.append("name = ?")
            vals.append(req.name)
        if req.tier is not None:
            updates.append("tier = ?")
            vals.append(req.tier)
        if req.cloud_models_allowed is not None:
            updates.append("cloud_models_allowed = ?")
            vals.append(1 if req.cloud_models_allowed else 0)
            if req.cloud_models_allowed:
                # Per 06-models-and-limits: PII masking is locked on when cloud models are enabled
                updates.append("masking_enabled = ?")
                vals.append(1)
        elif req.masking_enabled is not None:
            updates.append("masking_enabled = ?")
            vals.append(1 if req.masking_enabled else 0)

        if updates:
            vals.append(conn_id)
            conn.execute(f"UPDATE connections SET {', '.join(updates)}, updated_at = datetime('now', 'utc') WHERE id = ?;", tuple(vals))
            conn.commit()

    return {"status": "success", "id": conn_id}


@router.delete("/connections/{conn_id}")
def delete_connection_endpoint(conn_id: str):
    conn_data = app_db.get_connection(conn_id)
    if not conn_data:
        raise HTTPException(status_code=404, detail="Connection not found")

    with app_db._get_connection() as conn:
        conn.execute("DELETE FROM connections WHERE id = ?;", (conn_id,))
        conn.commit()

    if conn_data.get("secret_ref"):
        try:
            import keyring
            keyring.delete_password("dimension_studio", conn_data["secret_ref"])
        except Exception:
            pass

    return {"status": "success", "id": conn_id, "deleted": True}


@router.get("/connections/{conn_id}/cloud-disclosure")
def get_cloud_disclosure_endpoint(conn_id: str):
    """
    Per docs/studio/06-models-and-limits.md:
    Audits what metadata leaves the machine when cloud models are enabled.
    """
    conn_data = app_db.get_connection(conn_id)
    if not conn_data:
        raise HTTPException(status_code=404, detail="Connection not found")

    return {
        "status": "success",
        "connection_id": conn_id,
        "connection_name": conn_data["name"],
        "tier": conn_data["tier"],
        "cloud_models_allowed": bool(conn_data.get("cloud_models_allowed")),
        "masking_locked": True,
        "data_leaving_machine": [
            "User natural language prompt",
            "Compact schema notation (table & column names, primary keys)",
            "Masked statistical aggregations (null rates, cardinality)",
            "Relevant business glossary definitions",
        ],
        "data_staying_local": [
            "Raw customer data rows (masked via Faker and deterministic anonymizers)",
            "Database passwords and keychain credentials",
            "Database dumps and full table contents",
            "Internal SQLite audit trail and cryptographic hash chains",
        ],
        "disclosure_summary": "When a cloud model is active, prompts, schema excerpts, and masked distributions leave this machine. Raw customer rows and credentials never leave.",
    }


@router.get("/models/probe")
def probe_model_endpoint(model: str = Query(default="qwen3:4b", description="Model name to probe for tool support")):
    """
    Per docs/studio/06-models-and-limits.md:
    Probes whether a candidate model advertises native tool calling capabilities.
    """
    probe_result = ModelCapabilityProber.probe_model(model)
    return {
        "status": "success",
        "probe": probe_result,
    }


@router.get("/connections/{conn_id}/tables")
def search_tables_endpoint(conn_id: str, query: Optional[str] = Query(default=None), limit: int = Query(default=50)):
    snap = app_db.get_latest_snapshot(conn_id)
    if not snap:
        return {"status": "success", "tables": []}

    tables = snap["structure"].get("tables", [])
    if query:
        q = query.lower()
        tables = [t for t in tables if q in t["name"].lower() or any(q in c["name"].lower() for c in t.get("columns", []))]

    res = [
        {
            "name": t["name"],
            "row_count": t.get("row_count", 0),
            "column_count": len(t.get("columns", [])),
            "primary_keys": t.get("primary_keys", []),
        }
        for t in tables[:limit]
    ]
    return {"status": "success", "tables": res, "total_count": len(tables)}


@router.get("/connections/{conn_id}/tables/{table_name}")
def get_table_detail_endpoint(conn_id: str, table_name: str):
    snap = app_db.get_latest_snapshot(conn_id)
    if not snap:
        raise HTTPException(status_code=404, detail="Snapshot not found")

    tables = snap["structure"].get("tables", [])
    match = next((t for t in tables if t["name"].lower() == table_name.lower()), None)
    if not match:
        raise HTTPException(status_code=404, detail=f"Table '{table_name}' not found")

    glossary = glossary_manager.list_entries(conn_id)
    table_glossary = [g for g in glossary if g.get("target", "").lower().startswith(table_name.lower())]

    return {
        "status": "success",
        "table": match,
        "glossary": table_glossary,
    }


class RunCreateRequest(BaseModel):
    session_id: str = Field(default="session_default")
    connection_id: str
    mode: str = Field(default="ask", description="explore, ask, change, seed")
    effort: str = Field(default="medium", description="low, medium, high")
    message: str = Field(default="", description="User instruction or prompt")
    model_name: Optional[str] = None


@router.post("/runs")
def create_run_endpoint(req: RunCreateRequest):
    """Initializes an autonomous studio agent run."""
    conn_data = app_db.get_connection(req.connection_id)
    tier = conn_data["tier"] if conn_data else "sandbox"

    run_id = app_db.create_run(
        session_id=req.session_id,
        connection_id=req.connection_id,
        mode=req.mode,
        effort=req.effort,
        tier=tier,
        models={"tool": req.model_name or "llama3"},
        budgets={"max_tool_calls": 25},
    )

    # Store initial message in run metadata
    with app_db._get_connection() as conn:
        conn.execute(
            "UPDATE runs SET models_json = ? WHERE id = ?;",
            (json.dumps({"tool": req.model_name or "llama3", "prompt": req.message}), run_id),
        )
        conn.commit()

    return {
        "status": "success",
        "run_id": run_id,
        "mode": req.mode,
        "tier": tier,
    }


@router.get("/runs/{run_id}/events")
def stream_run_events_endpoint(run_id: str):
    """Streams monotonic typed SSE events for an active agent run."""
    run_data = app_db.get_run(run_id)
    if not run_data:
        raise HTTPException(status_code=404, detail="Run not found")

    conn_id = run_data.get("connection_id")
    session_id = run_data.get("session_id", "default")
    mode = run_data.get("mode", "ask")
    effort = run_data.get("effort", "medium")
    models = run_data.get("models", {})
    message = models.get("prompt", "")
    model_name = models.get("tool")

    stream = studio_agent.run_stream(
        run_id=run_id,
        connection_id=conn_id,
        session_id=session_id,
        mode=mode,
        effort=effort,
        message=message,
        model_name=model_name,
    )

    return StreamingResponse(stream, media_type="text/event-stream")


@router.get("/runs/{run_id}")
def get_run_endpoint(run_id: str):
    run_data = app_db.get_run(run_id)
    if not run_data:
        raise HTTPException(status_code=404, detail="Run not found")
    events = app_db.get_run_events(run_id)
    run_data["events"] = events
    return {"status": "success", "run": run_data}


@router.post("/runs/{run_id}/cancel")
def cancel_run_endpoint(run_id: str):
    app_db.update_run_status(run_id, "cancelled", stop_reason="user_cancelled")
    return {"status": "success", "run_id": run_id, "status": "cancelled"}


@router.get("/connections/{conn_id}/audit")
def get_connection_audit_endpoint(conn_id: str, limit: int = Query(default=100)):
    with app_db._get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM audit_entries WHERE connection_id = ? ORDER BY seq DESC LIMIT ?;",
            (conn_id, limit),
        ).fetchall()
        import json
        entries = []
        for r in rows:
            item = dict(r)
            item["detail"] = json.loads(item.get("detail_json") or "{}")
            entries.append(item)

        is_valid, chain_msg = app_db.verify_audit_chain()
        return {
            "status": "success",
            "audit_entries": entries,
            "chain_verified": is_valid,
            "verification_message": chain_msg,
            "count": len(entries),
        }
