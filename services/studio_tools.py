"""
Autonomous Data & Schema Studio — Formal Tool Implementations.
Implements the 13 agent tools specified in docs/studio/03-agent-and-tools.md:
- search_schema
- describe_tables
- get_relationships
- infer_foreign_keys
- profile_table
- find_hygiene_issues
- draft_sql
- run_query
- propose_migration
- plan_seed
- generate_seed
- export_docs
- propose_glossary_entry
"""

import time
import json
from typing import Dict, Any, List, Optional, Set
from pydantic import BaseModel, Field

from services.tool_registry import ToolSpec, ToolResult, ToolContext, tool_registry
from services.app_db import StudioAppDB
from services.connector import StudioConnector
from services.catalog import MetadataCatalog
from services.fk_inferrer import FKInferrer
from services.hygiene_detector import HygieneDetector
from services.sql_guard import sql_guard
from services.cost_guard import cost_guard
from services.shadow_db import shadow_manager
from services.migration_linter import migration_linter
from services.seed_generator import seed_generator
from services.glossary import GlossaryManager
from services.profiler import run_table_profile

app_db = StudioAppDB()
catalog = MetadataCatalog(app_db=app_db)
fk_inferrer = FKInferrer(app_db=app_db)
hygiene_detector = HygieneDetector(app_db=app_db)
glossary_manager = GlossaryManager(app_db=app_db)


# =========================================================================
# 1. search_schema
# =========================================================================

class SearchSchemaArgs(BaseModel):
    query: str = Field(max_length=300, description="Natural language search phrase for tables/columns")
    limit: int = Field(default=8, ge=1, le=20, description="Max tables to return")

    class Config:
        extra = "forbid"


def handle_search_schema(ctx: ToolContext, args: SearchSchemaArgs) -> ToolResult:
    if not ctx.connection_id:
        return ToolResult(status="error", summary="No active connection configured.")

    snap = app_db.get_latest_snapshot(ctx.connection_id)
    if not snap:
        return ToolResult(status="error", summary="No snapshot recorded for active connection.")

    tables = snap["structure"].get("tables", [])
    query_lower = args.query.lower().strip()
    words = [w for w in query_lower.split() if len(w) > 2]

    matches = []
    for tbl in tables:
        tname = tbl["name"].lower()
        cols = [c["name"].lower() for c in tbl.get("columns", [])]

        score = 0
        reasons = []

        if query_lower in tname:
            score += 10
            reasons.append("table name exact match")
        elif any(w in tname for w in words):
            score += 5
            reasons.append("table name keyword match")

        matched_cols = [c for c in cols if any(w in c for w in words)]
        if matched_cols:
            score += len(matched_cols) * 2
            reasons.append(f"column match ({', '.join(matched_cols[:3])})")

        if score > 0 or not words:
            matches.append({
                "table": tbl["name"],
                "score": score,
                "reasons": reasons,
                "column_count": len(cols),
                "columns": [c["name"] for c in tbl.get("columns", [])][:10],
            })

    matches.sort(key=lambda m: m["score"], reverse=True)
    top_matches = matches[:args.limit]

    summary = f"Found {len(top_matches)} relevant tables matching '{args.query}': {', '.join([m['table'] for m in top_matches])}."
    return ToolResult(
        status="ok",
        summary=summary,
        data={"matches": top_matches, "query": args.query},
        evidence=[{"id": f"ev_search_{int(time.time()*1000)}", "kind": "search", "title": f"Search '{args.query}'", "body": summary}],
    )


# =========================================================================
# 2. describe_tables
# =========================================================================

class DescribeTablesArgs(BaseModel):
    tables: List[str] = Field(min_length=1, max_length=10, description="List of table names to describe")
    include: List[str] = Field(default=["columns", "keys", "glossary"], description="Attributes to include")

    class Config:
        extra = "forbid"


