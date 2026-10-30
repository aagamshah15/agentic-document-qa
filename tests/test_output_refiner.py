"""
Unit & Integration Tests for OutputRefiner (Multi-Pass Reasoning Engine).

Validates:
1. Pass 1: Schema Grounding & Self-Correction
   - Typos in table names auto-corrected (e.g. custmers -> customers)
   - Typos in column names auto-corrected (e.g. balnce -> balance, cust_name -> name)
   - Synonym mapping (e.g. amont -> amount, clnt_id -> customer_id, order_statuss -> order_status)
   - Dialect compliance (TOP -> LIMIT, date_trunc in sqlite, strftime in postgres, etc.)
2. Pass 2: Executive Polish & Cognitive Framing
   - Elimination of conversational filler ("Sure, here is...", "Certainly!...")
   - Direct punchy headline synthesis
   - Executable SQL code block formatting (```sql:executable)
   - Analytical Lens / Key Takeaways section synthesis
3. Pass 3: Interactive Next-Action Synthesis
   - Synthesis of 2-3 contextual next actions
   - Formatting in <!-- suggestions: ["...", "..."] -->
"""

import json
import re
import unittest

from core.db_models import ColumnInfo, DatabaseSchemaResponse, TableSchema
from services.output_refiner import OutputRefiner


class TestOutputRefiner(unittest.TestCase):

    def setUp(self):
        self.sample_context = [
            "customers: id (INT), name (VARCHAR), email (VARCHAR), status (VARCHAR), balance (FLOAT), created_at (TIMESTAMP)",
            "orders: id (INT), customer_id (INT), amount (FLOAT), order_status (VARCHAR), order_date (DATE)"
        ]

    def test_schema_grounding_table_typo_correction(self):
        raw_text = """
```sql
SELECT id, email, balance FROM custmers WHERE status = 'active';
```
"""
        refined = OutputRefiner.refine(
            raw_text=raw_text,
            schema=self.sample_context,
            dialect="duckdb",
            prompt="Find active customers"
        )
        self.assertIn("FROM customers", refined)
        self.assertNotIn("FROM custmers", refined)
        self.assertIn("```sql:executable", refined)

    def test_schema_grounding_column_typo_correction(self):
        raw_text = """
```sql
SELECT id, cust_name, amont FROM ordrs WHERE order_statuss = 'completed';
```
"""
        refined = OutputRefiner.refine(
            raw_text=raw_text,
            schema=self.sample_context,
            dialect="duckdb",
            prompt="Show completed orders"
        )
        # ordrs -> orders
        self.assertIn("FROM orders", refined)
        # amont -> amount
        self.assertIn("amount", refined)
        # order_statuss -> order_status
        self.assertIn("order_status", refined)
        self.assertNotIn("amont", refined)
        self.assertNotIn("order_statuss", refined)

    def test_schema_grounding_preserves_string_literals(self):
        # A literal matching a typo name must not be altered inside quotes
        raw_text = """
```sql
SELECT amont FROM ordrs WHERE order_statuss = 'amont';
```
"""
        refined = OutputRefiner.refine(
            raw_text=raw_text,
            schema=self.sample_context,
            dialect="duckdb"
        )
        self.assertIn("SELECT amount FROM orders WHERE order_status = 'amont'", refined)

    def test_dialect_compliance_sqlite(self):
        raw_text = """
```sql
SELECT date_trunc('month', order_date), SUM(amount) FROM orders GROUP BY 1;
```
"""
        refined = OutputRefiner.refine(
            raw_text=raw_text,
            schema=self.sample_context,
            dialect="sqlite"
        )
        self.assertIn("strftime('%Y-%m-01', order_date)", refined)

    def test_dialect_compliance_postgres(self):
        raw_text = """
```sql
SELECT strftime(order_date, '%Y-%m'), SUM(amount) FROM orders GROUP BY 1;
```
"""
        refined = OutputRefiner.refine(
            raw_text=raw_text,
            schema=self.sample_context,
            dialect="postgresql"
        )
        self.assertIn("to_char(order_date, 'YYYY-MM')", refined)

    def test_dialect_compliance_top_n(self):
        raw_text = """
```sql
SELECT TOP 5 id, amount FROM orders ORDER BY amount DESC;
```
"""
        refined = OutputRefiner.refine(
            raw_text=raw_text,
            schema=self.sample_context,
            dialect="duckdb"
        )
        self.assertIn("LIMIT 5", refined)
        self.assertNotIn("TOP 5", refined)

    def test_pass2_executive_filler_elimination(self):
        raw_text = """Sure! Here is the SQL query you asked for to view customer balances:
```sql
SELECT id, name, balance FROM customers ORDER BY balance DESC LIMIT 10;
```
This query selects customers and orders them by balance.
"""
        refined = OutputRefiner.refine(
            raw_text=raw_text,
            schema=self.sample_context,
            prompt="Show top 10 customers by balance"
        )
        self.assertNotIn("Sure! Here is the SQL query you asked for", refined)
        self.assertTrue(refined.startswith("### "))
        self.assertIn("```sql:executable", refined)
        self.assertIn("#### 🔍 Analytical Lens & Key Takeaways", refined)

    def test_pass3_suggestion_pills_synthesis(self):
        raw_text = """
```sql:executable
SELECT id, name, balance FROM customers ORDER BY balance DESC LIMIT 10;
```
"""
        refined = OutputRefiner.refine(
            raw_text=raw_text,
            schema=self.sample_context,
            prompt="Show top 10 customers by balance"
        )
        match = re.search(r"<!--\s*suggestions:\s*(\[[\s\S]*?\])\s*-->", refined)
        self.assertIsNotNone(match, "Suggestions comment tag must be present in output.")
        suggestions = json.loads(match.group(1))
        self.assertIsInstance(suggestions, list)
        self.assertTrue(2 <= len(suggestions) <= 3)
        # Should include relevant next actions like status filter or monthly breakdown
        self.assertTrue(any("status" in s or "month" in s or "orders" in s or "CSV" in s for s in suggestions))

    def test_read_only_safety_preserves_unexecutable_mutation(self):
        raw_text = """
```sql
DROP TABLE customers;
```
"""
        refined = OutputRefiner.refine(
            raw_text=raw_text,
            schema=self.sample_context,
            safety_mode="read_only"
        )
        # Mutating query in read_only mode must not become executable
        self.assertIn("```sql\n", refined)
        self.assertNotIn("```sql:executable", refined)

    def test_idempotent_refinement(self):
        raw_text = """### 📊 Top-Tier Distribution Analysis

```sql:executable
SELECT id, name, balance FROM customers ORDER BY balance DESC LIMIT 10;
```

#### 🔍 Analytical Lens & Key Takeaways
- **Pareto Concentration**: Evaluates high-impact records.

<!-- suggestions: ["Filter by status = 'completed'", "Break down by month", "Export cleaned view as CSV"] -->
"""
        first_pass = OutputRefiner.refine(raw_text=raw_text, schema=self.sample_context)
        second_pass = OutputRefiner.refine(raw_text=first_pass, schema=self.sample_context)
        self.assertEqual(first_pass, second_pass)

    def test_cleaner_intent_suggestions(self):
        raw_text = """### Data Hygiene & Normalization Recipe
```sql:executable
SELECT DISTINCT TRIM(email) AS email FROM customers;
```
"""
        refined = OutputRefiner.refine(
            raw_text=raw_text,
            schema=self.sample_context,
            prompt="Clean customer records and whitespace"
        )
        match = re.search(r"<!--\s*suggestions:\s*(\[[\s\S]*?\])\s*-->", refined)
        self.assertIsNotNone(match)
        suggestions = json.loads(match.group(1))
        self.assertIn("Preview deduplicated rows", suggestions)
        self.assertIn("Export cleaned view as CSV", suggestions)

    def test_migration_intent_suggestions(self):
        raw_text = """### Schema Migration Plan
```sql
ALTER TABLE customers ADD COLUMN email_verified BOOLEAN DEFAULT false;
```
"""
        refined = OutputRefiner.refine(
            raw_text=raw_text,
            schema=self.sample_context,
            prompt="Alter table customers add column email_verified"
        )
        match = re.search(r"<!--\s*suggestions:\s*(\[[\s\S]*?\])\s*-->", refined)
        self.assertIsNotNone(match)
        suggestions = json.loads(match.group(1))
        self.assertIn("Validate rollback SQL DOWN script", suggestions)


