"""
Natural Language to SQL Translation Engine (Squad C - Agentic Intelligence).

Translates natural language questions into optimized SQL queries for DuckDB,
PostgreSQL, and SQLite dialects. Explains the query briefly and wraps executable
queries in ```sql:executable code blocks.
"""

import os
import re
from typing import List, Dict, Any, Optional, Union
from core.db_models import TableSchema, DatabaseSchemaResponse


# Destructive mutating keywords that must not be emitted in executable blocks when in read_only mode
MUTATING_KEYWORDS = {"DROP", "DELETE", "TRUNCATE", "ALTER", "UPDATE", "INSERT", "CREATE", "GRANT", "REVOKE"}


def parse_schema_context(
    table_context: Optional[Union[List[str], str, List[TableSchema], DatabaseSchemaResponse]]
) -> Dict[str, Dict[str, Any]]:
    """
    Parses various schema representations into a normalized dictionary:
    {
        "table_name": {
            "columns": [{"name": "id", "type": "INTEGER", "primary_key": True}, ...],
            "foreign_keys": [...]
        }
    }
    """
    schema_map: Dict[str, Dict[str, Any]] = {}

    if not table_context:
        # Attempt to introspect active DB manager if available
        try:
            from services.db_manager import db_manager
            if db_manager:
                active_schema = db_manager.get_schema()
                if active_schema and active_schema.tables:
                    for t in active_schema.tables:
                        schema_map[t.name.lower()] = {
                            "name": t.name,
                            "columns": [{"name": c.name, "type": c.data_type, "primary_key": c.primary_key} for c in t.columns],
                            "foreign_keys": [fk.dict() if hasattr(fk, 'dict') else fk for fk in t.foreign_keys]
                        }
                    return schema_map
        except Exception:
            pass
        return schema_map

    # If it's a DatabaseSchemaResponse
    if isinstance(table_context, DatabaseSchemaResponse):
        for t in table_context.tables:
            schema_map[t.name.lower()] = {
                "name": t.name,
                "columns": [{"name": c.name, "type": c.data_type, "primary_key": c.primary_key} for c in t.columns],
                "foreign_keys": [fk.dict() if hasattr(fk, 'dict') else fk for fk in t.foreign_keys]
            }
        return schema_map

    # If it's a list of TableSchema objects
    if isinstance(table_context, list) and table_context and isinstance(table_context[0], TableSchema):
        for t in table_context:
            schema_map[t.name.lower()] = {
                "name": t.name,
                "columns": [{"name": c.name, "type": c.data_type, "primary_key": c.primary_key} for c in t.columns],
                "foreign_keys": [fk.dict() if hasattr(fk, 'dict') else fk for fk in t.foreign_keys]
            }
        return schema_map

    # If it's a string, convert to single item list
    items = [table_context] if isinstance(table_context, str) else table_context

    for item in items:
        if not isinstance(item, str):
            continue
        text = item.strip()
        if not text:
            continue

        # Check for DDL pattern: CREATE TABLE table_name (col1 type, col2 type, ...)
        ddl_match = re.search(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([a-zA-Z0-9_]+)\s*\((.+?)\)", text, re.IGNORECASE | re.DOTALL)
        if ddl_match:
            tname = ddl_match.group(1).strip()
            cols_def = ddl_match.group(2)
            cols = []
            for col_part in cols_def.split(","):
                col_part = col_part.strip()
                if not col_part or col_part.upper().startswith(("PRIMARY KEY", "FOREIGN KEY", "CONSTRAINT")):
                    continue
                tokens = col_part.split()
                if tokens:
                    cname = tokens[0].strip('"`')
                    ctype = tokens[1] if len(tokens) > 1 else "VARCHAR"
                    is_pk = "PRIMARY" in col_part.upper()
                    cols.append({"name": cname, "type": ctype, "primary_key": is_pk})
            schema_map[tname.lower()] = {"name": tname, "columns": cols, "foreign_keys": []}
            continue

        # Check for descriptive format: Table name: col (type), col (type)
        desc_match = re.match(r"(?:Table\s+)?([a-zA-Z0-9_]+)\s*[:(](.+)", text, re.IGNORECASE)
        if desc_match:
            tname = desc_match.group(1).strip()
            cols_def = desc_match.group(2).rstrip(")")
            cols = []
            for part in cols_def.split(","):
                part = part.strip()
                if not part:
                    continue
                # col_name (type)
                m = re.match(r"([a-zA-Z0-9_]+)(?:\s*\(([^)]+)\))?", part)
                if m:
                    cname = m.group(1)
                    ctype = m.group(2) or "VARCHAR"
                    cols.append({"name": cname, "type": ctype, "primary_key": "id" in cname.lower()})
            schema_map[tname.lower()] = {"name": tname, "columns": cols, "foreign_keys": []}
            continue

        # Simple table name: "users" or "orders"
        clean_name = re.sub(r"[^a-zA-Z0-9_]", "", text)
        if clean_name:
            schema_map[clean_name.lower()] = {
                "name": clean_name,
                "columns": [],
                "foreign_keys": []
            }

    return schema_map


def _format_schema_for_prompt(schema_map: Dict[str, Dict[str, Any]]) -> str:
    """Formats schema map into human-readable and LLM-friendly schema descriptions."""
    if not schema_map:
        return "No explicit database schema provided (introspect from user query)."
    lines = []
    for tname, details in schema_map.items():
        cols = details.get("columns", [])
        if cols:
            col_strs = [f"{c['name']} ({c.get('type', 'TEXT')}{' PK' if c.get('primary_key') else ''})" for c in cols]
            lines.append(f"Table `{details['name']}`: {', '.join(col_strs)}")
        else:
            lines.append(f"Table `{details['name']}`")
    return "\n".join(lines)


def _check_safety(query: str, safety_mode: str) -> Optional[str]:
    """Returns an error message if the query violates the safety mode."""
    if safety_mode.lower() == "read_only":
        tokens = re.findall(r"\b([A-Z]+)\b", query.upper())
        for kw in MUTATING_KEYWORDS:
            if kw in tokens:
                return f"Mutating statement '{kw}' is blocked in read_only mode. Switch to mutation mode to execute DDL or updates."
    return None


def generate_offline_sql(
    prompt: str,
    schema_map: Dict[str, Dict[str, Any]],
    dialect: str = "duckdb",
    safety_mode: str = "read_only"
) -> str:
    """
    Deterministic rule-based SQL generator for offline execution or fallback.
    Analyzes user question tokens, identifies candidate tables and columns,
    and constructs optimized SQL for the given dialect.
    """
    p_lower = prompt.lower()
    dialect_lower = dialect.lower()

    # Determine candidate table
    target_table = None
    for t_key, t_info in schema_map.items():
        if t_key in p_lower or t_info["name"].lower() in p_lower:
            target_table = t_info["name"]
            break

    if not target_table:
        # Infer table name from schema or prompt keywords
        if schema_map:
            target_table = next(iter(schema_map.values()))["name"]
        else:
            # Common table guesses based on nouns in prompt
            words = re.findall(r"\b[a-zA-Z0-9_]{3,}\b", p_lower)
            for w in words:
                if w in {"user", "users", "customer", "customers", "order", "orders", "sale", "sales", "product", "products", "item", "items", "transaction", "transactions", "event", "events"}:
                    target_table = w
                    break
            if not target_table:
                target_table = "data_table"

    # Get known columns for this table
    known_cols = []
    t_key = target_table.lower()
    if t_key in schema_map and schema_map[t_key].get("columns"):
        known_cols = [c["name"] for c in schema_map[t_key]["columns"]]

    def find_col(candidates: List[str], fallback: str) -> str:
        for c in candidates:
            for kc in known_cols:
                if c in kc.lower():
                    return kc
        return fallback

    # Extract limit number if present
    limit = 50
    limit_match = re.search(r"\b(?:top|limit|first)\s+(\d+)\b", p_lower)
    if limit_match:
        limit = int(limit_match.group(1))

    # Pattern 0A: Shape, Dimensions, Row & Column count
    if any(k in p_lower for k in ["shape", "dimension", "dimensions", "how many rows", "row count", "how many records", "table size"]):
        col_count = len(known_cols) if known_cols else 0
        row_count = 0
        try:
            from services.db_manager import db_manager
            if db_manager:
                active_s = db_manager.get_schema()
                for t in active_s.tables:
                    if t.name.lower() == target_table.lower():
                        row_count = t.row_count
                        if not col_count:
                            col_count = len(t.columns)
                        break
        except Exception:
            pass

        if dialect_lower == "duckdb":
            query = (
                f"SELECT \n"
                f"    COUNT(*) AS total_rows,\n"
                f"    {col_count or '(SELECT COUNT(*) FROM information_schema.columns WHERE table_name = ' + repr(target_table) + ')'} AS total_columns\n"
                f"FROM {target_table};"
            )
        else:
            query = (
                f"SELECT \n"
                f"    (SELECT COUNT(*) FROM {target_table}) AS total_rows,\n"
                f"    COUNT(*) AS total_columns\n"
                f"FROM information_schema.columns\n"
                f"WHERE table_name = '{target_table}';"
            )

        if row_count and col_count:
            explanation = f"Dataset `{target_table}` has a shape of **{row_count:,} rows × {col_count} columns**."
        else:
            explanation = f"Calculates the exact shape (total rows and columns) for `{target_table}`."

    # Pattern 0B: Schema / Columns / Describe
    elif any(k in p_lower for k in ["describe", "columns in", "fields in", "schema for", "column names", "data types"]):
        if dialect_lower == "duckdb":
            query = f"DESCRIBE {target_table};"
        else:
            query = f"SELECT column_name, data_type, is_nullable\nFROM information_schema.columns\nWHERE table_name = '{target_table}';"
        explanation = f"Inspects all column definitions, data types, and nullability for `{target_table}`."

    # Pattern 1: Time-based grouping (Monthly / Daily / Trends / Timelines)
    elif any(k in p_lower for k in ["monthly", "by month", "trend", "daily", "by year", "timeline"]):
        date_col = find_col(["order_date", "created_at", "created", "timestamp", "date", "updated_at"], "created_at")
        if dialect_lower == "duckdb":
            time_expr = f"strftime({date_col}, '%Y-%m')"
        else:
            time_expr = f"DATE_TRUNC('month', {date_col})"
        query = (
            f"SELECT {time_expr} AS month_period, COUNT(*) AS record_count\n"
            f"FROM {target_table}\n"
            f"WHERE {date_col} IS NOT NULL\n"
            f"GROUP BY 1\n"
            f"ORDER BY month_period ASC\n"
            f"LIMIT {limit};"
        )
        explanation = f"Groups `{target_table}` records chronologically by month using `{date_col}` to analyze trends."

    # Pattern 2: Duplicates
    elif any(k in p_lower for k in ["duplicate", "duplicates", "repeated"]):
        dup_col = find_col(["email", "user_id", "name", "phone", "username", "slug"], "email")
        query = f"SELECT {dup_col}, COUNT(*) AS occurrence_count\nFROM {target_table}\nGROUP BY {dup_col}\nHAVING COUNT(*) > 1\nORDER BY occurrence_count DESC\nLIMIT {limit};"
        explanation = f"Finds records with duplicate `{dup_col}` values in `{target_table}` by grouping and filtering for counts greater than 1."

    # Pattern 3: Top N by metric / revenue / spending / balance / amount
    elif any(k in p_lower for k in ["top", "highest", "most", "largest", "best"]):
        metric_col = find_col(["total", "amount", "revenue", "spending", "balance", "price", "salary", "score"], "amount")
        id_col = find_col(["id", "name", "username", "customer_id", "user_id", "email"], "id")
        query = f"SELECT {id_col}, {metric_col}\nFROM {target_table}\nORDER BY {metric_col} DESC NULLS LAST\nLIMIT {limit};"
        explanation = f"Retrieves the top {limit} records from `{target_table}` sorted by `{metric_col}` in descending order."

    # Pattern 4: Bottom / lowest / least
    elif any(k in p_lower for k in ["lowest", "least", "bottom", "cheapest", "smallest"]):
        metric_col = find_col(["amount", "price", "spending", "balance", "salary", "score"], "amount")
        id_col = find_col(["id", "name", "username", "customer_id", "user_id"], "id")
        query = f"SELECT {id_col}, {metric_col}\nFROM {target_table}\nORDER BY {metric_col} ASC NULLS LAST\nLIMIT {limit};"
        explanation = f"Retrieves the {limit} records with the lowest `{metric_col}` from `{target_table}`."

    # Pattern 5: Missing / Null values
    elif any(k in p_lower for k in ["null", "missing", "unassigned", "blank", "empty"]):
        target_col = find_col(["email", "phone", "address", "status", "deleted_at"], "email")
        query = f"SELECT *\nFROM {target_table}\nWHERE {target_col} IS NULL\nLIMIT {limit};"
        explanation = f"Filters for rows in `{target_table}` where `{target_col}` is NULL."

    # Pattern 6: Count / How many / Volume
    elif any(k in p_lower for k in ["how many", "count", "number of rows", "total count", "volume"]):
        if any(k in p_lower for k in ["per", "group by", "by status", "by category", "by type"]):
            group_col = find_col(["status", "category", "type", "country", "state", "gender"], "status")
            query = f"SELECT {group_col}, COUNT(*) AS total_count\nFROM {target_table}\nGROUP BY {group_col}\nORDER BY total_count DESC\nLIMIT {limit};"
            explanation = f"Aggregates total record count grouped by `{group_col}` in `{target_table}`, ordered from highest to lowest frequency."
        else:
            query = f"SELECT COUNT(*) AS total_records\nFROM {target_table};"
            explanation = f"Computes the total row count for table `{target_table}`."

    # Pattern 7: Average / Mean calculation
    elif any(k in p_lower for k in ["average", "avg", "mean"]):
        metric_col = find_col(["price", "amount", "salary", "age", "score", "total"], "amount")
        query = f"SELECT AVG({metric_col}) AS avg_{metric_col}, MIN({metric_col}) AS min_{metric_col}, MAX({metric_col}) AS max_{metric_col}\nFROM {target_table};"
        explanation = f"Calculates statistical summary (average, minimum, and maximum) of `{metric_col}` in `{target_table}`."

    # Pattern 8: Recent / Latest records
    elif any(k in p_lower for k in ["recent", "latest", "newest"]):
        date_col = find_col(["created_at", "created", "timestamp", "date", "id"], "id")
        query = f"SELECT *\nFROM {target_table}\nORDER BY {date_col} DESC\nLIMIT {limit};"
        explanation = f"Fetches the most recent {limit} records from `{target_table}` ordered by `{date_col}` descending."

    # Default: Select sample / preview
    else:
        select_clause = "*"
        if known_cols:
            select_clause = ", ".join(known_cols[:8])
        query = f"SELECT {select_clause}\nFROM {target_table}\nLIMIT {limit};"
        explanation = f"Selects sample records from `{target_table}` with a limit of {limit} rows."

    # Format response
    safety_error = _check_safety(query, safety_mode)
    code_block_tag = "sql" if safety_error else "sql:executable"

    output_lines = [
        f"### Query Analysis ({dialect.upper()})",
        explanation,
        "",
        f"```{code_block_tag}",
        query,
        "```",
        "",
        "**Optimization Notes:**",
        f"- Target engine: `{dialect}`."
    ]

    if "LIMIT" in query.upper():
        output_lines.append(f"- Bounded by `LIMIT {limit}` to avoid unnecessary memory overhead on large tables.")

    output_lines.append(f"- Schema context utilized: `{target_table}`.")

    if safety_error:
        output_lines.append(f"\n> **Safety Notice:** {safety_error}")

    return "\n".join(output_lines)


def translate_nl_to_sql(
    prompt: str,
    table_context: Optional[Union[List[str], str, List[TableSchema], DatabaseSchemaResponse]] = None,
    dialect: str = "duckdb",
    safety_mode: str = "read_only"
) -> str:
    """
    Main entrypoint for NL-to-SQL translation.
    Attempts LLM translation if API key is present; otherwise falls back to deterministic rule-based generator.
    """
    schema_map = parse_schema_context(table_context)
    schema_desc = _format_schema_for_prompt(schema_map)

    # Check for available Cloud LLM
    openai_key = os.getenv("OPENAI_API_KEY", "")
    gemini_key = os.getenv("GEMINI_API_KEY", "")

    if openai_key and not openai_key.startswith("sk-placeholder"):
        try:
            import openai
            client = openai.OpenAI(api_key=openai_key)
            system_prompt = (
                f"You are an expert SQL engineer specializing in {dialect.upper()} and PostgreSQL.\n"
                f"Convert the user's natural language question into an optimized, robust SQL query.\n"
                f"Available Schema:\n{schema_desc}\n\n"
                f"Formatting Rules:\n"
                f"1. Explain the query briefly (1-2 sentences).\n"
                f"2. Wrap the SQL query inside ```sql:executable ... ``` code block.\n"
                f"3. If safety_mode is '{safety_mode}' and safety_mode is 'read_only', NEVER emit mutating statements (DROP, DELETE, TRUNCATE, ALTER, UPDATE, INSERT).\n"
                f"4. Add 2 short bullet points on query optimization or indexing at the end."
            )
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,
                max_tokens=600,
                timeout=15.0
            )
            llm_text = response.choices[0].message.content
            if "```sql:executable" in llm_text or "```sql" in llm_text:
                return llm_text
        except Exception:
            # Fall back smoothly to deterministic generator on any failure
            pass

    # Deterministic rule-based fallback
    return generate_offline_sql(prompt, schema_map, dialect=dialect, safety_mode=safety_mode)


