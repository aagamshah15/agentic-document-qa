"""
Autonomous Data & Schema Studio — Application Database & Audit Store.
Manages the internal SQLite database (data/studio_app.db), versioned migrations,
schema snapshots, run event sequencing, glossary memory, and hash-chained audit logging.
"""

import os
import sqlite3
import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class StudioAppDB:
    def __init__(self, db_path: Optional[str] = None):
        # STUDIO_APP_DB_PATH lets tests point every default instance at a throwaway DB
        if db_path is None:
            db_path = os.environ.get("STUDIO_APP_DB_PATH") or None
        if db_path is None:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            data_dir = os.path.join(base_dir, "data")
            os.makedirs(data_dir, exist_ok=True)
            self.db_path = os.path.join(data_dir, "studio_app.db")
        else:
            self.db_path = db_path
            os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)

        self._init_migrations()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA journal_mode = WAL;")
        return conn

    def _init_migrations(self):
        """Applies versioned SQL migrations in services/migrations/."""
        migrations_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "migrations")
        if not os.path.exists(migrations_dir):
            return

        with self._get_connection() as conn:
            # Ensure schema_versions table exists
            conn.execute("""
                CREATE TABLE IF NOT EXISTS schema_versions (
                    version INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    applied_at TEXT NOT NULL DEFAULT (datetime('now', 'utc'))
                );
            """)
            applied = {row[0] for row in conn.execute("SELECT version FROM schema_versions").fetchall()}

            migration_files = sorted(f for f in os.listdir(migrations_dir) if f.endswith(".sql"))
            for fname in migration_files:
                parts = fname.split("_", 1)
                try:
                    v_num = int(parts[0])
                except ValueError:
                    continue

                if v_num not in applied:
                    filepath = os.path.join(migrations_dir, fname)
                    with open(filepath, "r", encoding="utf-8") as f:
                        sql_script = f.read()
                    conn.executescript(sql_script)
                    conn.execute(
                        "INSERT INTO schema_versions (version, name, applied_at) VALUES (?, ?, ?);",
                        (v_num, fname, _utc_now_iso()),
                    )
            conn.commit()

    # =========================================================================
    # 1. Connections
    # =========================================================================

    def create_connection(
        self,
        name: str,
        engine: str,
        dsn_template: str,
        tier: str = "sandbox",
        secret_ref: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None,
        privilege_grade: str = "B",
        workspace_id: str = "default",
        cloud_models_allowed: bool = False,
        masking_enabled: bool = True,
        conn_id: Optional[str] = None,
    ) -> str:
        cid = conn_id or f"conn_{uuid.uuid4().hex[:12]}"
        now = _utc_now_iso()
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO connections (
                    id, workspace_id, name, engine, tier, dsn_template,
                    secret_ref, options_json, privilege_grade,
                    cloud_models_allowed, masking_enabled, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    cid,
                    workspace_id,
                    name,
                    engine.lower(),
                    tier.lower(),
                    dsn_template,
                    secret_ref,
                    json.dumps(options or {}),
                    privilege_grade.upper(),
                    1 if cloud_models_allowed else 0,
                    1 if masking_enabled else 0,
                    now,
                    now,
                ),
            )
            conn.commit()
        return cid

    def get_connection(self, conn_id: str) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM connections WHERE id = ?;", (conn_id,)).fetchone()
            if not row:
                return None
            data = dict(row)
            data["options"] = json.loads(data.get("options_json") or "{}")
            data["cloud_models_allowed"] = bool(data.get("cloud_models_allowed", 0))
            data["masking_enabled"] = bool(data.get("masking_enabled", 1))
            return data

    def list_connections(self, workspace_id: str = "default") -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM connections WHERE workspace_id = ? ORDER BY created_at DESC;",
                (workspace_id,),
            ).fetchall()
            results = []
            for r in rows:
                item = dict(r)
                item["options"] = json.loads(item.get("options_json") or "{}")
                item["cloud_models_allowed"] = bool(item.get("cloud_models_allowed", 0))
                item["masking_enabled"] = bool(item.get("masking_enabled", 1))
                results.append(item)
            return results

    # =========================================================================
    # 2. Schema Snapshots
    # =========================================================================

    def record_snapshot(
        self,
        connection_id: str,
        structure: Dict[str, Any],
        server_version: Optional[str] = None,
        source: str = "refresh",
    ) -> str:
        snap_id = f"snap_{uuid.uuid4().hex[:12]}"
        now = _utc_now_iso()
        norm_json = json.dumps(structure, sort_keys=True)
        content_hash = hashlib.sha256(norm_json.encode("utf-8")).hexdigest()

        tables = structure.get("tables", [])
        table_count = len(tables)
        col_count = sum(len(t.get("columns", [])) for t in tables)

        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO schema_snapshots (
                    id, connection_id, content_hash, server_version,
                    structure_json, table_count, column_count, created_at, source
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    snap_id,
                    connection_id,
                    content_hash,
                    server_version,
                    norm_json,
                    table_count,
                    col_count,
                    now,
                    source,
                ),
            )
            conn.commit()
        return snap_id

    def get_latest_snapshot(self, connection_id: str) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            row = conn.execute(
                """
                SELECT * FROM schema_snapshots
                WHERE connection_id = ?
                ORDER BY created_at DESC LIMIT 1;
                """,
                (connection_id,),
            ).fetchone()
            if not row:
                return None
            res = dict(row)
            res["structure"] = json.loads(res.get("structure_json") or "{}")
            return res

    def get_snapshot(self, snapshot_id: str) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM schema_snapshots WHERE id = ?;", (snapshot_id,)
            ).fetchone()
            if not row:
                return None
            res = dict(row)
            res["structure"] = json.loads(res.get("structure_json") or "{}")
            return res

    def list_snapshots(self, connection_id: str) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT id, connection_id, content_hash, server_version,
                       table_count, column_count, created_at, source
                FROM schema_snapshots
                WHERE connection_id = ?
                ORDER BY created_at DESC;
                """,
                (connection_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    # =========================================================================
    # 3. Runs & Typed Event Streaming
    # =========================================================================

    def create_run(
        self,
        session_id: str,
        connection_id: Optional[str],
        mode: str = "ask",
        effort: str = "medium",
        tier: str = "sandbox",
        models: Optional[Dict[str, str]] = None,
        budgets: Optional[Dict[str, Any]] = None,
    ) -> str:
        run_id = f"run_{uuid.uuid4().hex[:12]}"
        now = _utc_now_iso()
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO runs (
                    id, session_id, connection_id, mode, effort,
                    tier_at_start, models_json, budget_json, usage_json,
                    status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'running', ?, ?);
                """,
                (
                    run_id,
                    session_id,
                    connection_id,
                    mode,
                    effort,
                    tier,
                    json.dumps(models or {}),
                    json.dumps(budgets or {}),
                    json.dumps({}),
                    now,
                    now,
                ),
            )
            conn.commit()
        return run_id

    def append_run_event(self, run_id: str, event_type: str, payload: Dict[str, Any]) -> int:
        now = _utc_now_iso()
        with self._get_connection() as conn:
            # Monotonically increment seq for this run
            cur = conn.execute(
                "SELECT COALESCE(MAX(seq), 0) + 1 FROM run_events WHERE run_id = ?;",
                (run_id,),
            )
            seq = cur.fetchone()[0]

            conn.execute(
                """
                INSERT INTO run_events (run_id, seq, event_type, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?);
                """,
                (run_id, seq, event_type, json.dumps(payload), now),
            )
            conn.commit()
            return seq

    def get_run_events(self, run_id: str, since_seq: int = 0) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT id, seq, event_type, payload_json, created_at
                FROM run_events
                WHERE run_id = ? AND seq > ?
                ORDER BY seq ASC;
                """,
                (run_id, since_seq),
            ).fetchall()
            return [
                {
                    "id": r["id"],
                    "seq": r["seq"],
                    "event": r["event_type"],
                    "payload": json.loads(r["payload_json"]),
                    "created_at": r["created_at"],
                }
                for r in rows
            ]

    def get_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            row = conn.execute("SELECT * FROM runs WHERE id = ?;", (run_id,)).fetchone()
            if not row:
                return None
            res = dict(row)
            res["models"] = json.loads(res.get("models_json") or "{}")
            res["budget"] = json.loads(res.get("budget_json") or "{}")
            res["usage"] = json.loads(res.get("usage_json") or "{}")

            tool_rows = conn.execute(
                "SELECT * FROM tool_calls WHERE run_id = ? ORDER BY created_at ASC;", (run_id,)
            ).fetchall()
            res["tool_calls"] = [dict(t) for t in tool_rows]
            return res

    def update_run_status(
        self,
        run_id: str,
        status: str,
        stop_reason: Optional[str] = None,
        usage: Optional[Dict[str, Any]] = None,
    ):
        now = _utc_now_iso()
        with self._get_connection() as conn:
            conn.execute(
                """
                UPDATE runs
                SET status = ?, stop_reason = ?, usage_json = ?, updated_at = ?
                WHERE id = ?;
                """,
                (status, stop_reason, json.dumps(usage or {}), now, run_id),
            )
            conn.commit()

    # =========================================================================
    # 4. Glossary (Schema Memory Flywheel)
    # =========================================================================

    def record_glossary_entry(
        self,
        connection_id: str,
        target_kind: str,
        target: str,
        kind: str,
        body: str,
        status: str = "suggested",
        author_kind: str = "agent",
        author_ref: Optional[str] = None,
        evidence: Optional[Dict[str, Any]] = None,
    ) -> str:
        gid = f"gl_{uuid.uuid4().hex[:10]}"
        now = _utc_now_iso()
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO glossary_entries (
                    id, connection_id, target_kind, target, kind, body,
                    status, author_kind, author_ref, evidence_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    gid,
                    connection_id,
                    target_kind,
                    target,
                    kind,
                    body,
                    status,
                    author_kind,
                    author_ref,
                    json.dumps(evidence or {}),
                    now,
                    now,
                ),
            )
            conn.commit()
        return gid

    def get_confirmed_glossary(self, connection_id: str) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM glossary_entries
                WHERE connection_id = ? AND status = 'confirmed'
                ORDER BY target ASC;
                """,
                (connection_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    # =========================================================================
    # 5. Cryptographic Append-Only Audit Log
    # =========================================================================

    def record_audit(
        self,
        action: str,
        detail: Dict[str, Any],
        actor: str = "user",
        connection_id: Optional[str] = None,
        run_id: Optional[str] = None,
        workspace_id: str = "default",
    ) -> int:
        now = _utc_now_iso()
        detail_str = json.dumps(detail, sort_keys=True)

        with self._get_connection() as conn:
            # Fetch previous entry's hash
            prev_row = conn.execute("SELECT hash FROM audit_entries ORDER BY seq DESC LIMIT 1;").fetchone()
            prev_hash = prev_row[0] if prev_row else "GENESIS_0000000000000000000000000000000000000000000000000000000000000000"

            # Compute SHA-256 hash: prev_hash + actor + action + detail_str + now
            payload = f"{prev_hash}|{workspace_id}|{actor}|{action}|{detail_str}|{now}"
            curr_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()

            cur = conn.execute(
                """
                INSERT INTO audit_entries (
                    prev_hash, hash, workspace_id, connection_id, run_id, actor, action, detail_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (prev_hash, curr_hash, workspace_id, connection_id, run_id, actor, action, detail_str, now),
            )
            conn.commit()
            return cur.lastrowid

    def verify_audit_chain(self) -> Tuple[bool, str]:
        """Validates cryptographic integrity of entire audit log chain."""
        with self._get_connection() as conn:
            rows = conn.execute("SELECT * FROM audit_entries ORDER BY seq ASC;").fetchall()
            if not rows:
                return True, "Audit log is empty."

            prev_hash = "GENESIS_0000000000000000000000000000000000000000000000000000000000000000"
            for r in rows:
                if r["prev_hash"] != prev_hash:
                    return False, f"Broken chain at seq {r['seq']}: expected prev {prev_hash}, got {r['prev_hash']}"
                payload = f"{prev_hash}|{r['workspace_id']}|{r['actor']}|{r['action']}|{r['detail_json']}|{r['created_at']}"
                expected_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
                if r["hash"] != expected_hash:
                    return False, f"Tampered entry at seq {r['seq']}: expected {expected_hash}, got {r['hash']}"
                prev_hash = r["hash"]

            return True, f"Verified {len(rows)} audit entries. Zero tampering detected."
