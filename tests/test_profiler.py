"""
Unit tests for Squad B: Profiler & PII Detector.

Validates:
- services/pii_detector.py
- services/profiler.py
"""

import unittest
import sqlite3
from typing import Optional, List

from core.db_models import (
    ProfileResponse,
    ColumnProfile,
    QueryResponse,
    AnomalyReport,
)
from services.pii_detector import (
    scan_column_for_pii,
    scan_table_for_pii,
    is_valid_email,
    is_valid_ssn,
    is_valid_credit_card,
    is_valid_phone,
    is_valid_ip,
    is_secret_token_or_credential,
    is_luhn_valid,
)
from services.profiler import run_table_profile


class TestPIIDetector(unittest.TestCase):
    """Test suite for sensitive PII scanning and credential detection."""

    def test_email_detection(self):
        self.assertTrue(is_valid_email("user.name+tag@example.com"))
        self.assertTrue(is_valid_email("alice@subdomain.company.org"))
        self.assertFalse(is_valid_email("not_an_email"))
        self.assertFalse(is_valid_email("12345"))

        reports = scan_column_for_pii("users", "contact_email", ["john@test.com", "jane@test.org"])
        self.assertEqual(len(reports), 1)
        self.assertEqual(reports[0].category, "pii_risk")
        self.assertEqual(reports[0].severity, "warning")
        self.assertEqual(reports[0].column, "contact_email")

    def test_ssn_detection(self):
        self.assertTrue(is_valid_ssn("123-45-6789"))
        self.assertTrue(is_valid_ssn("987-65-4321"))
        self.assertFalse(is_valid_ssn("000-12-3456"))  # Invalid US SSN area

        reports = scan_column_for_pii("employees", "ssn", ["123-45-6789"])
        self.assertEqual(len(reports), 1)
        self.assertEqual(reports[0].category, "pii_risk")
        self.assertEqual(reports[0].severity, "critical")
        self.assertIn("Social Security Numbers", reports[0].description)

    def test_credit_card_detection(self):
        # Visa test format
        self.assertTrue(is_valid_credit_card("4532-1234-5678-9010"))
        self.assertTrue(is_valid_credit_card("4000000000000002"))
        self.assertTrue(is_luhn_valid("4000000000000002"))
        self.assertFalse(is_valid_credit_card("123"))

        reports = scan_column_for_pii("payments", "credit_card", ["4532-1234-5678-9010"])
        self.assertEqual(len(reports), 1)
        self.assertEqual(reports[0].category, "pii_risk")
        self.assertEqual(reports[0].severity, "critical")
        self.assertIn("Credit Card", reports[0].description)

    def test_phone_detection(self):
        self.assertTrue(is_valid_phone("+1-555-123-4567"))
        self.assertTrue(is_valid_phone("(555) 987-6543"))
        self.assertTrue(is_valid_phone("555.234.5678"))
        self.assertFalse(is_valid_phone("abc-def-ghij"))

        reports = scan_column_for_pii("leads", "phone_number", ["+1 (555) 123-4567"])
        self.assertEqual(len(reports), 1)
        self.assertEqual(reports[0].category, "pii_risk")
        self.assertEqual(reports[0].severity, "warning")

    def test_secrets_and_passwords(self):
        self.assertTrue(is_secret_token_or_credential("ghp_123456789012345678901234567890123456"))
        self.assertTrue(is_secret_token_or_credential("AKIAIOSFODNN7EXAMPLE"))
        self.assertTrue(is_secret_token_or_credential("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.doNotDisclose"))

        reports = scan_column_for_pii("credentials", "password", ["PlainTextPassword123!"])
        self.assertEqual(len(reports), 1)
        self.assertEqual(reports[0].category, "pii_risk")
        self.assertEqual(reports[0].severity, "critical")

    def test_ip_address_detection(self):
        self.assertTrue(is_valid_ip("192.168.1.1"))
        self.assertTrue(is_valid_ip("10.0.0.254"))
        self.assertTrue(is_valid_ip("2001:0db8:85a3:0000:0000:8a2e:0370:7334"))
        self.assertFalse(is_valid_ip("999.999.999.999"))
        self.assertFalse(is_valid_ip("localhost"))

        reports = scan_column_for_pii("web_logs", "client_ip", ["192.168.1.100"])
        self.assertEqual(len(reports), 1)
        self.assertEqual(reports[0].category, "pii_risk")
        self.assertEqual(reports[0].severity, "info")

    def test_non_pii_columns(self):
        reports = scan_column_for_pii("products", "description", ["High quality leather boots", "Running shoes"])
        self.assertEqual(len(reports), 0)

    def test_scan_table_for_pii(self):
        data = {
            "email": ["user@example.com"],
            "ip": ["127.0.0.1"],
            "item_name": ["Widget A"],
        }
        reports = scan_table_for_pii("test_tbl", data)
        self.assertEqual(len(reports), 2)
        categories = [r.column for r in reports]
        self.assertIn("email", categories)
        self.assertIn("ip", categories)