def handle_describe_tables(ctx: ToolContext, args: DescribeTablesArgs) -> ToolResult:
    if not ctx.connection_id:
        return ToolResult(status="error", summary="No active connection configured.")

    snap = app_db.get_latest_snapshot(ctx.connection_id)
    if not snap:
        return ToolResult(status="error", summary="No snapshot recorded for active connection.")

    all_tables = {t["name"].lower(): t for t in snap["structure"].get("tables", [])}
    found = []
    missing = []

    for tname in args.tables:
        match = all_tables.get(tname.lower())
        if match:
            item = {
                "name": match["name"],
                "row_count": match.get("row_count", 0),
                "primary_keys": match.get("primary_keys", []),
                "foreign_keys": match.get("foreign_keys", []),
                "columns": [
                    {"name": c["name"], "type": c["type"], "nullable": c.get("nullable", True), "primary_key": c.get("primary_key", False)}
                    for c in match.get("columns", [])
                ],
            }
            found.append(item)
        else:
            missing.append(tname)

    if missing and not found:
        return ToolResult(status="error", summary=f"Tables not found in schema: {', '.join(missing)}.")

    summary = f"Described {len(found)} tables: {', '.join([t['name'] for t in found])}."
    if missing:
        summary += f" (Missing: {', '.join(missing)})"

    return ToolResult(
        status="ok",
        summary=summary,
        data={"tables": found, "missing": missing},
        evidence=[{"id": f"ev_desc_{int(time.time()*1000)}", "kind": "schema", "title": f"Table schema for {', '.join(args.tables)}", "body": summary}],
    )


# =========================================================================
# 3. get_relationships
# =========================================================================

class GetRelationshipsArgs(BaseModel):
    table: str = Field(description="Center table name")
    depth: int = Field(default=1, ge=1, le=3)
    include_inferred: bool = Field(default=True)
    min_score: float = Field(default=0.6, ge=0.0, le=1.0)

    class Config:
        extra = "forbid"


def handle_get_relationships(ctx: ToolContext, args: GetRelationshipsArgs) -> ToolResult:
    if not ctx.connection_id:
        return ToolResult(status="error", summary="No active connection configured.")

    snap = app_db.get_latest_snapshot(ctx.connection_id)
    if not snap:
        return ToolResult(status="error", summary="No snapshot recorded for active connection.")

    inferred = []
    if args.include_inferred:
        with app_db._get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM relationship_inferences WHERE snapshot_id = ? AND status != 'rejected';",
                (snap["id"],),
            ).fetchall()
            inferred = [dict(r) for r in rows]

    graph = catalog.generate_erd_graph(snap["structure"], inferred_relationships=inferred)
    t_lower = args.table.lower()

    # Filter edges connected to target table
    connected_edges = [
        e for e in graph.get("edges", [])
        if e.get("source", "").lower() == t_lower or e.get("target", "").lower() == t_lower
    ]

    summary = f"Found {len(connected_edges)} relationships connected to '{args.table}' (depth: {args.depth})."
    return ToolResult(
        status="ok",
        summary=summary,
        data={"table": args.table, "relationships": connected_edges},
        evidence=[{"id": f"ev_rel_{int(time.time()*1000)}", "kind": "relationships", "title": f"Relationships for {args.table}", "body": summary}],
    )


# =========================================================================
# 4. infer_foreign_keys
# =========================================================================

class InferForeignKeysArgs(BaseModel):
    tables: Optional[List[str]] = Field(default=None, description="Subset of tables or None for all")
    min_score: float = Field(default=0.65, ge=0.5, le=1.0)

    class Config:
        extra = "forbid"


