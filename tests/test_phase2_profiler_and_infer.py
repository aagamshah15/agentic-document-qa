"""
Unit & Integration Test Suite for Phase 2: Deep Profiler, FK Inference & Glossary Flywheel.
Tests FKInferrer (containment, trap rejection), HygieneDetector (sentinels, mixed dates, orphans, dismiss memory),
GlossaryManager (Markdown & dbt sources.yml export), and FastAPI v2 routes.
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
from services.fk_inferrer import FKInferrer
from services.hygiene_detector import HygieneDetector
from services.glossary import GlossaryManager


class TestPhase2ProfilerAndInfer(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.app_db_path = os.path.join(self.temp_dir.name, "test_studio_p2.db")
        self.app_db = StudioAppDB(db_path=self.app_db_path)
        self.catalog = MetadataCatalog(app_db=self.app_db)
        self.fk_inferrer = FKInferrer(app_db=self.app_db)
        self.hygiene = HygieneDetector(app_db=self.app_db)
        self.glossary = GlossaryManager(app_db=self.app_db)

        # Create realistic test database with planted problems
        self.db_path = os.path.join(self.temp_dir.name, "messy_shop.db")
        conn = sqlite3.connect(self.db_path)
        conn.executescript("""
            CREATE TABLE customers (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT
            );

            CREATE TABLE regions (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL
            );

            CREATE TABLE orders (
                id INTEGER PRIMARY KEY,
                cust_id INTEGER,                   -- Undeclared FK to customers.id
                status_code INTEGER,               -- Planted lookup trap (1..3 matches regions.id 1..3)
                order_date TEXT,                   -- Planted mixed date formats
                phone TEXT,                        -- Planted sentinel values
                notes TEXT,                        -- High null rate
                created_at TEXT DEFAULT (datetime('now'))
            );

            -- Declared FK table to test orphaned record detection and unindexed FK
            CREATE TABLE order_items (
                id INTEGER PRIMARY KEY,
                order_id INTEGER,
                amount REAL,
                FOREIGN KEY (order_id) REFERENCES orders(id)
            );
        """)

        # Seed data
        # 1. customers (ids 1..5)
        for i in range(1, 6):
            conn.execute("INSERT INTO customers VALUES (?, ?, ?);", (i, f"Customer {i}", f"cust{i}@example.com"))

        # 2. regions (ids 1..3)
        for i in range(1, 4):
            conn.execute("INSERT INTO regions VALUES (?, ?);", (i, f"Region {i}"))

        # 3. orders (cust_id strictly in 1..5 -> 100% containment to customers.id)
        # mixed dates: YYYY-MM-DD and MM/DD/YYYY
        # sentinels: 000-00-0000
        # notes: 9 out of 10 NULL -> 90% null rate
        order_rows = [
            (101, 1, 1, "2024-01-15", "000-00-0000", None),
            (102, 2, 2, "02/14/2024", "555-123-4567", None),
            (103, 3, 1, "2024-03-01", "000-00-0000", None),
            (104, 4, 3, "04/01/2024", "555-987-6543", None),
            (105, 5, 2, "2024-05-10", "000-00-0000", "Special handling"),
            (106, 1, 1, "06/20/2024", "555-000-1111", None),
            (107, 2, 3, "2024-07-04", "000-00-0000", None),
            (108, 3, 2, "08/15/2024", "555-222-3333", None),
            (109, 4, 1, "2024-09-01", "000-00-0000", None),
            (110, 5, 2, "10/31/2024", "555-444-5555", None),
        ]
        conn.executemany("INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?, datetime('now'));", order_rows)

        # 4. order_items: planted orphaned record (order_id 999 doesn't exist in orders)
        conn.execute("INSERT INTO order_items VALUES (1, 101, 49.99);")
        conn.execute("INSERT INTO order_items VALUES (2, 999, 99.99);") # Orphan!

        conn.commit()
        conn.close()

        self.engine = StudioConnector.create_managed_engine("sqlite", self.db_path, read_only=True)
        self.conn_id = self.app_db.create_connection("Messy Shop", "sqlite", self.db_path)
        self.snap_id = self.catalog.capture_and_record_snapshot(self.conn_id, self.engine)
        self.snap = self.app_db.get_latest_snapshot(self.conn_id)

        self.client = TestClient(app)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_heuristic_fk_inference_and_trap_rejection(self):
        inferred = self.fk_inferrer.infer_foreign_keys(self.engine, self.snap, min_score=0.65)
        self.assertTrue(len(inferred) >= 1)

        # Top match should be orders.cust_id -> customers.id
        top = inferred[0]
        self.assertEqual(top["child_table"], "orders")
        self.assertEqual(top["child_column"], "cust_id")
        self.assertEqual(top["parent_table"], "customers")
        self.assertEqual(top["parent_column"], "id")
        self.assertEqual(top["containment"], 1.0) # 100% overlap
        self.assertGreaterEqual(top["score"], 0.85)

        # Lookup trap rejection: orders.status_code -> regions.id should NOT be the top match
        for inf in inferred:
            if inf["child_column"] == "status_code" and inf["parent_table"] == "regions":
                self.assertLess(inf["score"], top["score"])

    def test_hygiene_findings_detection_and_dismiss_memory(self):
        findings = self.hygiene.run_hygiene_audit(self.engine, self.snap, self.conn_id)
        kinds = [f["kind"] for f in findings]

        # Verify planted problems are detected
        self.assertIn("mixed_dates", kinds)
        self.assertIn("sentinels", kinds)
        self.assertIn("high_null_rate", kinds)
        self.assertIn("orphans", kinds)
        self.assertIn("unindexed_fk", kinds)

        # Find orphan finding
        orphan_finding = next(f for f in findings if f["kind"] == "orphans")
        self.assertIn("Found 1 orphaned records", orphan_finding["summary"])

        # Dismiss the orphan finding
        with self.app_db._get_connection() as conn:
            conn.execute("UPDATE findings SET status = 'dismissed' WHERE id = ?;", (orphan_finding["id"],))
            conn.commit()

        # Re-run hygiene audit
        re_run_findings = self.hygiene.run_hygiene_audit(self.engine, self.snap, self.conn_id)
        # Dismissed finding should not be in the newly returned open findings
        re_run_kinds = [f["kind"] for f in re_run_findings]
        self.assertNotIn("orphans", re_run_kinds)

    def test_glossary_management_and_documentation_export(self):
        # 1. Propose and confirm entries
        g1 = self.glossary.propose_entry(
            connection_id=self.conn_id,
            target_kind="column",
            target="orders.status_code",
            kind="enum_map",
            body="1: Created, 2: Paid, 3: Shipped",
        )
        self.glossary.set_entry_status(g1, "confirmed")

        g2 = self.glossary.propose_entry(
            connection_id=self.conn_id,
            target_kind="table",
            target="customers",
            kind="description",
            body="Core customer master table containing verified account profiles.",
        )
        self.glossary.set_entry_status(g2, "confirmed")

        # 2. Markdown Export
        md_docs = self.glossary.export_markdown(self.conn_id, self.snap["structure"])
        self.assertIn("# Data Dictionary & Schema Catalog", md_docs)
        self.assertIn("Core customer master table", md_docs)
        self.assertIn("1: Created, 2: Paid, 3: Shipped", md_docs)
        self.assertIn("order_items", md_docs)

        # 3. dbt sources.yml Export
        dbt_yml = self.glossary.export_dbt_sources(self.conn_id, self.snap["structure"], source_name="prod_raw")
        self.assertIn("version: 2", dbt_yml)
        self.assertIn("- name: prod_raw", dbt_yml)
        self.assertIn("- unique", dbt_yml)
        self.assertIn("- not_null", dbt_yml)
        self.assertIn("relationships:", dbt_yml)

    def test_routes_v2_phase2_endpoints(self):
        # Register connection via API
        reg_res = self.client.post("/api/v2/connections", json={
            "name": "API Messy Shop",
            "engine": "sqlite",
            "dsn_template": self.db_path,
            "tier": "sandbox",
        })
        self.assertEqual(reg_res.status_code, 200)
        api_conn_id = reg_res.json()["connection_id"]

        # 1. Trigger relationship inference endpoint
        inf_res = self.client.post(f"/api/v2/connections/{api_conn_id}/relationships/infer")
        self.assertEqual(inf_res.status_code, 200)
        inferred = inf_res.json()["inferred_relationships"]
        self.assertTrue(len(inferred) >= 1)
        rel_id = inferred[0]["id"]

        # 2. Confirm relationship
        conf_res = self.client.post(f"/api/v2/relationships/{rel_id}/confirm")
        self.assertEqual(conf_res.status_code, 200)
        self.assertEqual(conf_res.json()["decision"], "confirmed")

        # 3. Run hygiene audit endpoint
        hyg_res = self.client.post(f"/api/v2/connections/{api_conn_id}/hygiene")
        self.assertEqual(hyg_res.status_code, 200)
        findings = hyg_res.json()["findings"]
        self.assertTrue(len(findings) >= 1)
        find_id = findings[0]["id"]

        # 4. Patch finding status to dismissed
        patch_res = self.client.patch(f"/api/v2/findings/{find_id}", json={"status": "dismissed", "dismiss_reason": "Expected test artifact"})
        self.assertEqual(patch_res.status_code, 200)
        self.assertEqual(patch_res.json()["status"], "dismissed")

        # 5. Export docs endpoints
        md_res = self.client.get(f"/api/v2/connections/{api_conn_id}/export/docs?format=markdown")
        self.assertEqual(md_res.status_code, 200)
        self.assertIn("Data Dictionary", md_res.json()["content"])

        dbt_res = self.client.get(f"/api/v2/connections/{api_conn_id}/export/docs?format=dbt_sources")
        self.assertEqual(dbt_res.status_code, 200)
        self.assertIn("version: 2", dbt_res.json()["content"])


if __name__ == "__main__":
    unittest.main()