class MockDatabaseManager:
    """Mock database manager adhering to Squad A execute_query contract."""

    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def execute_query(self, query: str, mode: str = "read_only", limit: Optional[int] = None) -> QueryResponse:
        cur = self.connection.execute(query)
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description] if cur.description else []
        return QueryResponse(
            status="success",
            columns=cols,
            rows=[list(r) for r in rows],
            row_count=len(rows)
        )


class TestProfiler(unittest.TestCase):
    """Test suite for statistical profiling and anomaly detection."""

    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.execute("""
            CREATE TABLE customers (
                customer_id INTEGER,
                full_name TEXT,
                email TEXT,
                ssn TEXT,
                credit_card TEXT,
                phone TEXT,
                password TEXT,
                ip_address TEXT,
                age INTEGER,
                purchase_amount REAL,
                optional_notes TEXT
            )
        """)

        # Insert 10 rows:
        # - customer_id has a duplicate (id 5 appears twice)
        # - optional_notes has 8 NULLs out of 10 rows (80% null burst)
        # - age has -10 (domain anomaly) and 150 (outlier)
        # - PII fields in email, ssn, credit_card, phone, password, ip_address
        rows = [
            (1, "Alice Smith", "alice@example.com", "123-45-6789", "4532-1234-5678-9010", "+1-555-1001", "secret1", "192.168.1.1", 25, 100.0, None),
            (2, "Bob Jones", "bob@example.com", "234-56-7890", "5425-2345-6789-0123", "+1-555-1002", "secret2", "192.168.1.2", 30, 150.0, None),
            (3, "Charlie Day", "charlie@example.com", "345-67-8901", "3782-822463-10005", "+1-555-1003", "secret3", "192.168.1.3", 35, 200.0, None),
            (4, "David Miller", "david@example.com", "456-78-9012", "6011-1111-1111-1117", "+1-555-1004", "secret4", "192.168.1.4", 40, 250.0, None),
            (5, "Eve Taylor", "eve@example.com", "567-89-0123", "4000-0000-0000-0002", "+1-555-1005", "secret5", "192.168.1.5", 28, 300.0, None),
            (5, "Eve Duplicate", "eve2@example.com", "567-89-0124", "4000-0000-0000-0003", "+1-555-1006", "secret6", "192.168.1.6", 29, 310.0, None),
            (7, "Frank Wright", "frank@example.com", "678-90-1234", "4111-1111-1111-1111", "+1-555-1007", "secret7", "192.168.1.7", -10, 50.0, None),
            (8, "Grace Hopper", "grace@example.com", "789-01-2345", "4222-2222-2222-2222", "+1-555-1008", "secret8", "192.168.1.8", 150, 1000.0, None),
            (9, "Heidi Klum", "heidi@example.com", "890-12-3456", "4333-3333-3333-3333", "+1-555-1009", "secret9", "192.168.1.9", 32, 120.0, "VIP client"),
            (10, "Ivan Drago", "ivan@example.com", "901-23-4567", "4444-4444-4444-4444", "+1-555-1010", "secret10", "192.168.1.10", 33, 130.0, "Contact by phone"),
        ]
        for r in rows:
            self.conn.execute("INSERT INTO customers VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", r)

    def tearDown(self):
        self.conn.close()

    def test_run_table_profile_sqlite_connection(self):
        response: ProfileResponse = run_table_profile(self.conn, "customers")

        self.assertEqual(response.status, "success")
        self.assertEqual(response.table, "customers")
        self.assertEqual(response.total_rows, 10)
        self.assertEqual(response.total_columns, 11)
        self.assertEqual(len(response.columns_profile), 11)

        # Validate column profiles
        col_map = {col.name: col for col in response.columns_profile}
        self.assertIn("customer_id", col_map)
        self.assertEqual(col_map["customer_id"].null_count, 0)
        self.assertEqual(col_map["customer_id"].unique_count, 9)  # 9 distinct IDs in 10 rows

        self.assertIn("optional_notes", col_map)
        self.assertEqual(col_map["optional_notes"].null_count, 8)
        self.assertEqual(col_map["optional_notes"].null_percentage, 80.0)

        # Validate anomalies
        anom_categories = [a.category for a in response.anomalies]
        anom_cols = {a.column: a for a in response.anomalies}

        # 1. Null burst
        self.assertIn("null_burst", anom_categories)
        self.assertEqual(anom_cols["optional_notes"].category, "null_burst")
        self.assertEqual(anom_cols["optional_notes"].severity, "critical")

        # 2. Duplicate candidate key
        self.assertIn("duplicate_pk", anom_categories)
        self.assertEqual(anom_cols["customer_id"].category, "duplicate_pk")

        # 3. Extreme outliers in age (negative domain anomaly)
        self.assertIn("extreme_outlier", anom_categories)
        age_anomalies = [a for a in response.anomalies if a.column == "age"]
        self.assertTrue(len(age_anomalies) >= 1)

        # 4. Sensitive PII
        pii_cols = {a.column: a.severity for a in response.anomalies if a.category == "pii_risk"}
        self.assertEqual(pii_cols.get("email"), "warning")
        self.assertEqual(pii_cols.get("ssn"), "critical")
        self.assertEqual(pii_cols.get("credit_card"), "critical")
        self.assertEqual(pii_cols.get("phone"), "warning")
        self.assertEqual(pii_cols.get("password"), "critical")
        self.assertEqual(pii_cols.get("ip_address"), "info")

    def test_run_table_profile_mock_manager(self):
        manager = MockDatabaseManager(self.conn)
        response: ProfileResponse = run_table_profile(manager, "customers")

        self.assertEqual(response.status, "success")
        self.assertEqual(response.total_rows, 10)
        self.assertTrue(len(response.columns_profile) > 0)
        self.assertTrue(len(response.anomalies) > 0)

    def test_run_table_profile_empty_table(self):
        self.conn.execute("CREATE TABLE empty_table (id INT, label TEXT)")
        response: ProfileResponse = run_table_profile(self.conn, "empty_table")

        self.assertEqual(response.status, "success")
        self.assertEqual(response.total_rows, 0)
        self.assertEqual(response.total_columns, 2)
        empty_anomalies = [a for a in response.anomalies if a.category == "empty_table"]
        self.assertEqual(len(empty_anomalies), 1)

    def test_run_table_profile_non_existent_table(self):
        response: ProfileResponse = run_table_profile(self.conn, "does_not_exist_xyz")
        self.assertEqual(response.status, "error")
        self.assertIsNotNone(response.error)


if __name__ == "__main__":
    unittest.main()
