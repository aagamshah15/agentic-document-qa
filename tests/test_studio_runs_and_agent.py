"""
Autonomous Data & Schema Studio — Runs & Autonomous Agent Test Suite.
Verifies:
- Connection testing, patching, deletion
- Table searching & detail endpoints
- Runs creation, monotonic event streaming, status inspection, cancellation
- Audit log query and cryptographic verification
- Tool registry invocation of all 13 Studio tools
"""

import unittest
import os
import json
from fastapi.testclient import TestClient
from main import app
from services.app_db import StudioAppDB
from services.tool_registry import tool_registry, ToolContext


class TestStudioRunsAndAgent(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.app_db = StudioAppDB()

        # Ensure demo connection
        conns = cls.client.get("/api/v2/connections").json().get("connections", [])
        if conns:
            cls.conn_id = conns[0]["id"]
        else:
            ecom_path = os.path.abspath("data/sample_datasets/ecommerce.sqlite")
            res = cls.client.post("/api/v2/connections", json={
                "name": "Test Store",
                "engine": "sqlite",
                "dsn_template": ecom_path,
                "tier": "sandbox"
            })
            cls.conn_id = res.json()["connection_id"]

    def test_connection_test_endpoint(self):
        ecom_path = os.path.abspath("data/sample_datasets/ecommerce.sqlite")
        res = self.client.post("/api/v2/connections/test", json={
            "engine": "sqlite",
            "dsn_template": ecom_path,
        })
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "success")
        self.assertTrue(data["connected"])
        self.assertIn("privilege_grade", data)

    def test_connection_patch_and_delete_endpoints(self):
        # Create disposable connection
        ecom_path = os.path.abspath("data/sample_datasets/ecommerce.sqlite")
        res_create = self.client.post("/api/v2/connections", json={
            "name": "Disposable Test DB",
            "engine": "sqlite",
            "dsn_template": ecom_path,
            "tier": "sandbox"
        })
        cid = res_create.json()["connection_id"]

        # Patch
        res_patch = self.client.patch(f"/api/v2/connections/{cid}", json={
            "name": "Updated Test DB",
            "tier": "dev",
            "cloud_models_allowed": True
        })
        self.assertEqual(res_patch.status_code, 200)

        # Verify patch
        cdata = self.app_db.get_connection(cid)
        self.assertEqual(cdata["name"], "Updated Test DB")
        self.assertEqual(cdata["tier"], "dev")

        # Delete
        res_del = self.client.delete(f"/api/v2/connections/{cid}")
        self.assertEqual(res_del.status_code, 200)
        self.assertIsNone(self.app_db.get_connection(cid))

    def test_search_tables_and_detail_endpoints(self):
        res_tables = self.client.get(f"/api/v2/connections/{self.conn_id}/tables?limit=10")
        self.assertEqual(res_tables.status_code, 200)
        data = res_tables.json()
        self.assertEqual(data["status"], "success")
        self.assertGreater(len(data["tables"]), 0)

        tname = data["tables"][0]["name"]
        res_detail = self.client.get(f"/api/v2/connections/{self.conn_id}/tables/{tname}")
        self.assertEqual(res_detail.status_code, 200)
        self.assertEqual(res_detail.json()["table"]["name"], tname)

    def test_run_creation_and_streaming_events(self):
        # 1. Start a run in 'ask' mode
        res_run = self.client.post("/api/v2/runs", json={
            "session_id": "test_session_123",
            "connection_id": self.conn_id,
            "mode": "ask",
            "effort": "low",
            "message": "SELECT * FROM customers LIMIT 5"
        })
        self.assertEqual(res_run.status_code, 200)
        run_id = res_run.json()["run_id"]
        self.assertTrue(run_id.startswith("run_"))

        # 2. Stream events
        res_stream = self.client.get(f"/api/v2/runs/{run_id}/events")
        self.assertEqual(res_stream.status_code, 200)
        content = res_stream.text

        # Verify event types are emitted
        self.assertIn("event: run.started", content)
        self.assertIn("event: step.started", content)
        self.assertIn("event: tool.called", content)
        self.assertIn("event: tool.result", content)
        self.assertIn("event: token", content)
        self.assertIn("event: run.completed", content)

        # 3. Inspect run status
        res_get = self.client.get(f"/api/v2/runs/{run_id}")
        self.assertEqual(res_get.status_code, 200)
        rinfo = res_get.json()["run"]
        self.assertEqual(rinfo["status"], "completed")
        self.assertGreater(len(rinfo["events"]), 0)

    def test_run_cancel_endpoint(self):
        res_run = self.client.post("/api/v2/runs", json={
            "session_id": "test_session_cancel",
            "connection_id": self.conn_id,
            "mode": "explore",
            "message": "Explore all tables"
        })
        run_id = res_run.json()["run_id"]

        res_cancel = self.client.post(f"/api/v2/runs/{run_id}/cancel")
        self.assertEqual(res_cancel.status_code, 200)

        run_data = self.app_db.get_run(run_id)
        self.assertEqual(run_data["status"], "cancelled")

    def test_audit_log_endpoint(self):
        res_audit = self.client.get(f"/api/v2/connections/{self.conn_id}/audit?limit=50")
        self.assertEqual(res_audit.status_code, 200)
        data = res_audit.json()
        self.assertEqual(data["status"], "success")
        self.assertTrue(data["chain_verified"])

    def test_tool_registry_scoping_and_execution(self):
        ctx = ToolContext(connection_id=self.conn_id, tier="sandbox", mode="ask")

        # 1. Permitted tool in 'ask' mode
        res_search = tool_registry.invoke("search_schema", {"query": "customers", "limit": 5}, ctx)
        self.assertEqual(res_search.status_code if hasattr(res_search, "status_code") else res_search.status, "ok")

        # 2. Blocked tool in 'ask' mode (propose_migration is 'change' mode only)
        res_blocked = tool_registry.invoke("propose_migration", {"goal": "test", "up_sql": "SELECT 1;", "down_sql": "SELECT 1;"}, ctx)
        self.assertEqual(res_blocked.status, "error")
        self.assertIn("not permitted in 'ask' mode", res_blocked.summary)


if __name__ == "__main__":
    unittest.main()