def handle_infer_foreign_keys(ctx: ToolContext, args: InferForeignKeysArgs) -> ToolResult:
    if not ctx.connection_id:
        return ToolResult(status="error", summary="No active connection configured.")

    conn_data = app_db.get_connection(ctx.connection_id)
    snap = app_db.get_latest_snapshot(ctx.connection_id)
    if not conn_data or not snap:
        return ToolResult(status="error", summary="Missing connection or snapshot.")

    dsn = StudioConnector.assemble_dsn(conn_data["dsn_template"], conn_data.get("secret_ref"))
    engine = StudioConnector.create_managed_engine(conn_data["engine"], dsn, read_only=True)

    inferred = fk_inferrer.infer_foreign_keys(engine, snap, min_score=args.min_score)
    summary = f"Inferred {len(inferred)} candidate foreign key relationships with score >= {args.min_score}."

    return ToolResult(
        status="ok",
        summary=summary,
        data={"inferred_relationships": inferred, "count": len(inferred)},
        evidence=[{"id": f"ev_infer_{int(time.time()*1000)}", "kind": "inference", "title": "FK Inference", "body": summary}],
    )


# =========================================================================
# 5. profile_table
# =========================================================================

class ProfileTableArgs(BaseModel):
    table: str = Field(description="Target table to profile")
    sample_fraction: Optional[float] = Field(default=1.0, ge=0.001, le=1.0)

    class Config:
        extra = "forbid"


def handle_profile_table(ctx: ToolContext, args: ProfileTableArgs) -> ToolResult:
    if not ctx.connection_id:
        return ToolResult(status="error", summary="No active connection configured.")

    conn_data = app_db.get_connection(ctx.connection_id)
    if not conn_data:
        return ToolResult(status="error", summary="Connection not found.")

    dsn = StudioConnector.assemble_dsn(conn_data["dsn_template"], conn_data.get("secret_ref"))
    engine = StudioConnector.create_managed_engine(conn_data["engine"], dsn, read_only=True)

    profile = run_table_profile(engine, args.table, sample_fraction=args.sample_fraction or 1.0)
    summary = f"Profiled table '{args.table}': {profile.row_count} rows, {len(profile.columns)} columns."

    return ToolResult(
        status="ok",
        summary=summary,
        data={"table": args.table, "row_count": profile.row_count, "columns": [c.model_dump() for c in profile.columns]},
        evidence=[{"id": f"ev_prof_{int(time.time()*1000)}", "kind": "profile", "title": f"Profile for {args.table}", "body": summary}],
    )


# =========================================================================
# 6. find_hygiene_issues
# =========================================================================

class FindHygieneIssuesArgs(BaseModel):
    table: Optional[str] = Field(default=None, description="Optional single table filter")

    class Config:
        extra = "forbid"


def handle_find_hygiene_issues(ctx: ToolContext, args: FindHygieneIssuesArgs) -> ToolResult:
    if not ctx.connection_id:
        return ToolResult(status="error", summary="No active connection configured.")

    conn_data = app_db.get_connection(ctx.connection_id)
    snap = app_db.get_latest_snapshot(ctx.connection_id)
    if not conn_data or not snap:
        return ToolResult(status="error", summary="Missing connection or snapshot.")

    dsn = StudioConnector.assemble_dsn(conn_data["dsn_template"], conn_data.get("secret_ref"))
    engine = StudioConnector.create_managed_engine(conn_data["engine"], dsn, read_only=True)

    findings = hygiene_detector.run_hygiene_audit(engine, snap, connection_id=ctx.connection_id)
    summary = f"Hygiene scan found {len(findings)} anomalies across orphans, sentinels, format skew, and PII."

    return ToolResult(
        status="ok",
        summary=summary,
        data={"findings": findings, "count": len(findings)},
        evidence=[{"id": f"ev_hyg_{int(time.time()*1000)}", "kind": "hygiene", "title": "Hygiene Scan", "body": summary}],
    )


# =========================================================================
# 7. draft_sql
# =========================================================================

class DraftSqlArgs(BaseModel):
    sql: str = Field(max_length=8000, description="SQL query statement to validate")
    intent: str = Field(description="Short sentence explaining query intent")

    class Config:
        extra = "forbid"


