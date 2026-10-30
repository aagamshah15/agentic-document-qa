"""
Unit & Integration Test Suite for Phase 1: Multi-Engine Connect & ERD Cartography.
Tests CredentialVault, StudioConnector (DSN assembly, engine configuration, privilege grading),
MetadataCatalog (introspection, snapshot hashing, diffing, ERD graph generation),
and FastAPI v2 endpoints.
"""

import unittest
import os
import tempfile
import sqlite3
from fastapi.testclient import TestClient

from main import app
from services.app_db import StudioAppDB
from services.connector import CredentialVault, StudioConnector
from services.catalog import MetadataCatalog


class TestPhase1ConnectAndMap(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.app_db_path = os.path.join(self.temp_dir.name, "test_studio_p1.db")
        self.app_db = StudioAppDB(db_path=self.app_db_path)
        self.catalog = MetadataCatalog(app_db=self.app_db)

        # Create a sample SQLite database to connect to
        self.sample_db_path = os.path.join(self.temp_dir.name, "sample_store.db")
        conn = sqlite3.connect(self.sample_db_path)
        conn.executescript("""
            CREATE TABLE customers (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT UNIQUE
            );
            CREATE TABLE orders (
                id INTEGER PRIMARY KEY,
                customer_id INTEGER,
                total REAL NOT NULL,
                status TEXT DEFAULT 'pending',
                FOREIGN KEY (customer_id) REFERENCES customers(id)
            );
            CREATE INDEX idx_orders_customer ON orders(customer_id);
        """)
        conn.commit()
        conn.close()

        self.client = TestClient(app)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_credential_vault_isolation(self):
        ref = "sec_test_secret_123"
        val = "super_secret_pg_pass_$$"
        CredentialVault.store_secret(ref, val)

        retrieved = CredentialVault.get_secret(ref)
        self.assertEqual(retrieved, val)

        # DSN assembly replaces ref securely
        template = "postgresql://dbuser@localhost:5432/my_db"
        assembled = StudioConnector.assemble_dsn(template, secret_ref=ref)
        self.assertIn("dbuser:super_secret_pg_pass_%24%24@localhost:5432/my_db", assembled)

        CredentialVault.delete_secret(ref)
        self.assertIsNone(CredentialVault.get_secret(ref))

    def test_sqlite_engine_pragmas_and_privilege_grade(self):
        from sqlalchemy import text
        engine = StudioConnector.create_managed_engine("sqlite", self.sample_db_path, read_only=True)
        with engine.connect() as conn:
            fk_on = conn.execute(text("PRAGMA foreign_keys;")).scalar()
            self.assertEqual(fk_on, 1)
        grade, desc = StudioConnector.evaluate_privilege_grade(engine, "sqlite")
        self.assertIn(grade, ("A", "B", "C"))

    def test_metadata_catalog_introspection(self):
        engine = StudioConnector.create_managed_engine("sqlite", self.sample_db_path, read_only=True)
        structure = self.catalog.introspect_schema(engine)

        self.assertEqual(structure["table_count"], 2)
        table_names = [t["name"] for t in structure["tables"]]
        self.assertIn("customers", table_names)
        self.assertIn("orders", table_names)

        # Verify foreign keys
        orders_tbl = next(t for t in structure["tables"] if t["name"] == "orders")
        self.assertEqual(len(orders_tbl["foreign_keys"]), 1)
        fk = orders_tbl["foreign_keys"][0]
        self.assertEqual(fk["constrained_columns"], ["customer_id"])
        self.assertEqual(fk["referred_table"], "customers")
        self.assertEqual(fk["referred_columns"], ["id"])

        # Snapshot recording
        cid = self.app_db.create_connection("Sample Store", "sqlite", self.sample_db_path)
        snap_id = self.catalog.capture_and_record_snapshot(cid, engine)
        self.assertTrue(snap_id.startswith("snap_"))

    def test_snapshot_diffing(self):
        snap_a = {
            "tables": [
                {
                    "name": "users",
                    "columns": [
                        {"name": "id", "type": "INTEGER", "nullable": False, "primary_key": True},
                        {"name": "email", "type": "VARCHAR(255)", "nullable": False, "primary_key": False},
                    ],
                },
                {
                    "name": "old_logs",
                    "columns": [{"name": "entry", "type": "TEXT", "nullable": True, "primary_key": False}],
                },
            ]
        }

        snap_b = {
            "tables": [
                {
                    "name": "users",
                    "columns": [
                        {"name": "id", "type": "INTEGER", "nullable": False, "primary_key": True},
                        {"name": "email", "type": "TEXT", "nullable": True, "primary_key": False}, # Changed type and nullability
                        {"name": "role", "type": "VARCHAR(50)", "nullable": False, "primary_key": False}, # Added col
                    ],
                },
                {
                    "name": "audit_events", # New table
                    "columns": [{"name": "id", "type": "INTEGER", "nullable": False, "primary_key": True}],
                },
                # old_logs dropped
            ]
        }

        diff = MetadataCatalog.compute_snapshot_diff(snap_a, snap_b)
        self.assertTrue(diff["has_changes"])
        self.assertEqual(diff["added_tables"], ["audit_events"])
        self.assertEqual(diff["dropped_tables"], ["old_logs"])
        self.assertIn("users", diff["modified_tables"])
        self.assertEqual(diff["modified_tables"]["users"]["added_columns"], ["role"])
        self.assertEqual(len(diff["modified_tables"]["users"]["altered_columns"]), 1)
        altered = diff["modified_tables"]["users"]["altered_columns"][0]
        self.assertEqual(altered["name"], "email")
        self.assertEqual(altered["old_type"], "VARCHAR(255)")
        self.assertEqual(altered["new_type"], "TEXT")

    def test_erd_graph_generation(self):
        engine = StudioConnector.create_managed_engine("sqlite", self.sample_db_path, read_only=True)
        structure = self.catalog.introspect_schema(engine)

        inferred = [
            {
                "child_table": "orders",
                "child_column": "status",
                "parent_table": "lookup_status",
                "parent_column": "code",
                "score": 0.95,
            }
        ]

        graph = MetadataCatalog.generate_erd_graph(structure, inferred_relationships=inferred)
        self.assertEqual(graph["node_count"], 2)
        # Should have 1 declared edge + 1 inferred edge = 2 edges
        self.assertEqual(graph["edge_count"], 2)

        decl_edge = next(e for e in graph["edges"] if e["kind"] == "declared")
        self.assertEqual(decl_edge["source"], "customers")
        self.assertEqual(decl_edge["target"], "orders")
        self.assertEqual(decl_edge["source_column"], "id")
        self.assertEqual(decl_edge["target_column"], "customer_id")

        inf_edge = next(e for e in graph["edges"] if e["kind"] == "inferred")
        self.assertEqual(inf_edge["kind"], "inferred")
        self.assertTrue(inf_edge["animated"])
        self.assertIn("Inferred (95%)", inf_edge["label"])

    def test_v2_api_endpoints_flow(self):
        # 1. Register connection
        payload = {
            "name": "Live Store API Test",
            "engine": "sqlite",
            "dsn_template": self.sample_db_path,
            "tier": "sandbox",
        }
        res = self.client.post("/api/v2/connections", json=payload)
        self.assertEqual(res.status_code, 200)
        conn_id = res.json()["connection_id"]
        self.assertTrue(conn_id.startswith("conn_"))

        # 2. List connections
        list_res = self.client.get("/api/v2/connections")
        self.assertEqual(list_res.status_code, 200)
        self.assertTrue(any(c["id"] == conn_id for c in list_res.json()["connections"]))

        # 3. Get connection details
        get_res = self.client.get(f"/api/v2/connections/{conn_id}")
        self.assertEqual(get_res.status_code, 200)
        self.assertEqual(get_res.json()["connection"]["name"], "Live Store API Test")

        # 4. Trigger snapshot refresh
        snap_res = self.client.post(f"/api/v2/connections/{conn_id}/snapshots")
        self.assertEqual(snap_res.status_code, 200)
        self.assertTrue(snap_res.json()["snapshot_id"].startswith("snap_"))

        # 5. Fetch latest snapshot
        latest_res = self.client.get(f"/api/v2/connections/{conn_id}/snapshots/latest")
        self.assertEqual(latest_res.status_code, 200)
        self.assertEqual(latest_res.json()["snapshot"]["table_count"], 2)

        # 6. Diff against live database (should have zero changes)
        diff_res = self.client.get(f"/api/v2/connections/{conn_id}/diff")
        self.assertEqual(diff_res.status_code, 200)
        self.assertFalse(diff_res.json()["diff"]["has_changes"])

        # 7. ERD graph
        graph_res = self.client.get(f"/api/v2/connections/{conn_id}/graph")
        self.assertEqual(graph_res.status_code, 200)
        self.assertEqual(graph_res.json()["graph"]["node_count"], 2)
        self.assertEqual(graph_res.json()["graph"]["edge_count"], 1)


if __name__ == "__main__":
    unittest.main()
