"""
Automated Data Cleaner Service (Squad C - Agentic Intelligence).

Generates standardized SQL cleanup and normalization scripts:
- Whitespace trimming and multi-space collapsing
- Duplicate removal via Window Functions (ROW_NUMBER CTE) or in-place DELETE
- Casing fixes (LOWER for emails, UPPER for codes/status, INITCAP for names)
- Null imputation (sensible defaults for numeric, categorical, and datetime columns)
- Safe non-destructive views (CTAS) vs in-place mutations with safety warnings.
"""

import os
import re
from typing import List, Dict, Any, Optional, Union
from core.db_models import TableSchema, ColumnInfo, AnomalyReport, ColumnProfile
from services.nl_sql import parse_schema_context


def generate_cleaning_recipe(
    table_name: str,
    columns: Optional[List[Dict[str, Any]]] = None,
    anomalies: Optional[List[Union[AnomalyReport, Dict[str, Any]]]] = None,
    dialect: str = "duckdb",
    in_place: bool = False,
    prompt: Optional[str] = None,
    safety_mode: str = "read_only"
) -> str:
    """
    Constructs a comprehensive, dialect-optimized SQL data cleaning recipe.
    """
    clean_table = table_name.strip()
    dialect_lower = dialect.lower()

    # Normalize columns list
    cols = columns or []
    if not cols:
        # Defaults if no column metadata provided
        cols = [
            {"name": "id", "type": "INTEGER", "primary_key": True},
            {"name": "name", "type": "VARCHAR"},
            {"name": "email", "type": "VARCHAR"},
            {"name": "status", "type": "VARCHAR"},
            {"name": "amount", "type": "FLOAT"},
            {"name": "created_at", "type": "TIMESTAMP"},
        ]

    # Detect key columns
    pk_col = "id"
    email_col = None
    name_col = None
    status_col = None
    numeric_cols = []
    string_cols = []
    date_cols = []

    for c in cols:
        cname = c["name"]
        ctype = str(c.get("type", "")).upper()
        clower = cname.lower()

        if c.get("primary_key") or clower in ("id", f"{clean_table}_id", "uuid", "pk"):
            pk_col = cname

        if "email" in clower:
            email_col = cname
            string_cols.append(cname)
        elif any(k in clower for k in ["name", "title", "full_name"]):
            name_col = cname
            string_cols.append(cname)
        elif any(k in clower for k in ["status", "state", "type", "country", "currency", "code"]):
            status_col = cname
            string_cols.append(cname)
        elif any(k in ctype for k in ["INT", "FLOAT", "NUMERIC", "DECIMAL", "REAL", "DOUBLE"]) or any(k in clower for k in ["amount", "total", "price", "balance", "cost", "score", "age"]):
            numeric_cols.append(cname)
        elif any(k in ctype for k in ["TIME", "DATE"]) or any(k in clower for k in ["date", "created", "updated", "time"]):
            date_cols.append(cname)
        else:
            string_cols.append(cname)

    # Key for deduplication
    dedup_key = email_col or pk_col or (cols[0]["name"] if cols else "id")
    order_key = pk_col if pk_col else (date_cols[0] if date_cols else dedup_key)

    # 1. Build Cleaning Transformations for SELECT expressions
    transform_exprs = []
    for c in cols:
        cname = c["name"]
        ctype = str(c.get("type", "")).upper()
        clower = cname.lower()

        if cname == pk_col:
            transform_exprs.append(f"{cname}")
        elif cname == email_col:
            # Lowercase and whitespace trim email
            transform_exprs.append(f"LOWER(TRIM({cname})) AS {cname}")
        elif cname == name_col:
            # Trim and collapse extra internal whitespace
            if dialect_lower == "duckdb":
                transform_exprs.append(f"TRIM(REGEXP_REPLACE({cname}, '\\s+', ' ')) AS {cname}")
            else:
                transform_exprs.append(f"TRIM(REGEXP_REPLACE({cname}, '\\s+', ' ', 'g')) AS {cname}")
        elif cname == status_col:
            # Uppercase status and impute UNKNOWN if null
            transform_exprs.append(f"COALESCE(UPPER(TRIM({cname})), 'UNKNOWN') AS {cname}")
        elif cname in numeric_cols:
            # Impute 0 or 0.0 for numeric nulls
            default_num = "0.0" if any(k in ctype for k in ["FLOAT", "NUMERIC", "DECIMAL", "REAL"]) else "0"
            transform_exprs.append(f"COALESCE({cname}, {default_num}) AS {cname}")
        elif cname in date_cols:
            transform_exprs.append(f"{cname}")
        elif cname in string_cols:
            # General string trimming and null imputation
            transform_exprs.append(f"COALESCE(TRIM({cname}), '') AS {cname}")
        else:
            transform_exprs.append(f"{cname}")

    proj_sql = ",\n    ".join(transform_exprs)

    # 2. Non-Destructive Cleaning Query (Safe View / CTAS)
    cte_query = (
        f"CREATE OR REPLACE VIEW cleaned_{clean_table} AS\n"
        f"WITH deduplicated AS (\n"
        f"    SELECT *,\n"
        f"           ROW_NUMBER() OVER (\n"
        f"               PARTITION BY {dedup_key}\n"
        f"               ORDER BY {order_key} DESC\n"
        f"           ) AS _row_num\n"
        f"    FROM {clean_table}\n"
        f")\n"
        f"SELECT\n"
        f"    {proj_sql}\n"
        f"FROM deduplicated\n"
        f"WHERE _row_num = 1;"
    )

    # 3. In-Place Mutation Alternative (for users explicitly needing UPDATE/DELETE)
    in_place_query = (
        f"-- 1. Remove duplicate rows keeping latest {order_key}\n"
        f"DELETE FROM {clean_table}\n"
        f"WHERE {pk_col} NOT IN (\n"
        f"    SELECT MIN({pk_col})\n"
        f"    FROM {clean_table}\n"
        f"    GROUP BY {dedup_key}\n"
        f");\n\n"
        f"-- 2. Trim whitespace and standardize casing\n"
        f"UPDATE {clean_table}\n"
        f"SET "
    )
    updates = []
    if email_col:
        updates.append(f"{email_col} = LOWER(TRIM({email_col}))")
    if name_col:
        updates.append(f"{name_col} = TRIM({name_col})")
    if status_col:
        updates.append(f"{status_col} = COALESCE(UPPER(TRIM({status_col})), 'UNKNOWN')")
    for nc in numeric_cols[:2]:
        updates.append(f"{nc} = COALESCE({nc}, 0)")

    in_place_query += ",\n    ".join(updates or [f"{pk_col} = {pk_col}"]) + ";"

    # Output generation
    output = []
    output.append(f"### Data Hygiene & Normalization Recipe for `{clean_table}`")
    output.append(
        f"This recipe standardizes `{clean_table}` across 4 critical data quality dimensions:\n"
        f"1. **Deduplication**: Eliminates duplicate entries partitioned by `{dedup_key}`.\n"
        f"2. **Whitespace Trimming**: Strips leading/trailing spaces and collapses redundant whitespace.\n"
        f"3. **Casing Standardization**: Enforces lowercase on email addresses and uppercase on categorical codes.\n"
        f"4. **Null Imputation**: Replaces null metrics with `0` and missing categories with `'UNKNOWN'`."
    )
    output.append("")

    if in_place:
        output.append("> [!WARNING]\n> **In-Place Mutation Alert**: Running destructive `DELETE` and `UPDATE` queries modifies source data directly. Always verify with a backup before running.")
        output.append("")
        tag = "sql" if safety_mode == "read_only" else "sql:executable"
        output.append(f"```{tag}\n{in_place_query}\n```")
    else:
        output.append("#### Non-Destructive Cleaned View (Recommended)")
        output.append("Creates a clean, normalized abstraction without risking permanent data loss on the source table.")
        output.append("")
        output.append(f"```sql:executable\n{cte_query}\n```")

    output.append("")
    output.append("#### Verification & Post-Cleaning Validation")
    output.append("Execute this validation query to confirm data cleanliness:")
    val_sql = (
        f"SELECT\n"
        f"    COUNT(*) AS total_clean_rows,\n"
        f"    COUNT(*) - COUNT(DISTINCT {dedup_key}) AS remaining_duplicates\n"
        f"FROM cleaned_{clean_table};"
    )
    output.append(f"```sql:executable\n{val_sql}\n```")

    return "\n".join(output)