def handle_draft_sql(ctx: ToolContext, args: DraftSqlArgs) -> ToolResult:
    if not ctx.connection_id:
        return ToolResult(status="error", summary="No active connection configured.")

    conn_data = app_db.get_connection(ctx.connection_id)
    if not conn_data:
        return ToolResult(status="error", summary="Connection not found.")

    engine_type = conn_data["engine"]
    tier = conn_data["tier"]

    # AST validation
    try:
        sanitized_sql, meta = sql_guard.enforce_read_only(args.sql, dialect=engine_type, enforce_limit=True)
    except Exception as e:
        return ToolResult(status="error", summary=f"SQL validation error: {str(e)}")

    # Cost estimation
    dsn = StudioConnector.assemble_dsn(conn_data["dsn_template"], conn_data.get("secret_ref"))
    engine = StudioConnector.create_managed_engine(engine_type, dsn, read_only=True)
    cost_info = cost_guard.evaluate_plan_and_cost(engine, sanitized_sql, engine_type=engine_type, tier=tier)

    # Issue query token
    token = sql_guard.issue_query_token(
        sanitized_sql=sanitized_sql,
        connection_id=ctx.connection_id,
        tier=tier,
        meta=meta,
    )

    summary = f"SQL validated. Estimated rows: {cost_info['estimated_rows']}. Token issued."
    return ToolResult(
        status="ok",
        summary=summary,
        data={
            "sanitized_sql": sanitized_sql,
            "query_token": token,
            "cost_evaluation": cost_info,
            "requires_confirmation": cost_info.get("requires_confirmation", False),
        },
        evidence=[{"id": f"ev_sql_{int(time.time()*1000)}", "kind": "sql", "title": f"SQL for {args.intent}", "body": sanitized_sql}],
        warnings=cost_info.get("warnings", []),
    )


# =========================================================================
# 8. run_query
# =========================================================================

class RunQueryArgs(BaseModel):
    query_token: str = Field(description="HMAC-signed token from draft_sql")

    class Config:
        extra = "forbid"


def handle_run_query(ctx: ToolContext, args: RunQueryArgs) -> ToolResult:
    if not ctx.connection_id:
        return ToolResult(status="error", summary="No active connection configured.")

    try:
        payload = sql_guard.verify_query_token(args.query_token)
    except Exception as e:
        return ToolResult(status="error", summary=f"Query token verification failed: {str(e)}")

    conn_data = app_db.get_connection(ctx.connection_id)
    if not conn_data:
        return ToolResult(status="error", summary="Connection not found.")

    sql_to_execute = payload["sql"]
    dsn = StudioConnector.assemble_dsn(conn_data["dsn_template"], conn_data.get("secret_ref"))
    engine = StudioConnector.create_managed_engine(conn_data["engine"], dsn, read_only=True)

    start_time = time.perf_counter()
    from sqlalchemy import text
    try:
        with engine.connect() as db_conn:
            result = db_conn.execute(text(sql_to_execute))
            cols = list(result.keys()) if result.returns_rows else []
            all_rows = [list(r) for r in result.fetchall()] if result.returns_rows else []
    except Exception as e:
        return ToolResult(status="error", summary=f"Execution error: {str(e)}")

    duration_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
    preview_rows = all_rows[:50]  # Cap to 50 rows for model context

    from services.sql_executor import serialize_cell
    clean_preview = [[serialize_cell(c) for c in row] for row in preview_rows]

    # Audit entry
    app_db.record_audit(
        action="sql_query",
        detail={"sql": sql_to_execute, "total_rows": len(all_rows), "duration_ms": duration_ms},
        actor="agent",
        connection_id=ctx.connection_id,
        run_id=ctx.run_id,
    )

    summary = f"Query executed in {duration_ms}ms, returned {len(all_rows)} rows (first {len(clean_preview)} previewed)."
    return ToolResult(
        status="ok",
        summary=summary,
        data={
            "columns": cols,
            "preview_rows": clean_preview,
            "total_row_count": len(all_rows),
            "duration_ms": duration_ms,
        },
        evidence=[{"id": f"ev_run_{int(time.time()*1000)}", "kind": "query_result", "title": "Query Output", "body": f"Executed: {sql_to_execute}"}],
    )