class TestDataAgentRefinementIntegration(unittest.IsolatedAsyncioTestCase):

    async def test_streamed_agent_response_contains_refinement_pipeline(self):
        from core.db_models import AgentPromptRequest
        from services.data_agent import stream_data_agent_response

        req = AgentPromptRequest(
            prompt="Show top 5 customers with highest balance",
            table_context=[
                "customers: id (INT), name (VARCHAR), email (VARCHAR), status (VARCHAR), balance (FLOAT), created_at (TIMESTAMP)"
            ],
            model="gemini-1.5-flash",
            safety_mode="read_only"
        )

        tokens = []
        async for sse_chunk in stream_data_agent_response(req):
            if sse_chunk.startswith("data: "):
                payload_str = sse_chunk[6:].strip()
                if payload_str != "[DONE]":
                    data = json.loads(payload_str)
                    if "token" in data:
                        tokens.append(data["token"])

        full_output = "".join(tokens)
        # Verify Pass 1/2: Executive Polish & Executable wrap
        self.assertIn("```sql:executable", full_output)
        self.assertIn("customers", full_output)
        self.assertIn("Analytical Lens", full_output)

        # Verify Pass 3: Suggestion chips comment tag
        self.assertIn("<!-- suggestions:", full_output)
        match = re.search(r"<!--\s*suggestions:\s*(\[[\s\S]*?\])\s*-->", full_output)
        self.assertIsNotNone(match)
        suggestions = json.loads(match.group(1))
        self.assertTrue(len(suggestions) >= 2)


if __name__ == "__main__":
    unittest.main()
