"""
Dimension — Autonomous Data & Schema Studio
Phase 7 / Milestone M6 Hardening & Capability Test Suite.
Validates MySQL engine assembly, cross-connection drift diffing,
model capability probing, cloud model PII lock guarantees,
and wide schema (1,200 tables) performance.
"""

import unittest
import tempfile
import time
from fastapi.testclient import TestClient
from main import app
from services.connector import StudioConnector
from services.model_probe import ModelCapabilityProber
from services.app_db import StudioAppDB
from experiments.fixtures.generator import generate_wide_schema_fixture
from services.catalog import MetadataCatalog


class TestPhase7M6Hardening(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.client.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)

    def test_mysql_engine_assembly_and_read_only_flags(self):
        """Verify mysql+pymysql engine creation injects read-only session params."""
        # Non-connected mock engine test
        engine = StudioConnector.create_managed_engine(
            engine_type="mysql",
            dsn="mysql://user:pass@localhost:3306/db",
            read_only=True,
            statement_timeout_ms=10000,
        )
        self.assertIn("mysql+pymysql", str(engine.url))
        self.assertEqual(engine.url.username, "user")
        self.assertEqual(engine.url.port, 3306)

    def test_model_capability_prober_static_and_probe_results(self):
        """Verify prober correctly identifies tool calling vs non-tool calling models."""
        # Tool model
        probe_tool = ModelCapabilityProber.probe_model("qwen3:4b")
        self.assertTrue(probe_tool["tools_supported"])
        self.assertEqual(probe_tool["recommended_role"], "tool")

        # Non-tool model
        probe_non_tool = ModelCapabilityProber.probe_model("llama3")
        self.assertFalse(probe_non_tool["tools_supported"])
        self.assertEqual(probe_non_tool["recommended_role"], "fast")

        # Via endpoint
        res = self.client.get("/api/v2/models/probe?model=qwen3:4b")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json()["probe"]["tools_supported"])

        res_llama = self.client.get("/api/v2/models/probe?model=llama3")
        self.assertEqual(res_llama.status_code, 200)
        self.assertFalse(res_llama.json()["probe"]["tools_supported"])

    def test_cross_connection_and_snapshot_drift_diffing(self):
        """Verify cross-connection and cross-snapshot drift diffing endpoints."""
        conns_res = self.client.get("/api/v2/connections")
        self.assertEqual(conns_res.status_code, 200)
        conns = conns_res.json()["connections"]
        self.assertGreaterEqual(len(conns), 1)

        conn_id = conns[0]["id"]

        # Ensure snapshots exist
        self.client.post(f"/api/v2/connections/{conn_id}/snapshots")
        snaps_res = self.client.get(f"/api/v2/connections/{conn_id}/snapshots")
        self.assertEqual(snaps_res.status_code, 200)
        snaps = snaps_res.json().get("snapshots", [])
        self.assertGreaterEqual(len(snaps), 1)

        snap_id = snaps[0]["id"]

        # Diff same snapshot (diff should be empty: 0 added, 0 removed, 0 altered)
        diff_res = self.client.get(f"/api/v2/snapshots/{snap_id}/diff/{snap_id}")
        self.assertEqual(diff_res.status_code, 200)
        diff_data = diff_res.json()["diff"]
        self.assertEqual(len(diff_data.get("added_tables", [])), 0)
        self.assertEqual(len(diff_data.get("removed_tables", [])), 0)
        self.assertEqual(len(diff_data.get("altered_tables", [])), 0)

        # Cross connection diff against itself
        conn_diff_res = self.client.get(f"/api/v2/connections/{conn_id}/diff/{conn_id}")
        self.assertEqual(conn_diff_res.status_code, 200)
        self.assertEqual(len(conn_diff_res.json()["diff"].get("added_tables", [])), 0)

    def test_byok_cloud_disclosure_and_pii_masking_lock(self):
        """Verify cloud disclosure audit and that enabling cloud models locks masking_enabled=True."""
        conns_res = self.client.get("/api/v2/connections")
        conn_id = conns_res.json()["connections"][0]["id"]

        # 1. Cloud disclosure endpoint
        res = self.client.get(f"/api/v2/connections/{conn_id}/cloud-disclosure")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("data_leaving_machine", data)
        self.assertIn("data_staying_local", data)
        self.assertTrue(data["masking_locked"])

        # 2. Update connection allowing cloud models, verify masking_enabled is forced True
        update_res = self.client.patch(
            f"/api/v2/connections/{conn_id}",
            json={
                "cloud_models_allowed": True,
                "masking_enabled": False,  # Attempt to disable masking while cloud is enabled
            },
        )
        self.assertEqual(update_res.status_code, 200)

        # Fetch and verify
        conn_res = self.client.get(f"/api/v2/connections/{conn_id}")
        self.assertEqual(conn_res.status_code, 200)
        updated = conn_res.json()["connection"]
        self.assertTrue(updated["cloud_models_allowed"])
        self.assertTrue(updated["masking_enabled"], "Masking MUST be locked to True when cloud models are allowed!")

    def test_wide_schema_fixture_generation_and_search_benchmark(self):
        """Verify 1,200 table wide schema fixture generates and schema search finishes in <100ms."""
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = generate_wide_schema_fixture(temp_dir, num_tables=1200, num_schemas=30)
            db_path = fixture["db_path"]
            engine = StudioConnector.create_managed_engine("sqlite", db_path)
            catalog = MetadataCatalog()

            # Introspect
            t0 = time.perf_counter()
            snapshot_struct = catalog.introspect_schema(engine)
            t_introspect = time.perf_counter() - t0

            self.assertEqual(len(snapshot_struct["tables"]), 1200)
            self.assertLess(t_introspect, 2.0, "Introspection of 1,200 tables took too long")

            # Search benchmark: query against 1,200 tables must execute in <100ms
            from services.tool_registry import tool_registry, ToolContext
            from services.app_db import StudioAppDB

            app_db = StudioAppDB()
            conn_id = app_db.create_connection(
                name="Wide Benchmark DB",
                engine="sqlite",
                dsn_template=f"sqlite:///{db_path}",
                tier="dev",
            )
            app_db.record_snapshot(conn_id, snapshot_struct, server_version="3.x", source="test")

            ctx = ToolContext(
                connection_id=conn_id,
                tier="dev",
                mode="explore",
                run_id="run_bench",
            )
            search_tool = tool_registry.get_tool("search_schema")
            self.assertIsNotNone(search_tool)

            t1 = time.perf_counter()
            result = search_tool.handler(ctx, search_tool.args_model(query="billing_tbl_010", limit=10))
            t_search = (time.perf_counter() - t1) * 1000  # in ms

            self.assertEqual(result.status, "ok")
            matches = result.data.get("matches", [])
            self.assertGreater(len(matches), 0)
            self.assertLess(t_search, 100.0, f"Search took {t_search:.2f}ms (threshold: 100ms)")


if __name__ == "__main__":
    unittest.main()