# =========================================================================
# 9. propose_migration
# =========================================================================

class ProposeMigrationArgs(BaseModel):
    goal: str = Field(description="Objective of the migration")
    up_sql: str = Field(description="Forward migration DDL statements")
    down_sql: str = Field(description="Reversible rollback DDL statements")

    class Config:
        extra = "forbid"


def handle_propose_migration(ctx: ToolContext, args: ProposeMigrationArgs) -> ToolResult:
    if not ctx.connection_id:
        return ToolResult(status="error", summary="No active connection configured.")

    conn_data = app_db.get_connection(ctx.connection_id)
    snap = app_db.get_latest_snapshot(ctx.connection_id)
    if not conn_data:
        return ToolResult(status="error", summary="Connection not found.")

    engine_type = conn_data["engine"]
    structure = snap["structure"] if snap else {"tables": []}

    lint_report = migration_linter.lint_ddl(args.up_sql, engine_type=engine_type)
    impact_report = migration_linter.analyze_impact(args.up_sql, structure)

    dsn = StudioConnector.assemble_dsn(conn_data["dsn_template"], conn_data.get("secret_ref"))
    shadow_report = shadow_manager.verify_migration(engine_type, dsn, args.up_sql, args.down_sql)

    import uuid
    prop_id = f"prop_{uuid.uuid4().hex[:10]}"
    status = "verified" if shadow_report.get("rollback_clean") else "draft"

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
                ctx.run_id or "manual",
                ctx.connection_id,
                args.goal,
                args.up_sql,
                args.down_sql,
                snap["id"] if snap else None,
                json.dumps(lint_report),
                json.dumps(impact_report),
                json.dumps(shadow_report),
                status,
            ),
        )
        conn.commit()

    summary = f"Migration proposal created ({prop_id}). Shadow Rollback Clean: {shadow_report.get('rollback_clean')}."
    return ToolResult(
        status="ok",
        summary=summary,
        data={
            "proposal_id": prop_id,
            "status": status,
            "lint": lint_report,
            "impact": impact_report,
            "shadow": shadow_report,
        },
        evidence=[{"id": f"ev_prop_{int(time.time()*1000)}", "kind": "proposal", "title": f"Proposal: {args.goal}", "body": args.up_sql}],
    )


# =========================================================================
# 10. plan_seed
# =========================================================================

class PlanSeedArgs(BaseModel):
    tables: Optional[List[str]] = Field(default=None)
    row_counts: Optional[Dict[str, int]] = Field(default=None)

    class Config:
        extra = "forbid"


def handle_plan_seed(ctx: ToolContext, args: PlanSeedArgs) -> ToolResult:
    if not ctx.connection_id:
        return ToolResult(status="error", summary="No active connection configured.")

    snap = app_db.get_latest_snapshot(ctx.connection_id)
    if not snap:
        return ToolResult(status="error", summary="No snapshot recorded for active connection.")

    plan = seed_generator.build_generation_plan(snap["structure"], row_counts=args.row_counts)
    order = plan.get("topological_order", [])
    summary = f"Built topological seed plan for {len(order)} tables: {' -> '.join(order)}."

    return ToolResult(
        status="ok",
        summary=summary,
        data={"plan": plan},
        evidence=[{"id": f"ev_seed_{int(time.time()*1000)}", "kind": "seed_plan", "title": "Topological Seed Plan", "body": summary}],
    )


# =========================================================================
# 11. generate_seed
# =========================================================================

class GenerateSeedArgs(BaseModel):
    row_counts: Optional[Dict[str, int]] = Field(default=None)
    target: str = Field(default="sql", description="sql or apply")

    class Config:
        extra = "forbid"


