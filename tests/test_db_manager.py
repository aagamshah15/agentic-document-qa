import os
import tempfile
import sqlite3
import unittest
import duckdb

from services.db_manager import DatabaseManager
from core.db_models import DatabaseSchemaResponse, QueryResponse


class TestDatabaseManager(unittest.TestCase):

    def setUp(self):
        self.manager = DatabaseManager()
        self.temp_dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.manager.close()
        self.temp_dir.cleanup()

    def test_connect_csv_and_query(self):
        # 1. Create a sample CSV
        csv_path = os.path.join(self.temp_dir.name, "employees.csv")
        with open(csv_path, "w", encoding="utf-8") as f:
            f.write("id,name,department,salary\n")
            f.write("1,Alice,Engineering,120000.50\n")
            f.write("2,Bob,Product,105000.00\n")
            f.write("3,Charlie,Engineering,110000.00\n")

        # 2. Connect CSV
        schema = self.manager.connect_file(csv_path, "employees.csv")
        self.assertIsInstance(schema, DatabaseSchemaResponse)
        self.assertEqual(schema.status, "connected")
        self.assertEqual(schema.engine, "duckdb")

        # Verify table schema
        table_names = [t.name for t in schema.tables]
        self.assertIn("employees", table_names)
        emp_table = next(t for t in schema.tables if t.name == "employees")
        self.assertEqual(emp_table.row_count, 3)
        col_names = [c.name for c in emp_table.columns]
        self.assertListEqual(col_names, ["id", "name", "department", "salary"])

        # 3. Safe read query
        resp = self.manager.execute_query(
            "SELECT name, salary FROM employees WHERE department = 'Engineering' ORDER BY id",
            mode="read_only",
        )
        self.assertIsInstance(resp, QueryResponse)
        self.assertEqual(resp.status, "success")
        self.assertIsNone(resp.error)
        self.assertEqual(resp.row_count, 2)
        self.assertListEqual(resp.columns, ["name", "salary"])
        self.assertEqual(resp.rows[0], ["Alice", 120000.5])
        self.assertEqual(resp.rows[1], ["Charlie", 110000.0])
        self.assertGreaterEqual(resp.execution_time_ms, 0.0)
        self.assertFalse(resp.truncated)

    def test_connect_sqlite_and_query(self):
        # 1. Create a sample SQLite database
        sqlite_path = os.path.join(self.temp_dir.name, "store.sqlite")
        s_conn = sqlite3.connect(sqlite_path)
        s_conn.execute("CREATE TABLE products (id INTEGER PRIMARY KEY, title TEXT, price REAL)")
        s_conn.execute("INSERT INTO products VALUES (1, 'Laptop', 999.99), (2, 'Keyboard', 49.99)")
        s_conn.commit()
        s_conn.close()

        # 2. Connect SQLite file into in-memory DuckDB
        schema = self.manager.connect_file(sqlite_path, "store.sqlite")
        self.assertEqual(schema.status, "connected")
        table_names = [t.name for t in schema.tables]
        self.assertIn("products", table_names)

        prod_table = next(t for t in schema.tables if t.name == "products")
        self.assertEqual(prod_table.row_count, 2)
        pk_cols = [c.name for c in prod_table.columns if c.primary_key]
        self.assertIn("id", pk_cols)

        # 3. Query the loaded table
        resp = self.manager.execute_query("SELECT title, price FROM products ORDER BY id DESC")
        self.assertEqual(resp.status, "success")
        self.assertEqual(resp.row_count, 2)
        self.assertEqual(resp.rows[0][0], "Keyboard")
        self.assertEqual(resp.rows[1][0], "Laptop")

    def test_connect_parquet_file(self):
        # 1. Create Parquet file via temporary DuckDB session
        pq_path = os.path.join(self.temp_dir.name, "metrics.parquet")
        d = duckdb.connect()
        d.execute("CREATE TABLE metrics AS SELECT 101 AS metric_id, 42.5 AS val")
        d.execute("COPY metrics TO ? (FORMAT PARQUET)", [pq_path])
        d.close()

        # 2. Ingest via db_manager
        schema = self.manager.connect_file(pq_path, "metrics.parquet")
        self.assertEqual(schema.status, "connected")
        self.assertIn("metrics", [t.name for t in schema.tables])

        resp = self.manager.execute_query("SELECT val FROM metrics WHERE metric_id = 101")
        self.assertEqual(resp.status, "success")
        self.assertEqual(resp.rows[0][0], 42.5)

    def test_read_only_safety_blocks_mutations(self):
        # Set up a table
        csv_path = os.path.join(self.temp_dir.name, "users.csv")
        with open(csv_path, "w", encoding="utf-8") as f:
            f.write("id,username\n1,john_doe\n2,jane_doe\n")
        self.manager.connect_file(csv_path, "users.csv")

        mutating_statements = [
            "DROP TABLE users",
            "DELETE FROM users WHERE id = 1",
            "TRUNCATE TABLE users",
            "ALTER TABLE users ADD COLUMN age INT",
            "UPDATE users SET username = 'hacked' WHERE id = 1",
            "INSERT INTO users VALUES (3, 'evil')",
            "/* comment */ DROP TABLE users",
            "-- line comment\nDELETE FROM users",
        ]

        for query in mutating_statements:
            with self.subTest(query=query):
                resp = self.manager.execute_query(query, mode="read_only")
                self.assertEqual(resp.status, "error")
                self.assertEqual(resp.error, "Mutating statements blocked in read_only mode.")

        # Ensure literal strings containing mutating words are NOT blocked
        safe_query = "SELECT * FROM users WHERE username = 'DELETE'"
        resp = self.manager.execute_query(safe_query, mode="read_only")
        self.assertEqual(resp.status, "success")
        self.assertEqual(resp.row_count, 0)

    def test_mutation_mode_allows_updates(self):
        csv_path = os.path.join(self.temp_dir.name, "inventory.csv")
        with open(csv_path, "w", encoding="utf-8") as f:
            f.write("item,qty\napple,10\nbanana,20\n")
        self.manager.connect_file(csv_path, "inventory.csv")

        # Mutation mode allows INSERT
        insert_resp = self.manager.execute_query(
            "INSERT INTO inventory VALUES ('cherry', 30)",
            mode="mutation"
        )
        self.assertEqual(insert_resp.status, "success")

        # Verify insertion
        select_resp = self.manager.execute_query(
            "SELECT count(*) FROM inventory",
            mode="read_only"
        )
        self.assertEqual(select_resp.rows[0][0], 3)

    def test_query_truncation_limit(self):
        csv_path = os.path.join(self.temp_dir.name, "numbers.csv")
        with open(csv_path, "w", encoding="utf-8") as f:
            f.write("num\n")
            for i in range(120):
                f.write(f"{i}\n")
        self.manager.connect_file(csv_path, "numbers.csv")

        # Query with limit 50
        resp = self.manager.execute_query("SELECT num FROM numbers", limit=50)
        self.assertEqual(resp.status, "success")
        self.assertEqual(len(resp.rows), 50)
        self.assertEqual(resp.row_count, 50)
        self.assertTrue(resp.truncated)

        # Query with limit 200 (not truncated)
        resp2 = self.manager.execute_query("SELECT num FROM numbers", limit=200)
        self.assertEqual(resp2.status, "success")
        self.assertEqual(len(resp2.rows), 120)
        self.assertFalse(resp2.truncated)

    def test_sqlalchemy_url_connection(self):
        # Connect in-memory SQLite through SQLAlchemy
        schema = self.manager.connect_url("sqlite:///:memory:")
        self.assertEqual(schema.status, "connected")
        self.assertEqual(schema.engine, "sqlite")

        # Create table via mutation mode
        self.manager.execute_query("CREATE TABLE tasks (id INT PRIMARY KEY, desc TEXT)", mode="mutation")
        self.manager.execute_query("INSERT INTO tasks VALUES (1, 'Finish Squad A')", mode="mutation")

        # Query back
        resp = self.manager.execute_query("SELECT desc FROM tasks WHERE id = 1", mode="read_only")
        self.assertEqual(resp.status, "success")
        self.assertEqual(resp.rows[0][0], "Finish Squad A")

    def test_undeclared_relational_link_detection(self):
        # Create SQLite with users and orders without foreign key constraint
        sqlite_path = os.path.join(self.temp_dir.name, "relational.sqlite")
        s = sqlite3.connect(sqlite_path)
        s.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT)")
        s.execute("CREATE TABLE orders (id INTEGER PRIMARY KEY, user_id INTEGER, amount REAL)")
        s.commit()
        s.close()

        schema = self.manager.connect_file(sqlite_path, "relational.sqlite")
        orders_table = next((t for t in schema.tables if t.name == "orders"), None)
        self.assertIsNotNone(orders_table)

        # Verify user_id link to users table was detected
        detected_links = [
            (fk.constrained_columns, fk.referred_table, fk.referred_columns)
            for fk in orders_table.foreign_keys
        ]
        self.assertIn((["user_id"], "users", ["id"]), detected_links)


if __name__ == "__main__":
    unittest.main()
