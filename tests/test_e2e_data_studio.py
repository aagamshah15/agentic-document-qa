import os
import unittest
from fastapi.testclient import TestClient
from main import app

class TestE2EDataStudio(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.test_csv_path = "tests/test_sample_customers.csv"
        # Create a small realistic CSV with PII and an anomaly
        with open(self.test_csv_path, "w") as f:
            f.write("id,name,email,card_number,balance,signup_date\n")
            f.write("1,Alice,alice@corp.com,4532015012345674,150.50,2026-01-15\n")
            f.write("2,Bob,bob@corp.com,,2500.00,2026-02-20\n")
            f.write("3,Charlie,charlie@corp.com,4532015012345674,-50.00,2026-03-01\n")

    def tearDown(self):
        if os.path.exists(self.test_csv_path):
            os.remove(self.test_csv_path)

    def test_01_static_frontend_assets(self):
        """Verify all frontend assets serve with HTTP 200."""
        routes = ["/", "/static/styles.css", "/static/data_grid.js", "/static/sql_runner.js", "/static/app.js"]
        for route in routes:
            res = self.client.get(route)
            self.assertEqual(res.status_code, 200, f"Route {route} failed to serve")
            self.assertGreater(len(res.content), 0)

    def test_02_connect_and_introspect_csv(self):
        """Verify file upload ingestion and schema introspection."""
        with open(self.test_csv_path, "rb") as f:
            res = self.client.post(
                "/api/db/connect",
                files={"file": ("customers.csv", f, "text/csv")}
            )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "connected")
        self.assertEqual(data["engine"], "duckdb")
        table_names = [t["name"] for t in data["tables"]]
        self.assertIn("customers", table_names)

        # Verify schema retrieval endpoint
        schema_res = self.client.get("/api/db/schema")
        self.assertEqual(schema_res.status_code, 200)
        schema_data = schema_res.json()
        customers_table = next(t for t in schema_data["tables"] if t["name"] == "customers")
        self.assertEqual(customers_table["row_count"], 3)
        col_names = [c["name"] for c in customers_table["columns"]]
        self.assertIn("email", col_names)
        self.assertIn("card_number", col_names)

    def test_03_query_execution_and_safety_guardrails(self):
        """Verify safe SELECT queries execute and mutations are blocked in read-only mode."""
        # Ensure customers table is loaded
        with open(self.test_csv_path, "rb") as f:
            self.client.post("/api/db/connect", files={"file": ("customers.csv", f, "text/csv")})

        # Safe query
        query_payload = {"query": "SELECT id, name, balance FROM customers WHERE balance > 100;", "mode": "read_only"}
        res = self.client.post("/api/db/query", json=query_payload)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["row_count"], 2)
        self.assertIn("Alice", [row[1] for row in data["rows"]])

        # Mutating query blocked in read-only mode
        unsafe_payload = {"query": "DROP TABLE customers;", "mode": "read_only"}
        unsafe_res = self.client.post("/api/db/query", json=unsafe_payload)
        self.assertEqual(unsafe_res.status_code, 200)
        unsafe_data = unsafe_res.json()
        self.assertEqual(unsafe_data["status"], "error")
        self.assertIn("blocked in read_only mode", unsafe_data["error"])

    def test_04_table_profiler_and_pii_anomalies(self):
        """Verify column statistics, outlier detection, and PII scanning."""
        with open(self.test_csv_path, "rb") as f:
            self.client.post("/api/db/connect", files={"file": ("customers.csv", f, "text/csv")})

        res = self.client.post("/api/db/profile", json={"table": "customers"})
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["table"], "customers")
        self.assertEqual(data["total_rows"], 3)

        # Verify PII detection was triggered
        anomaly_categories = [a["category"] for a in data["anomalies"]]
        self.assertIn("pii_risk", anomaly_categories)

    def test_05_agent_stream(self):
        """Verify the agent SSE streaming endpoint emits tokens."""
        with open(self.test_csv_path, "rb") as f:
            self.client.post("/api/db/connect", files={"file": ("customers.csv", f, "text/csv")})

        agent_payload = {
            "prompt": "Show all customers with negative balance",
            "table_context": ["customers"],
            "model": "gemini-1.5-flash",
            "safety_mode": "read_only"
        }
        res = self.client.post("/api/agent/stream", json=agent_payload)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.headers["content-type"], "text/event-stream; charset=utf-8")
        stream_text = res.text
        self.assertIn("data:", stream_text)
        self.assertIn("[DONE]", stream_text)

    def test_06_reject_unsupported_document_formats(self):
        """Verify PDF, DOCX, TXT, and other document formats are strictly rejected."""
        unsupported_files = [
            ("annual_report.pdf", b"%PDF-1.4...", "application/pdf"),
            ("spec.docx", b"PK...", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
            ("notes.txt", b"plain text", "text/plain"),
            ("readme.md", b"# markdown", "text/markdown"),
        ]

        for filename, content, mime in unsupported_files:
            # 1. Reject on /api/db/connect
            res_db = self.client.post(
                "/api/db/connect",
                files={"file": (filename, content, mime)}
            )
            self.assertEqual(res_db.status_code, 400, f"{filename} should be rejected on /api/db/connect")
            self.assertIn("Unsupported format", res_db.json()["detail"])

            # 2. Reject on legacy /api/upload
            res_upload = self.client.post(
                "/api/upload",
                files={"file": (filename, content, mime)}
            )
            self.assertEqual(res_upload.status_code, 400, f"{filename} should be rejected on /api/upload")
            self.assertIn("disabled", res_upload.json()["detail"])

if __name__ == "__main__":
    unittest.main()
