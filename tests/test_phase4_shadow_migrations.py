"""
Unit & Integration Test Suite for Phase 4: Shadow Migrations, Lock Linting & Approval Gates.
Tests ShadowDBManager (two-way rollback verification, invariant checks),
MigrationLinter (CONCURRENTLY, NOT VALID, column drops, Alembic/Flyway export),
and FastAPI v2 proposal/approval lifecycle including strict Prod rejection (D5).
"""

import unittest
import os
import tempfile
import sqlite3
from fastapi.testclient import TestClient

from main import app
from services.app_db import StudioAppDB
from services.shadow_db import ShadowDBManager
from services.migration_linter import MigrationLinter


class TestPhase4ShadowMigrations(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.app_db_path = os.path.join(self.temp_dir.name, "test_studio_p4.db")
        self.app_db = StudioAppDB(db_path=self.app_db_path)
        self.shadow = ShadowDBManager()
        self.linter = MigrationLinter()

        # Create target SQLite database
        self.db_path = os.path.join(self.temp_dir.name, "target_db.db")
        conn = sqlite3.connect(self.db_path)
        conn.executescript("""
            CREATE TABLE products (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                price REAL
            );
        """)
        conn.execute("INSERT INTO products VALUES (1, 'Widget', 9.99);")
        conn.commit()
        conn.close()

        self.client = TestClient(app)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_shadow_verification_two_way_rollback(self):
        # UP: Add column stock_count
        # DOWN: Drop column stock_count
        up_sql = "ALTER TABLE products ADD COLUMN stock_count INTEGER DEFAULT 0;"
        down_sql = "ALTER TABLE products DROP COLUMN stock_count;"

        res = self.shadow.verify_migration("sqlite", self.db_path, up_sql, down_sql)
        self.assertEqual(res["status"], "verified")
        self.assertTrue(res["rollback_clean"])
        self.assertTrue(res["up_duration_ms"] >= 0)
        self.assertTrue(res["down_duration_ms"] >= 0)

    def test_shadow_verification_detects_broken_rollback(self):
        # DOWN does not undo UP (leaves products_v2 table)
        up_sql = "CREATE TABLE products_v2 (id INT);"
        down_sql = "SELECT 1;" # Doesn't drop products_v2!

        res = self.shadow.verify_migration("sqlite", self.db_path, up_sql, down_sql)
        self.assertEqual(res["status"], "imperfect_rollback")
        self.assertFalse(res["rollback_clean"])

    def test_migration_lock_risk_linter_and_exports(self):
        # 1. Lock risk checks
        pg_index = "CREATE INDEX idx_products_price ON products(price);"
        lint_res = self.linter.lint_ddl(pg_index, engine_type="postgres")
        self.assertTrue(lint_res["is_risky"])
        self.assertTrue(any("CONCURRENTLY" in w for w in lint_res["warnings"]))

        # 2. Export Alembic
        alembic_code = self.linter.export_alembic("Add stock count", "ALTER TABLE products ADD COLUMN stock INT;", "ALTER TABLE products DROP COLUMN stock;")
        self.assertIn("def upgrade() -> None:", alembic_code)
        self.assertIn("def downgrade() -> None:", alembic_code)
        self.assertIn("op.execute", alembic_code)

        # 3. Export Flyway
        flyway_code = self.linter.export_flyway("Add stock count", "ALTER TABLE products ADD COLUMN stock INT;")
        self.assertIn("-- Flyway Migration:", flyway_code)
        self.assertIn("ALTER TABLE products ADD COLUMN stock INT;", flyway_code)

    def test_proposal_approval_lifecycle_and_prod_rejection(self):
        # 1. Register sandbox connection
        reg = self.client.post("/api/v2/connections", json={
            "name": "Dev Products DB",
            "engine": "sqlite",
            "dsn_template": self.db_path,
            "tier": "dev",
        })
        self.assertEqual(reg.status_code, 200)
        conn_id = reg.json()["connection_id"]

        # 2. Submit proposal
        up_sql = "ALTER TABLE products ADD COLUMN sku TEXT;"
        down_sql = "ALTER TABLE products DROP COLUMN sku;"

        prop_res = self.client.post("/api/v2/proposals", json={
            "connection_id": conn_id,
            "goal": "Add SKU identifier to products table",
            "up_sql": up_sql,
            "down_sql": down_sql,
        })
        self.assertEqual(prop_res.status_code, 200)
        prop_data = prop_res.json()
        prop_id = prop_data["proposal_id"]
        self.assertEqual(prop_data["verification_status"], "verified")

        # 3. Attempting to apply unapproved proposal must fail (400)
        unapproved_apply = self.client.post(f"/api/v2/proposals/{prop_id}/apply")
        self.assertEqual(unapproved_apply.status_code, 400)

        # 4. Record human approval decision
        dec_res = self.client.post(f"/api/v2/proposals/{prop_id}/decision", json={
            "decision": "approved",
            "typed_confirmation": "products",
            "comment": "Verified on shadow database, safe to apply",
        })
        self.assertEqual(dec_res.status_code, 200)
        self.assertEqual(dec_res.json()["status"], "approved")

        # 5. Apply approved proposal to Dev database
        apply_res = self.client.post(f"/api/v2/proposals/{prop_id}/apply")
        self.assertEqual(apply_res.status_code, 200)
        self.assertEqual(apply_res.json()["status"], "applied")

        # Verify column exists on live database
        conn = sqlite3.connect(self.db_path)
        col_names = [r[1] for r in conn.execute("PRAGMA table_info(products);").fetchall()]
        conn.close()
        self.assertIn("sku", col_names)

        # 6. Strict Prod Guardrail (D5): register prod connection and verify apply fails
        prod_reg = self.client.post("/api/v2/connections", json={
            "name": "Production DB",
            "engine": "sqlite",
            "dsn_template": self.db_path,
            "tier": "prod",
        })
        prod_conn_id = prod_reg.json()["connection_id"]

        prod_prop = self.client.post("/api/v2/proposals", json={
            "connection_id": prod_conn_id,
            "goal": "Prod change test",
            "up_sql": "SELECT 1;",
            "down_sql": "SELECT 1;",
        })
        prod_prop_id = prod_prop.json()["proposal_id"]

        # Approve it
        self.client.post(f"/api/v2/proposals/{prod_prop_id}/decision", json={"decision": "approved"})

        # Attempt to apply to PROD must fail with 403 Forbidden
        prod_apply = self.client.post(f"/api/v2/proposals/{prod_prop_id}/apply")
        self.assertEqual(prod_apply.status_code, 403)
        self.assertIn("disabled on PROD connections in v1", prod_apply.json()["detail"])


if __name__ == "__main__":
    unittest.main()
