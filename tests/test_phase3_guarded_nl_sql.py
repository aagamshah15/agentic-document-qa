"""
Unit & Integration Test Suite for Phase 3: Guarded NL->SQL & Cost Guard.
Tests CostGuard EXPLAIN plan analysis and threshold warnings,
compact schema context assembly with glossary enrichment,
and the two-phase SQL check -> query token -> run execution API pipeline.
"""

import unittest
import os
import tempfile
import sqlite3
from fastapi.testclient import TestClient

from main import app
from services.app_db import StudioAppDB
from services.connector import StudioConnector
from services.catalog import MetadataCatalog
from services.cost_guard import CostGuard
from services.nl_sql import assemble_compact_schema_context


class TestPhase3GuardedNLSQL(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.app_db_path = os.path.join(self.temp_dir.name, "test_studio_p3.db")
        self.app_db = StudioAppDB(db_path=self.app_db_path)
        self.catalog = MetadataCatalog(app_db=self.app_db)
        self.cost_guard = CostGuard()

        # Create a test database
        self.db_path = os.path.join(self.temp_dir.name, "ecommerce_test.db")
        conn = sqlite3.connect(self.db_path)
        conn.executescript("""
            CREATE TABLE customers (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT
            );

            CREATE TABLE orders (
                id INTEGER PRIMARY KEY,
                customer_id INTEGER,
                amount REAL,
                status INTEGER,
                FOREIGN KEY (customer_id) REFERENCES customers(id)
            );
        """)
        for i in range(1, 21):
            conn.execute("INSERT INTO customers VALUES (?, ?, ?);", (i, f"Cust {i}", f"cust{i}@example.com"))
            conn.execute("INSERT INTO orders VALUES (?, ?, ?, ?);", (i, i, i * 15.5, 1 if i % 2 == 0 else 2))
        conn.commit()
        conn.close()

        self.engine = StudioConnector.create_managed_engine("sqlite", self.db_path, read_only=True)
        self.client = TestClient(app)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_cost_guard_explain_plan_and_warnings(self):
        # Query with sequential scan on orders
        sql = "SELECT customer_id, SUM(amount) FROM orders GROUP BY customer_id;"
        plan_eval = self.cost_guard.evaluate_plan_and_cost(
            self.engine, sql, engine_type="sqlite", tier="dev"
        )
        self.assertIn("plan_tree", plan_eval)
        self.assertTrue(len(plan_eval["plan_tree"]) > 0)
        self.assertTrue(plan_eval["has_seq_scan"])
        # Should have a warning about full sequential scan in dev tier
        self.assertTrue(any("sequential table scan" in w for w in plan_eval["warnings"]))

    def test_compact_schema_context_assembly(self):
        structure = self.catalog.introspect_schema(self.engine)
        glossary = {
            "orders.status": "1: Active, 2: Shipped",
            "customers": "Customer account directory",
        }
        compact = assemble_compact_schema_context(structure, confirmed_glossary=glossary)

        self.assertIn("customers(", compact)
        self.assertIn("orders(", compact)
        self.assertIn("id integer PK", compact)
        self.assertIn("-> customers.id", compact)
        self.assertIn("{1: Active, 2: Shipped}", compact)

    def test_two_phase_sql_check_and_run_api_flow(self):
        # 1. Register connection
        reg = self.client.post("/api/v2/connections", json={
            "name": "Phase 3 DB",
            "engine": "sqlite",
            "dsn_template": self.db_path,
            "tier": "dev",
        })
        self.assertEqual(reg.status_code, 200)
        conn_id = reg.json()["connection_id"]

        # 2. Check safe query
        check_res = self.client.post(f"/api/v2/connections/{conn_id}/sql/check", json={
            "sql": "SELECT id, name, email FROM customers WHERE id <= 10"
        })
        self.assertEqual(check_res.status_code, 200)
        check_data = check_res.json()
        self.assertEqual(check_data["status"], "success")
        self.assertIn("LIMIT 500", check_data["sanitized_sql"].upper())
        token = check_data["query_token"]
        self.assertTrue(token.startswith("qtok_"))

        # 3. Run query with token
        run_res = self.client.post(f"/api/v2/connections/{conn_id}/sql/run", json={
            "query_token": token,
            "page": 1,
            "page_size": 5,
        })
        self.assertEqual(run_res.status_code, 200)
        run_data = run_res.json()
        self.assertEqual(run_data["status"], "success")
        self.assertEqual(run_data["columns"], ["id", "name", "email"])
        self.assertEqual(len(run_data["rows"]), 5)
        self.assertEqual(run_data["total_row_count"], 10)

        # 4. Attempt to run with tampered token
        tampered_token = token[:-6] + "tamper"
        bad_run = self.client.post(f"/api/v2/connections/{conn_id}/sql/run", json={
            "query_token": tampered_token
        })
        self.assertEqual(bad_run.status_code, 403)

        # 5. Check mutating query rejection
        bad_check = self.client.post(f"/api/v2/connections/{conn_id}/sql/check", json={
            "sql": "DELETE FROM customers WHERE id = 1"
        })
        self.assertEqual(bad_check.status_code, 400)


if __name__ == "__main__":
    unittest.main()
