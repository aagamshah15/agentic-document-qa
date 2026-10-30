import os
import json
import unittest
from fastapi.testclient import TestClient
from main import app
from services.db_manager import db_manager


class TestMockDatasetsE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.base_dir = os.path.dirname(os.path.dirname(__file__))
        cls.sample_datasets_dir = os.path.join(cls.base_dir, "data", "sample_datasets")
        cls.manifest_path = os.path.join(cls.sample_datasets_dir, "test_scenarios.json")

    def setUp(self):
        # Reset DB manager connection state before each test
        db_manager.close()

    def tearDown(self):
        db_manager.close()

    def test_01_manifest_structure_and_completeness(self):
        """Verify test_scenarios.json manifest is complete with 5-8 scenarios per dataset."""
        self.assertTrue(os.path.exists(self.manifest_path), "test_scenarios.json does not exist")
        with open(self.manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)

        self.assertIn("datasets", manifest)
        expected_datasets = [
            "ecommerce.sqlite",
            "dirty_leads.csv",
            "stock_market.csv",
            "server_telemetry.parquet",
        ]

        for ds_name in expected_datasets:
            self.assertIn(ds_name, manifest["datasets"], f"Missing {ds_name} in manifest")
            ds_info = manifest["datasets"][ds_name]
            scenarios = ds_info["scenarios"]
            self.assertGreaterEqual(len(scenarios), 5, f"{ds_name} has fewer than 5 scenarios")
            self.assertLessEqual(len(scenarios), 8, f"{ds_name} has more than 8 scenarios")

            # Verify actual file exists on disk
            real_file_path = os.path.join(self.base_dir, ds_info["dataset_file"])
            self.assertTrue(os.path.exists(real_file_path), f"File {real_file_path} does not exist on disk")

            # Verify scenario fields
            for sc in scenarios:
                self.assertIn("id", sc)
                self.assertIn("category", sc)
                self.assertIn("question", sc)
                self.assertIn("description", sc)
                self.assertIn("reference_sql", sc)
                self.assertIn("safety_mode", sc)

    def test_02_ecommerce_sqlite_introspection_and_queries(self):
        """Test connecting to ecommerce.sqlite, verifying multi-table schema, foreign keys, row counts and queries."""
        file_path = os.path.join(self.sample_datasets_dir, "ecommerce.sqlite")
        with open(file_path, "rb") as f:
            res = self.client.post(
                "/api/db/connect",
                files={"file": ("ecommerce.sqlite", f, "application/x-sqlite3")},
            )

        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "connected")
        self.assertEqual(data["engine"], "duckdb")

        # Verify tables present
        table_map = {t["name"]: t for t in data["tables"]}
        for expected_table in ["customers", "products", "orders", "order_items"]:
            self.assertIn(expected_table, table_map, f"Table {expected_table} missing from schema")

        # Verify row counts
        self.assertEqual(table_map["customers"]["row_count"], 50)
        self.assertEqual(table_map["products"]["row_count"], 25)
        self.assertEqual(table_map["orders"]["row_count"], 100)
        self.assertGreaterEqual(table_map["order_items"]["row_count"], 200)

        # Verify columns
        cust_cols = [c["name"] for c in table_map["customers"]["columns"]]
        self.assertListEqual(cust_cols, ["id", "name", "email", "country", "signup_date"])

        prod_cols = [c["name"] for c in table_map["products"]["columns"]]
        self.assertListEqual(prod_cols, ["id", "sku", "title", "category", "price", "stock"])

        order_cols = [c["name"] for c in table_map["orders"]["columns"]]
        self.assertListEqual(order_cols, ["id", "customer_id", "order_date", "status", "total_amount"])

        item_cols = [c["name"] for c in table_map["order_items"]["columns"]]
        self.assertListEqual(item_cols, ["id", "order_id", "product_id", "quantity", "unit_price"])

        # Verify foreign keys
        order_fks = table_map["orders"]["foreign_keys"]
        self.assertTrue(
            any(fk["referred_table"] == "customers" and "customer_id" in fk["constrained_columns"] for fk in order_fks),
            "Foreign key orders.customer_id -> customers.id missing",
        )

        item_fks = table_map["order_items"]["foreign_keys"]
        has_order_fk = any(fk["referred_table"] == "orders" and "order_id" in fk["constrained_columns"] for fk in item_fks)
        has_prod_fk = any(fk["referred_table"] == "products" and "product_id" in fk["constrained_columns"] for fk in item_fks)
        self.assertTrue(has_order_fk, "Foreign key order_items.order_id -> orders.id missing")
        self.assertTrue(has_prod_fk, "Foreign key order_items.product_id -> products.id missing")

        # Verify schema endpoint
        schema_res = self.client.get("/api/db/schema")
        self.assertEqual(schema_res.status_code, 200)
        self.assertEqual(len(schema_res.json()["tables"]), 4)

        # Execute Top N Customers query
        top_cust_query = (
            "SELECT c.name, c.country, ROUND(SUM(o.total_amount), 2) AS total_spent "
            "FROM customers c JOIN orders o ON c.id = o.customer_id "
            "WHERE o.status = 'completed' "
            "GROUP BY c.name, c.country "
            "ORDER BY total_spent DESC LIMIT 5;"
        )
        q_res = self.client.post("/api/db/query", json={"query": top_cust_query, "mode": "read_only"})
        self.assertEqual(q_res.status_code, 200)
        q_data = q_res.json()
        self.assertEqual(q_data["status"], "success")
        self.assertEqual(q_data["row_count"], 5)
        self.assertGreater(q_data["rows"][0][2], 0.0)

        # Execute Best-Selling Category join query
        cat_query = (
            "SELECT p.category, SUM(oi.quantity) AS units_sold, ROUND(SUM(oi.quantity * oi.unit_price), 2) AS revenue "
            "FROM products p "
            "JOIN order_items oi ON p.id = oi.product_id "
            "JOIN orders o ON oi.order_id = o.id "
            "WHERE o.status = 'completed' "
            "GROUP BY p.category "
            "ORDER BY revenue DESC;"
        )
        cat_res = self.client.post("/api/db/query", json={"query": cat_query, "mode": "read_only"})
        self.assertEqual(cat_res.status_code, 200)
        self.assertEqual(cat_res.json()["status"], "success")
        self.assertGreater(len(cat_res.json()["rows"]), 0)

        # Verify safe execution blocking DELETE in read-only mode
        del_query = "DELETE FROM orders WHERE status = 'cancelled';"
        del_res = self.client.post("/api/db/query", json={"query": del_query, "mode": "read_only"})
        self.assertEqual(del_res.status_code, 200)
        self.assertEqual(del_res.json()["status"], "error")
        self.assertIn("blocked in read_only mode", del_res.json()["error"])

    def test_03_dirty_leads_introspection_and_profiling(self):
        """Test dirty_leads.csv ingestion, data quality queries, null burst detection, and PII scanning."""
        file_path = os.path.join(self.sample_datasets_dir, "dirty_leads.csv")
        with open(file_path, "rb") as f:
            res = self.client.post(
                "/api/db/connect",
                files={"file": ("dirty_leads.csv", f, "text/csv")},
            )

        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "connected")
        table_names = [t["name"] for t in data["tables"]]
        self.assertIn("dirty_leads", table_names)

        dirty_table = next(t for t in data["tables"] if t["name"] == "dirty_leads")
        self.assertEqual(dirty_table["row_count"], 50)
        col_names = [c["name"] for c in dirty_table["columns"]]
        for col in ["full_name", "company", "email", "phone", "credit_card", "ssn"]:
            self.assertIn(col, col_names)

        # 1. Query: Detect leading/trailing whitespace
        ws_query = "SELECT COUNT(*) FROM dirty_leads WHERE full_name != TRIM(full_name) OR company != TRIM(company);"
        ws_res = self.client.post("/api/db/query", json={"query": ws_query, "mode": "read_only"})
        self.assertEqual(ws_res.status_code, 200)
        ws_data = ws_res.json()
        self.assertEqual(ws_data["status"], "success")
        self.assertGreater(ws_data["rows"][0][0], 0, "Expected dirty leads with untrimmed whitespace")

        # 2. Query: Detect duplicate emails with case/spacing variations
        dup_query = (
            "SELECT LOWER(TRIM(email)) AS norm_email, COUNT(*) AS count "
            "FROM dirty_leads GROUP BY norm_email HAVING count > 1 ORDER BY count DESC;"
        )
        dup_res = self.client.post("/api/db/query", json={"query": dup_query, "mode": "read_only"})
        self.assertEqual(dup_res.status_code, 200)
        dup_data = dup_res.json()
        self.assertEqual(dup_data["status"], "success")
        self.assertGreater(len(dup_data["rows"]), 0, "Expected duplicate email clusters")

        # 3. Profiling: Check null burst and PII detection
        prof_res = self.client.post("/api/db/profile", json={"table": "dirty_leads"})
        self.assertEqual(prof_res.status_code, 200)
        prof_data = prof_res.json()
        self.assertEqual(prof_data["status"], "success")
        self.assertEqual(prof_data["table"], "dirty_leads")
        self.assertEqual(prof_data["total_rows"], 50)

        # Check phone null burst (>60% null rate)
        phone_profile = next(c for c in prof_data["columns_profile"] if c["name"] == "phone")
        self.assertGreaterEqual(phone_profile["null_percentage"], 60.0)

        anomalies = prof_data["anomalies"]
        # Verify null burst anomaly
        null_burst_cols = [a["column"] for a in anomalies if a["category"] == "null_burst"]
        self.assertIn("phone", null_burst_cols, "Profiler did not flag 'phone' for null_burst")

        # Verify PII detection
        pii_cols = [a["column"] for a in anomalies if a["category"] == "pii_risk"]
        self.assertIn("email", pii_cols, "Profiler did not flag 'email' for pii_risk")
        self.assertIn("credit_card", pii_cols, "Profiler did not flag 'credit_card' for pii_risk")
        self.assertIn("ssn", pii_cols, "Profiler did not flag 'ssn' for pii_risk")

        # Verify safe execution blocking DROP TABLE in read-only mode
        drop_query = "DROP TABLE dirty_leads;"
        drop_res = self.client.post("/api/db/query", json={"query": drop_query, "mode": "read_only"})
        self.assertEqual(drop_res.status_code, 200)
        self.assertEqual(drop_res.json()["status"], "error")
        self.assertIn("blocked in read_only mode", drop_res.json()["error"])

    def test_04_stock_market_introspection_and_outliers(self):
        """Test stock_market.csv ingestion, time-series metrics, negative balance outliers and profiling."""
        file_path = os.path.join(self.sample_datasets_dir, "stock_market.csv")
        with open(file_path, "rb") as f:
            res = self.client.post(
                "/api/db/connect",
                files={"file": ("stock_market.csv", f, "text/csv")},
            )

        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "connected")
        table_names = [t["name"] for t in data["tables"]]
        self.assertIn("stock_market", table_names)

        stock_table = next(t for t in data["tables"] if t["name"] == "stock_market")
        self.assertEqual(stock_table["row_count"], 180)
        col_names = [c["name"] for c in stock_table["columns"]]
        for col in ["ticker", "date", "open", "high", "low", "close", "volume", "balance"]:
            self.assertIn(col, col_names)

        # 1. Query: Verify all 3 tickers exist
        tickers_query = "SELECT DISTINCT ticker FROM stock_market ORDER BY ticker;"
        t_res = self.client.post("/api/db/query", json={"query": tickers_query, "mode": "read_only"})
        self.assertEqual(t_res.status_code, 200)
        self.assertEqual([r[0] for r in t_res.json()["rows"]], ["AAPL", "GOOGL", "MSFT"])

        # 2. Query: Identify negative balance outliers
        outlier_query = "SELECT ticker, date, balance FROM stock_market WHERE balance < 0 ORDER BY balance ASC;"
        out_res = self.client.post("/api/db/query", json={"query": outlier_query, "mode": "read_only"})
        self.assertEqual(out_res.status_code, 200)
        out_rows = out_res.json()["rows"]
        self.assertGreaterEqual(len(out_rows), 3, "Expected at least 3 negative balance outliers")
        for row in out_rows:
            self.assertLess(row[2], 0.0)

        # 3. Profiling: Check extreme outlier anomaly on balance
        prof_res = self.client.post("/api/db/profile", json={"table": "stock_market"})
        self.assertEqual(prof_res.status_code, 200)
        anomalies = prof_res.json()["anomalies"]
        outlier_anomalies = [a for a in anomalies if a["category"] == "extreme_outlier" and a["column"] == "balance"]
        self.assertGreater(len(outlier_anomalies), 0, "Expected extreme_outlier anomaly on balance column")

        # Safe execution check
        upd_query = "UPDATE stock_market SET balance = 0 WHERE balance < 0;"
        upd_res = self.client.post("/api/db/query", json={"query": upd_query, "mode": "read_only"})
        self.assertEqual(upd_res.status_code, 200)
        self.assertEqual(upd_res.json()["status"], "error")
        self.assertIn("blocked in read_only mode", upd_res.json()["error"])

    def test_05_server_telemetry_parquet_introspection_and_queries(self):
        """Test server_telemetry.parquet ingestion, metrics queries, latency distribution and guardrails."""
        file_path = os.path.join(self.sample_datasets_dir, "server_telemetry.parquet")
        with open(file_path, "rb") as f:
            res = self.client.post(
                "/api/db/connect",
                files={"file": ("server_telemetry.parquet", f, "application/octet-stream")},
            )

        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "connected")
        table_names = [t["name"] for t in data["tables"]]
        self.assertIn("server_telemetry", table_names)

        telemetry_table = next(t for t in data["tables"] if t["name"] == "server_telemetry")
        self.assertEqual(telemetry_table["row_count"], 400)
        col_names = [c["name"] for c in telemetry_table["columns"]]
        for col in ["timestamp", "server_id", "cpu_utilization", "memory_mb", "status_code", "latency_ms"]:
            self.assertIn(col, col_names)

        # 1. Query: Error rate calculation (5xx status codes)
        err_query = (
            "SELECT server_id, COUNT(*) AS total, "
            "SUM(CASE WHEN status_code >= 500 THEN 1 ELSE 0 END) AS err_count "
            "FROM server_telemetry GROUP BY server_id ORDER BY total DESC LIMIT 5;"
        )
        err_res = self.client.post("/api/db/query", json={"query": err_query, "mode": "read_only"})
        self.assertEqual(err_res.status_code, 200)
        err_data = err_res.json()
        self.assertEqual(err_data["status"], "success")
        self.assertEqual(len(err_data["rows"]), 5)

        # 2. Query: Peak latency events
        peak_query = "SELECT server_id, latency_ms, cpu_utilization FROM server_telemetry ORDER BY latency_ms DESC LIMIT 3;"
        peak_res = self.client.post("/api/db/query", json={"query": peak_query, "mode": "read_only"})
        self.assertEqual(peak_res.status_code, 200)
        self.assertEqual(peak_res.json()["status"], "success")
        self.assertEqual(len(peak_res.json()["rows"]), 3)

        # Safe execution check
        trunc_query = "TRUNCATE TABLE server_telemetry;"
        trunc_res = self.client.post("/api/db/query", json={"query": trunc_query, "mode": "read_only"})
        self.assertEqual(trunc_res.status_code, 200)
        self.assertEqual(trunc_res.json()["status"], "error")
        self.assertIn("blocked in read_only mode", trunc_res.json()["error"])

    def test_06_shape_queries_across_all_datasets(self):
        """Execute shape queries for all 4 mock datasets and verify correct dimensions."""
        with open(self.manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)

        mime_types = {
            ".sqlite": "application/x-sqlite3",
            ".csv": "text/csv",
            ".parquet": "application/octet-stream",
        }

        for ds_name, ds_info in manifest["datasets"].items():
            db_manager.close()
            ext = os.path.splitext(ds_name)[1]
            mime = mime_types.get(ext, "application/octet-stream")
            file_path = os.path.join(self.base_dir, ds_info["dataset_file"])

            # 1. Connect
            with open(file_path, "rb") as f:
                conn_res = self.client.post(
                    "/api/db/connect",
                    files={"file": (ds_name, f, mime)},
                )
            self.assertEqual(conn_res.status_code, 200, f"Failed to connect to {ds_name}")

            # 2. Find shape query scenario
            shape_scenario = next(
                sc for sc in ds_info["scenarios"] if sc["category"] == "shape_query"
            )
            sql = shape_scenario["reference_sql"]

            # 3. Execute query
            q_res = self.client.post("/api/db/query", json={"query": sql, "mode": "read_only"})
            self.assertEqual(q_res.status_code, 200, f"Shape query failed on {ds_name}")
            q_data = q_res.json()
            self.assertEqual(q_data["status"], "success", f"Shape query error on {ds_name}: {q_data.get('error')}")
            self.assertGreater(q_data["row_count"], 0, f"Shape query returned 0 rows on {ds_name}")
            self.assertGreater(len(q_data["columns"]), 0)


if __name__ == "__main__":
    unittest.main()