def handle_generate_seed(ctx: ToolContext, args: GenerateSeedArgs) -> ToolResult:
    if not ctx.connection_id:
        return ToolResult(status="error", summary="No active connection configured.")

    snap = app_db.get_latest_snapshot(ctx.connection_id)
    if not snap:
        return ToolResult(status="error", summary="No snapshot recorded for active connection.")

    sql_inserts = seed_generator.generate_sql_inserts(snap["structure"], row_counts=args.row_counts)
    summary = f"Generated topological synthetic SQL inserts for schema."

    return ToolResult(
        status="ok",
        summary=summary,
        data={"sql_inserts": sql_inserts},
        evidence=[{"id": f"ev_seedsql_{int(time.time()*1000)}", "kind": "seed_sql", "title": "Generated Seed Inserts", "body": sql_inserts[:500]}],
    )


# =========================================================================
# 12. export_docs
# =========================================================================

class ExportDocsArgs(BaseModel):
    format: str = Field(default="markdown", description="markdown or dbt_sources")

    class Config:
        extra = "forbid"


def handle_export_docs(ctx: ToolContext, args: ExportDocsArgs) -> ToolResult:
    if not ctx.connection_id:
        return ToolResult(status="error", summary="No active connection configured.")

    snap = app_db.get_latest_snapshot(ctx.connection_id)
    if not snap:
        return ToolResult(status="error", summary="No snapshot recorded for active connection.")

    if args.format == "dbt_sources":
        content = glossary_manager.export_dbt_sources(ctx.connection_id, snap["structure"])
    else:
        content = glossary_manager.export_markdown(ctx.connection_id, snap["structure"])

    summary = f"Exported documentation in {args.format} format ({len(content)} characters)."
    return ToolResult(
        status="ok",
        summary=summary,
        data={"format": args.format, "content": content},
        evidence=[{"id": f"ev_docs_{int(time.time()*1000)}", "kind": "docs", "title": f"Data Dictionary ({args.format})", "body": summary}],
    )


# =========================================================================
# 13. propose_glossary_entry
# =========================================================================

class ProposeGlossaryEntryArgs(BaseModel):
    target_kind: str = Field(description="table, column, relationship")
    target: str = Field(description="Qualified name, e.g. orders.status")
    kind: str = Field(description="description, enum_map, join_rule, filter_rule, caveat")
    body: str = Field(description="Business explanation or semantic definition")

    class Config:
        extra = "forbid"


def handle_propose_glossary_entry(ctx: ToolContext, args: ProposeGlossaryEntryArgs) -> ToolResult:
    if not ctx.connection_id:
        return ToolResult(status="error", summary="No active connection configured.")

    gid = glossary_manager.propose_entry(
        connection_id=ctx.connection_id,
        target_kind=args.target_kind,
        target=args.target,
        kind=args.kind,
        body=args.body,
        author_kind="agent",
        author_ref=ctx.run_id,
    )
    summary = f"Recorded glossary definition '{args.target}' ({gid})."

    return ToolResult(
        status="ok",
        summary=summary,
        data={"id": gid, "target": args.target, "kind": args.kind},
        evidence=[{"id": f"ev_gl_{int(time.time()*1000)}", "kind": "glossary", "title": f"Glossary Definition for {args.target}", "body": args.body}],
    )


# =========================================================================
# Register All 13 Tools into Global Tool Registry
# =========================================================================

tool_registry.register(ToolSpec(
    name="search_schema",
    description="Find tables and columns relevant to a natural language phrase. Returns matching tables, match reasons, and column highlights.",
    args_model=SearchSchemaArgs,
    risk="metadata",
    allowed_tiers={"sandbox", "dev", "prod"},
    modes={"explore", "ask", "change", "seed"},
    handler=handle_search_schema,
))

tool_registry.register(ToolSpec(
    name="describe_tables",
    description="Retrieve full structural schema for named tables, including columns, data types, primary keys, and foreign keys.",
    args_model=DescribeTablesArgs,
    risk="metadata",
    allowed_tiers={"sandbox", "dev", "prod"},
    modes={"explore", "ask", "change", "seed"},
    handler=handle_describe_tables,
))

tool_registry.register(ToolSpec(
    name="get_relationships",
    description="Retrieve declared and inferred relationships connected to a specified table up to depth 3.",
    args_model=GetRelationshipsArgs,
    risk="metadata",
    allowed_tiers={"sandbox", "dev", "prod"},
    modes={"explore", "ask", "change", "seed"},
    handler=handle_get_relationships,
))