def clean_table_data(
    prompt: str,
    table_context: Optional[Union[List[str], str, List[TableSchema]]] = None,
    dialect: str = "duckdb",
    safety_mode: str = "read_only"
) -> str:
    """
    Main entrypoint for autonomous data cleaning requests.
    Inspects schema context, detects target table, and produces a tailored cleaning recipe.
    """
    schema_map = parse_schema_context(table_context)
    p_lower = prompt.lower()

    # Identify target table
    target_table = None
    for t_key, t_info in schema_map.items():
        if t_key in p_lower or t_info["name"].lower() in p_lower:
            target_table = t_info["name"]
            break

    if not target_table:
        if schema_map:
            target_table = next(iter(schema_map.values()))["name"]
        else:
            words = re.findall(r"\b[a-zA-Z0-9_]{3,}\b", p_lower)
            for w in words:
                if w in {"user", "users", "customer", "customers", "order", "orders", "product", "products", "transaction", "transactions"}:
                    target_table = w
                    break
            if not target_table:
                target_table = "users"

    cols = []
    t_key = target_table.lower()
    if t_key in schema_map and schema_map[t_key].get("columns"):
        cols = schema_map[t_key]["columns"]

    # Check if user requested in-place mutation
    in_place = any(k in p_lower for k in ["in place", "in-place", "permanently", "direct update", "delete from"])

    return generate_cleaning_recipe(
        table_name=target_table,
        columns=cols,
        dialect=dialect,
        in_place=in_place,
        prompt=prompt,
        safety_mode=safety_mode
    )


class DataCleaner:
    """Class wrapper for automated data cleaning."""

    def __init__(self, dialect: str = "duckdb", safety_mode: str = "read_only"):
        self.dialect = dialect
        self.safety_mode = safety_mode

    def generate_recipe(
        self,
        table_name: str,
        columns: Optional[List[Dict[str, Any]]] = None,
        anomalies: Optional[List[AnomalyReport]] = None,
        in_place: bool = False
    ) -> str:
        return generate_cleaning_recipe(
            table_name=table_name,
            columns=columns,
            anomalies=anomalies,
            dialect=self.dialect,
            in_place=in_place,
            safety_mode=self.safety_mode
        )
