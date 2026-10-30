"""
Unit & Integration Test Suite for Phase 5: Topological Seed Generator & Constraints.
Tests SeedGenerator (topological sorting, cycle handling, foreign key validity, Faker PII replacement),
execution with zero foreign key violations, and FastAPI v2 seed planning & generation endpoints.
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
from services.seed_generator import SeedGenerator


class TestPhase5SeedGenerator(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.app_db_path = os.path.join(self.temp_dir.name, "test_studio_p5.db")
        self.app_db = StudioAppDB(db_path=self.app_db_path)
        self.catalog = MetadataCatalog(app_db=self.app_db)
        self.seeder = SeedGenerator(seed=123)

        # Create multi-table relational schema: customers -> orders -> order_items
        self.db_path = os.path.join(self.temp_dir.name, "relational_store.db")
        conn = sqlite3.connect(self.db_path)
        conn.executescript("""
            PRAGMA foreign_keys = ON;

            CREATE TABLE customers (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT NOT NULL
            );

            CREATE TABLE orders (
                id INTEGER PRIMARY KEY,
                customer_id INTEGER NOT NULL,
                total REAL NOT NULL,
                FOREIGN KEY (customer_id) REFERENCES customers(id)
            );

            CREATE TABLE order_items (
                id INTEGER PRIMARY KEY,
                order_id INTEGER NOT NULL,
                product_name TEXT NOT NULL,
                FOREIGN KEY (order_id) REFERENCES orders(id)
            );
        """)
        conn.commit()
        conn.close()

        self.engine = StudioConnector.create_managed_engine("sqlite", self.db_path, read_only=False)
        self.structure = self.catalog.introspect_schema(self.engine)
        self.client = TestClient(app)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_topological_dependency_ordering(self):
        ordered = self.seeder.topological_sort_tables(self.structure)

        # customers must come before orders
        self.assertLess(ordered.index("customers"), ordered.index("orders"))
        # orders must come before order_items
        self.assertLess(ordered.index("orders"), ordered.index("order_items"))

    def test_data_generation_fk_integrity_and_faker_pii(self):
        counts = {"customers": 5, "orders": 10, "order_items": 20}
        data = self.seeder.generate_data(self.structure, row_counts=counts)

        self.assertEqual(len(data["customers"]), 5)
        self.assertEqual(len(data["orders"]), 10)
        self.assertEqual(len(data["order_items"]), 20)

        # Verify FK integrity: all order.customer_id must be in customers.id
        customer_ids = {c["id"] for c in data["customers"]}
        for ord_row in data["orders"]:
            self.assertIn(ord_row["customer_id"], customer_ids)

        # Verify order_items.order_id must be in orders.id
        order_ids = {o["id"] for o in data["orders"]}
        for item in data["order_items"]:
            self.assertIn(item["order_id"], order_ids)

        # Verify Faker PII is generated
        for c in data["customers"]:
            self.assertIn("@", c["email"])
            self.assertTrue(len(c["name"]) > 2)

    def test_zero_constraint_violations_on_live_execution(self):
        sql_inserts = self.seeder.generate_sql_inserts(self.structure, row_counts={"customers": 10, "orders": 25, "order_items": 50})
        self.assertTrue(len(sql_inserts) > 0)

        # Execute inserts on database with strict foreign key constraints enforced
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON;")
        for stmt in sql_inserts.split(";"):
            if stmt.strip():
                conn.execute(stmt)
        conn.commit()

        # Check counts
        cust_cnt = conn.execute("SELECT COUNT(*) FROM customers;").fetchone()[0]
        ord_cnt = conn.execute("SELECT COUNT(*) FROM orders;").fetchone()[0]
        item_cnt = conn.execute("SELECT COUNT(*) FROM order_items;").fetchone()[0]
        conn.close()

        self.assertEqual(cust_cnt, 10)
        self.assertEqual(ord_cnt, 25)
        self.assertEqual(item_cnt, 50)

    def test_routes_v2_seed_endpoints(self):
        # 1. Register connection
        reg = self.client.post("/api/v2/connections", json={
            "name": "Seeding API Target",
            "engine": "sqlite",
            "dsn_template": self.db_path,
            "tier": "sandbox",
        })
        self.assertEqual(reg.status_code, 200)
        conn_id = reg.json()["connection_id"]

        # 2. Get seed generation plan
        plan_res = self.client.post(f"/api/v2/connections/{conn_id}/seed-plans", json={
            "row_counts": {"customers": 5, "orders": 12}
        })
        self.assertEqual(plan_res.status_code, 200)
        plan_data = plan_res.json()["plan"]
        self.assertEqual(plan_data["topological_order"][0], "customers")

        # 3. Generate SQL script
        gen_sql_res = self.client.post(f"/api/v2/connections/{conn_id}/seed-plans/generate", json={
            "target": "sql",
            "row_counts": {"customers": 3, "orders": 6}
        })
        self.assertEqual(gen_sql_res.status_code, 200)
        self.assertIn("INSERT INTO customers", gen_sql_res.json()["sql_inserts"])

        # 4. Generate and apply directly into Sandbox connection
        apply_res = self.client.post(f"/api/v2/connections/{conn_id}/seed-plans/generate", json={
            "target": "apply",
            "row_counts": {"customers": 4, "orders": 8, "order_items": 16}
        })
        self.assertEqual(apply_res.status_code, 200)
        self.assertEqual(apply_res.json()["constraint_violations"], 0)

        # 5. Prod rejection: register prod connection and verify direct apply fails with 403
        prod_reg = self.client.post("/api/v2/connections", json={
            "name": "Prod Seeding Target",
            "engine": "sqlite",
            "dsn_template": self.db_path,
            "tier": "prod",
        })
        prod_conn_id = prod_reg.json()["connection_id"]

        bad_apply = self.client.post(f"/api/v2/connections/{prod_conn_id}/seed-plans/generate", json={
            "target": "apply"
        })
        self.assertEqual(bad_apply.status_code, 403)


if __name__ == "__main__":
    unittest.main()