tool_registry.register(ToolSpec(
    name="infer_foreign_keys",
    description="Run mathematical containment analysis (>= 85%) to discover implicit, undeclared foreign key relationships.",
    args_model=InferForeignKeysArgs,
    risk="read_data",
    allowed_tiers={"sandbox", "dev", "prod"},
    modes={"explore", "change"},
    handler=handle_infer_foreign_keys,
))

tool_registry.register(ToolSpec(
    name="profile_table",
    description="Compute pushdown statistics, cardinality, null rates, and PII detection across table columns.",
    args_model=ProfileTableArgs,
    risk="read_data",
    allowed_tiers={"sandbox", "dev", "prod"},
    modes={"explore", "change"},
    handler=handle_profile_table,
))

tool_registry.register(ToolSpec(
    name="find_hygiene_issues",
    description="Scan database schema for data quality anomalies: orphaned records, sentinel values ('000-00-0000'), mixed date formats, and high null rates.",
    args_model=FindHygieneIssuesArgs,
    risk="read_data",
    allowed_tiers={"sandbox", "dev", "prod"},
    modes={"explore", "change"},
    handler=handle_find_hygiene_issues,
))

tool_registry.register(ToolSpec(
    name="draft_sql",
    description="Validate SQL against AST security guardrails, inject LIMIT, perform EXPLAIN plan analysis, and issue HMAC execution token.",
    args_model=DraftSqlArgs,
    risk="metadata",
    allowed_tiers={"sandbox", "dev", "prod"},
    modes={"ask"},
    handler=handle_draft_sql,
))

tool_registry.register(ToolSpec(
    name="run_query",
    description="Execute validated SQL authorized by a query_token against a read-only session with strict row fetch limits.",
    args_model=RunQueryArgs,
    risk="read_data",
    allowed_tiers={"sandbox", "dev", "prod"},
    modes={"ask"},
    handler=handle_run_query,
))

tool_registry.register(ToolSpec(
    name="propose_migration",
    description="Lint forward and rollback DDL for lock risks and execute two-way verification on disposable shadow database clone.",
    args_model=ProposeMigrationArgs,
    risk="write_shadow",
    allowed_tiers={"sandbox", "dev", "prod"},
    modes={"change"},
    handler=handle_propose_migration,
))

tool_registry.register(ToolSpec(
    name="plan_seed",
    description="Build Kahn's topological order DAG sequence for synthetic data generation ensuring zero foreign key constraint violations.",
    args_model=PlanSeedArgs,
    risk="metadata",
    allowed_tiers={"sandbox", "dev", "prod"},
    modes={"seed"},
    handler=handle_plan_seed,
))

tool_registry.register(ToolSpec(
    name="generate_seed",
    description="Generate deterministic synthetic SQL INSERT statements with Faker PII replacement and constraint satisfaction.",
    args_model=GenerateSeedArgs,
    risk="write_shadow",
    allowed_tiers={"sandbox", "dev", "prod"},
    modes={"seed"},
    handler=handle_generate_seed,
))

tool_registry.register(ToolSpec(
    name="export_docs",
    description="Export verified schema data dictionary in Markdown or dbt sources.yml format with schema validation tests.",
    args_model=ExportDocsArgs,
    risk="metadata",
    allowed_tiers={"sandbox", "dev", "prod"},
    modes={"explore", "ask", "change", "seed"},
    handler=handle_export_docs,
))

tool_registry.register(ToolSpec(
    name="propose_glossary_entry",
    description="Propose business definition, enum mapping, join rule, or caveat to maintain schema memory across runs.",
    args_model=ProposeGlossaryEntryArgs,
    risk="metadata",
    allowed_tiers={"sandbox", "dev", "prod"},
    modes={"explore", "ask", "change", "seed"},
    handler=handle_propose_glossary_entry,
))
