"""
Unit & Integration Tests for Squad C (Agentic Intelligence and Synthesis).

Validates:
1. services/nl_sql.py: Natural Language to SQL translation & executable block formatting.
2. services/data_cleaner.py: Automated SQL cleanup recipes (trimming, deduplication, casing, imputation).
3. services/migration_architect.py: Schema migration DDL, rollback logic, Alembic code, safety warnings.
4. services/data_agent.py: stream_data_agent_response orchestrator yielding valid SSE chunks.
"""

import asyncio
import json
import unittest

from core.db_models import AgentPromptRequest
from services.nl_sql import translate_nl_to_sql, NL2SQLEngine, parse_schema_context
from services.data_cleaner import clean_table_data, generate_cleaning_recipe, DataCleaner
from services.migration_architect import generate_migration_plan, MigrationArchitect
from services.data_agent import (
    classify_user_intent,
    generate_deterministic_response,
    stream_data_agent_response,
)


class TestSquadCDataAgent(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.sample_context = [
            "customers: id (INT), name (VARCHAR), email (VARCHAR), status (VARCHAR), balance (FLOAT), created_at (TIMESTAMP)",
            "orders: id (INT), customer_id (INT), amount (FLOAT), order_status (VARCHAR), order_date (DATE)"
        ]

    def test_schema_context_parsing(self):
        schema = parse_schema_context(self.sample_context)
        self.assertIn("customers", schema)
        self.assertIn("orders", schema)
        col_names = [c["name"] for c in schema["customers"]["columns"]]
        self.assertIn("email", col_names)
        self.assertIn("balance", col_names)

    def test_nl_sql_top_n(self):
        res = translate_nl_to_sql(
            prompt="Show top 10 customers by balance",
            table_context=self.sample_context,
            dialect="duckdb"
        )
        self.assertIn("```sql:executable", res)
        self.assertIn("customers", res)
        self.assertIn("ORDER BY", res)
        self.assertIn("10", res)

    def test_nl_sql_monthly_grouping(self):
        res = translate_nl_to_sql(
            prompt="Show monthly order count for orders",
            table_context=self.sample_context,
            dialect="duckdb"
        )
        self.assertIn("```sql:executable", res)
        self.assertIn("strftime", res)
        self.assertIn("GROUP BY", res)

    def test_nl_sql_read_only_safety(self):
        res = translate_nl_to_sql(
            prompt="How many orders are in the database?",
            table_context=self.sample_context,
            dialect="duckdb",
            safety_mode="read_only"
        )
        self.assertIn("```sql:executable", res)
        self.assertIn("COUNT(*)", res)

    def test_data_cleaner_recipe(self):
        res = clean_table_data(
            prompt="Clean customer names, normalize email casing, and fix null balances",
            table_context=self.sample_context,
            dialect="duckdb"
        )
        self.assertIn("### Data Hygiene & Normalization Recipe", res)
        self.assertIn("```sql:executable", res)
        self.assertIn("LOWER(TRIM(email))", res)
        self.assertIn("ROW_NUMBER() OVER", res)
        self.assertIn("COALESCE(balance, 0.0)", res)

    def test_data_cleaner_in_place_warning(self):
        res = clean_table_data(
            prompt="Permanently delete duplicate customers in place",
            table_context=self.sample_context,
            dialect="duckdb",
            safety_mode="read_only"
        )
        self.assertIn("In-Place Mutation Alert", res)
        self.assertIn("DELETE FROM customers", res)
        # Should NOT be sql:executable in read_only mode for safety
        self.assertIn("```sql\n", res)

    def test_migration_add_column(self):
        res = generate_migration_plan(
            prompt="Add email_verified boolean column with default false to customers",
            table_context=self.sample_context,
            dialect="postgresql"
        )
        self.assertIn("ALTER TABLE customers", res)
        self.assertIn("ADD COLUMN email_verified BOOLEAN", res)
        self.assertIn("DROP COLUMN IF EXISTS email_verified", res)
        self.assertIn("op.add_column", res)
        self.assertIn("op.drop_column", res)
        self.assertIn("def upgrade()", res)
        self.assertIn("def downgrade()", res)

    def test_migration_drop_column_critical_warning(self):
        res = generate_migration_plan(
            prompt="Drop column deprecated_notes from customers",
            table_context=self.sample_context,
            dialect="postgresql"
        )
        self.assertIn("CRITICAL", res)
        self.assertIn("Data Loss Hazard", res)
        self.assertIn("DROP COLUMN IF EXISTS deprecated_notes", res)

    def test_intent_classification(self):
        self.assertEqual(classify_user_intent("Clean duplicate emails and trim names"), "cleaner")
        self.assertEqual(classify_user_intent("Add column is_verified to users"), "migration")
        self.assertEqual(classify_user_intent("Show top 5 customers with highest revenue"), "nl_sql")

    async def test_stream_data_agent_response_sse(self):
        req = AgentPromptRequest(
            prompt="Show top 5 customers by balance",
            table_context=self.sample_context,
            model="gemini-1.5-flash",
            safety_mode="read_only"
        )

        chunks = []
        tokens = []
        async for sse_chunk in stream_data_agent_response(req):
            chunks.append(sse_chunk)
            self.assertTrue(sse_chunk.startswith("data: "))
            self.assertTrue(sse_chunk.endswith("\n\n"))
            payload_str = sse_chunk[6:].strip()
            if payload_str == "[DONE]":
                continue
            data = json.loads(payload_str)
            if "token" in data:
                tokens.append(data["token"])

        self.assertGreater(len(chunks), 5)
        full_text = "".join(tokens)
        self.assertIn("```sql:executable", full_text)
        self.assertIn("customers", full_text)
        self.assertIn("data: [DONE]\n\n", chunks)
        print("\n[TEST PASS] stream_data_agent_response successfully yielded", len(chunks), "SSE chunks.")

    async def test_stream_data_agent_cleaner_route(self):
        req = AgentPromptRequest(
            prompt="Clean customer records and deduplicate",
            table_context=self.sample_context,
            model="gemini-1.5-flash",
            safety_mode="read_only"
        )
        tokens = []
        async for sse_chunk in stream_data_agent_response(req):
            payload_str = sse_chunk[6:].strip()
            if payload_str != "[DONE]":
                data = json.loads(payload_str)
                if "token" in data:
                    tokens.append(data["token"])

        full_text = "".join(tokens)
        self.assertIn("Data Hygiene", full_text)
        self.assertIn("```sql:executable", full_text)

    async def test_stream_data_agent_migration_route(self):
        req = AgentPromptRequest(
            prompt="Alter table orders add column is_paid boolean default false",
            table_context=self.sample_context,
            model="gemini-1.5-flash",
            safety_mode="read_only"
        )
        tokens = []
        async for sse_chunk in stream_data_agent_response(req):
            payload_str = sse_chunk[6:].strip()
            if payload_str != "[DONE]":
                data = json.loads(payload_str)
                if "token" in data:
                    tokens.append(data["token"])

        full_text = "".join(tokens)
        self.assertIn("Schema Migration", full_text)
        self.assertIn("ALTER TABLE orders", full_text)
        self.assertIn("op.add_column", full_text)


if __name__ == "__main__":
    unittest.main()