class NL2SQLEngine:
    """Class wrapper providing conversational NL to SQL translation."""

    def __init__(self, dialect: str = "duckdb", safety_mode: str = "read_only"):
        self.dialect = dialect
        self.safety_mode = safety_mode

    def translate(
        self,
        prompt: str,
        table_context: Optional[Union[List[str], str, List[TableSchema], DatabaseSchemaResponse]] = None
    ) -> str:
        return translate_nl_to_sql(
            prompt=prompt,
            table_context=table_context,
            dialect=self.dialect,
            safety_mode=self.safety_mode
        )


def assemble_compact_schema_context(
    structure: Dict[str, Any],
    confirmed_glossary: Optional[Dict[str, str]] = None,
    focus_tables: Optional[List[str]] = None,
) -> str:
    """
    Builds token-efficient compact schema notation for prompt context:
    e.g. orders(id PK int, cust_id int -> customers.id, status int {1:new, 2:paid})
    """
    glossary = confirmed_glossary or {}
    tables = structure.get("tables", [])
    if focus_tables:
        focus_set = {t.lower() for t in focus_tables}
        tables = [t for t in tables if t["name"].lower() in focus_set]

    compact_lines = []
    for tbl in tables:
        t_name = tbl["name"]
        cols = tbl.get("columns", [])
        pks = set(tbl.get("primary_keys", []))

        # Build FK lookup for table
        fk_map = {}
        for fk in tbl.get("foreign_keys", []):
            ref_tbl = fk.get("referred_table")
            for c, r in zip(fk.get("constrained_columns", []), fk.get("referred_columns", [])):
                if ref_tbl:
                    fk_map[c] = f"-> {ref_tbl}.{r}"

        col_parts = []
        for c in cols:
            c_name = c["name"]
            c_type = c["type"].lower()
            flags = []
            if c_name in pks:
                flags.append("PK")
            if c_name in fk_map:
                flags.append(fk_map[c_name])

            # Check glossary mapping
            qual = f"{t_name}.{c_name}"
            if qual in glossary:
                flags.append(f"{{{glossary[qual]}}}")

            flag_str = f" {' '.join(flags)}" if flags else ""
            col_parts.append(f"{c_name} {c_type}{flag_str}")

        compact_lines.append(f"{t_name}({', '.join(col_parts)})")

    return "\n".join(compact_lines)
