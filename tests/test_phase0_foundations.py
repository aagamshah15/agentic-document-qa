"""
Unit Test Suite for Phase 0: Foundations & Safety Choke Point.
Tests SQLGuard (AST parsing, CTE attacks, limits, tokens),
StudioAppDB (migrations, snapshots, events, hash-chained audit),
and ToolRegistry (mode/tier scoping, budget limits, sanitized errors).
"""

import unittest
import os
import tempfile
import time
from pydantic import BaseModel, Field

from core.config import settings
from services.app_db import StudioAppDB
from services.sql_guard import SQLGuard, SQLGuardException, sql_guard
from services.tool_registry import (
    ToolRegistry,
    ToolSpec,
    ToolContext,
    ToolResult,
)


class TestConfigSafety(unittest.TestCase):
    def test_langchain_tracing_defaults_to_false(self):
        """Ensures telemetry tracing is disabled by default to prevent customer data leakage."""
        self.assertEqual(settings.LANGCHAIN_TRACING_V2.lower(), "false")


class TestStudioAppDB(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_studio.db")
        self.app_db = StudioAppDB(db_path=self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_migrations_applied(self):
        with self.app_db._get_connection() as conn:
            rows = conn.execute("SELECT version, name FROM schema_versions ORDER BY version ASC;").fetchall()
            self.assertTrue(len(rows) >= 1)
            self.assertEqual(rows[0]["version"], 1)

    def test_connections_lifecycle(self):
        conn_id = self.app_db.create_connection(
            name="Prod Analytics",
            engine="postgresql",
            dsn_template="postgresql://reader@db.internal:5432/analytics",
            tier="prod",
            privilege_grade="A",
            cloud_models_allowed=False,
            masking_enabled=True,
        )
        self.assertTrue(conn_id.startswith("conn_"))

        data = self.app_db.get_connection(conn_id)
        self.assertIsNotNone(data)
        self.assertEqual(data["name"], "Prod Analytics")
        self.assertEqual(data["tier"], "prod")
        self.assertEqual(data["privilege_grade"], "A")
        self.assertFalse(data["cloud_models_allowed"])
        self.assertTrue(data["masking_enabled"])

        connections = self.app_db.list_connections()
        self.assertEqual(len(connections), 1)

    def test_schema_snapshots_hashing(self):
        cid = self.app_db.create_connection(name="Test DB", engine="sqlite", dsn_template="sqlite:///:memory:")
        structure = {
            "tables": [
                {"name": "users", "columns": [{"name": "id", "type": "INTEGER"}]},
                {"name": "orders", "columns": [{"name": "id", "type": "INTEGER"}]},
            ]
        }
        snap_id = self.app_db.record_snapshot(cid, structure=structure, server_version="SQLite 3.39")
        self.assertTrue(snap_id.startswith("snap_"))

        latest = self.app_db.get_latest_snapshot(cid)
        self.assertIsNotNone(latest)
        self.assertEqual(latest["table_count"], 2)
        self.assertEqual(latest["column_count"], 2)
        self.assertTrue(len(latest["content_hash"]) == 64)

    def test_runs_and_monotonic_event_sequencing(self):
        run_id = self.app_db.create_run(
            session_id="sess_123",
            connection_id=None,
            mode="explore",
            effort="medium",
        )
        self.assertTrue(run_id.startswith("run_"))

        seq1 = self.app_db.append_run_event(run_id, "run.started", {"mode": "explore"})
        seq2 = self.app_db.append_run_event(run_id, "step.started", {"step": 1})
        seq3 = self.app_db.append_run_event(run_id, "tool.called", {"tool": "search_schema"})

        self.assertEqual(seq1, 1)
        self.assertEqual(seq2, 2)
        self.assertEqual(seq3, 3)

        events_from_start = self.app_db.get_run_events(run_id, since_seq=0)
        self.assertEqual(len(events_from_start), 3)

        events_since_2 = self.app_db.get_run_events(run_id, since_seq=2)
        self.assertEqual(len(events_since_2), 1)
        self.assertEqual(events_since_2[0]["event"], "tool.called")

    def test_glossary_flywheel(self):
        cid = self.app_db.create_connection(name="Shop", engine="sqlite", dsn_template="sqlite:///:memory:")
        gid = self.app_db.record_glossary_entry(
            connection_id=cid,
            target_kind="column",
            target="orders.status",
            kind="enum_map",
            body="1:new, 2:paid, 4:refunded",
            status="confirmed",
        )
        self.assertTrue(gid.startswith("gl_"))

        confirmed = self.app_db.get_confirmed_glossary(cid)
        self.assertEqual(len(confirmed), 1)
        self.assertEqual(confirmed[0]["target"], "orders.status")
        self.assertEqual(confirmed[0]["body"], "1:new, 2:paid, 4:refunded")

    def test_cryptographic_audit_log_and_tamper_detection(self):
        self.app_db.record_audit(action="connect", detail={"db": "test"}, actor="user")
        self.app_db.record_audit(action="query", detail={"sql": "SELECT 1"}, actor="agent")
        self.app_db.record_audit(action="export", detail={"format": "csv"}, actor="user")

        is_valid, msg = self.app_db.verify_audit_chain()
        self.assertTrue(is_valid, msg)

        # Tamper with the database directly
        with self.app_db._get_connection() as conn:
            conn.execute("UPDATE audit_entries SET action = 'tampered_action' WHERE seq = 2;")
            conn.commit()

        is_valid_after_tamper, tamper_msg = self.app_db.verify_audit_chain()
        self.assertFalse(is_valid_after_tamper)
        self.assertIn("Tampered entry at seq 2", tamper_msg)


class TestSQLGuard(unittest.TestCase):
    def setUp(self):
        self.guard = SQLGuard(default_limit=250, max_limit=1000)

    def test_classify_and_allow_clean_read(self):
        sql = "SELECT id, name, total FROM orders WHERE total > 100;"
        rewritten, meta = self.guard.enforce_read_only(sql, dialect="postgres")
        self.assertEqual(meta["class"], "READ")
        self.assertTrue(meta["is_read"])
        self.assertEqual(meta["tables"], ["orders"])
        # Should have auto-injected limit 250
        self.assertIn("LIMIT 250", rewritten.upper())
        self.assertEqual(meta["final_limit"], 250)

    def test_block_write_statements(self):
        dangerous_queries = [
            "DELETE FROM customers WHERE id = 1;",
            "UPDATE orders SET status = 'cancelled';",
            "INSERT INTO audit_log VALUES (1, 'bypass');",
            "DROP TABLE users;",
            "ALTER TABLE products DROP COLUMN price;",
            "TRUNCATE TABLE telemetry;",
        ]
        for query in dangerous_queries:
            with self.assertRaises(SQLGuardException) as ctx:
                self.guard.enforce_read_only(query)
            self.assertEqual(ctx.exception.code, "write_blocked")

    def test_block_multi_statement_injection(self):
        attack = "SELECT 1; DROP TABLE accounts;"
        with self.assertRaises(SQLGuardException) as ctx:
            self.guard.enforce_read_only(attack)
        self.assertEqual(ctx.exception.code, "multi_statement_rejected")

    def test_block_cte_masked_write(self):
        cte_attack = "WITH deleted_rows AS (DELETE FROM orders RETURNING *) SELECT * FROM deleted_rows;"
        with self.assertRaises(SQLGuardException) as ctx:
            self.guard.enforce_read_only(cte_attack)
        self.assertEqual(ctx.exception.code, "write_blocked")

    def test_block_select_into_write(self):
        select_into = "SELECT * INTO backup_orders FROM orders;"
        with self.assertRaises(SQLGuardException) as ctx:
            self.guard.enforce_read_only(select_into)
        self.assertEqual(ctx.exception.code, "write_blocked")

    def test_limit_clamping(self):
        # Query with excessive limit should clamp to max_limit (1000)
        sql = "SELECT * FROM large_table LIMIT 50000;"
        rewritten, meta = self.guard.enforce_read_only(sql, dialect="postgres")
        self.assertEqual(meta["final_limit"], 1000)
        self.assertIn("LIMIT 1000", rewritten.upper())

    def test_query_token_issuance_and_verification(self):
        sql = "SELECT id, email FROM customers LIMIT 100;"
        rewritten, meta = self.guard.enforce_read_only(sql)
        token = self.guard.issue_query_token(rewritten, connection_id="conn_abc", tier="dev", meta=meta)

        self.assertTrue(token.startswith("qtok_"))
        payload = self.guard.verify_query_token(token)
        self.assertEqual(payload["sql"], rewritten)
        self.assertEqual(payload["conn_id"], "conn_abc")
        self.assertEqual(payload["tier"], "dev")

        # Tampered token check
        tampered_token = token[:-5] + "bad00"
        with self.assertRaises(SQLGuardException) as ctx:
            self.guard.verify_query_token(tampered_token)
        self.assertEqual(ctx.exception.code, "tampered_token")


class MockArgs(BaseModel):
    query: str = Field(description="Search term")
    limit: int = Field(default=5, ge=1, le=20)

    class Config:
        extra = "forbid"


class TestToolRegistry(unittest.TestCase):
    def setUp(self):
        self.registry = ToolRegistry()

        def dummy_search(ctx: ToolContext, args: MockArgs) -> ToolResult:
            return ToolResult(
                status="ok",
                summary=f"Found 2 tables for '{args.query}'",
                data={"tables": ["orders", "order_items"]},
                evidence=[{"id": "ev_1", "kind": "search", "query": args.query}],
            )

        self.spec = ToolSpec(
            name="search_schema",
            description="Searches tables and columns",
            args_model=MockArgs,
            risk="metadata",
            allowed_tiers={"sandbox", "dev", "prod"},
            modes={"explore", "ask"},
            handler=dummy_search,
        )
        self.registry.register(self.spec)

    def test_list_tools_by_mode(self):
        explore_tools = self.registry.list_tools_for_mode("explore", "sandbox")
        self.assertEqual(len(explore_tools), 1)
        self.assertEqual(explore_tools[0].name, "search_schema")

        # Seed mode shouldn't have search_schema
        seed_tools = self.registry.list_tools_for_mode("seed", "sandbox")
        self.assertEqual(len(seed_tools), 0)

    def test_successful_tool_invocation(self):
        ctx = ToolContext(mode="explore", tier="sandbox")
        res = self.registry.invoke("search_schema", {"query": "customer", "limit": 10}, ctx)
        self.assertEqual(res.status, "ok")
        self.assertIn("Found 2 tables", res.summary)
        self.assertEqual(len(res.evidence), 1)
        self.assertEqual(ctx.tool_calls_count, 1)

    def test_reject_forbidden_mode(self):
        ctx = ToolContext(mode="seed", tier="sandbox")
        res = self.registry.invoke("search_schema", {"query": "customer"}, ctx)
        self.assertEqual(res.status, "error")
        self.assertIn("not permitted in 'seed' mode", res.summary)

    def test_reject_extra_arguments(self):
        ctx = ToolContext(mode="explore", tier="sandbox")
        res = self.registry.invoke("search_schema", {"query": "customer", "illegal_arg": True}, ctx)
        self.assertEqual(res.status, "error")
        self.assertIn("Invalid arguments", res.summary)

    def test_budget_exhaustion(self):
        ctx = ToolContext(mode="explore", tier="sandbox", budgets={"max_tool_calls": 1})
        res1 = self.registry.invoke("search_schema", {"query": "orders"}, ctx)
        self.assertEqual(res1.status, "ok")

        # Second call should fail due to budget
        res2 = self.registry.invoke("search_schema", {"query": "customers"}, ctx)
        self.assertEqual(res2.status, "error")
        self.assertIn("budget exhausted", res2.summary)


if __name__ == "__main__":
    unittest.main()
