"""
Schema Migration Architect (Squad C - Agentic Intelligence).

Generates comprehensive, production-grade schema migration artifacts:
1. SQL Migration DDL (Forward UP migration)
2. SQL Rollback DDL (DOWN migration)
3. Alembic Python migration script (with upgrade and downgrade functions)
4. Safety impact assessment, lock risk analysis, and pre-flight checklists.
"""

import os
import re
import datetime
from typing import List, Dict, Any, Optional, Union
from core.db_models import TableSchema
from services.nl_sql import parse_schema_context


def _infer_sql_and_sa_type(type_str: str) -> tuple[str, str]:
    """
    Maps an informal type string to SQL DDL and SQLAlchemy types.
    Returns: (sql_ddl_type, sqlalchemy_type_code)
    """
    t = type_str.upper()
    if any(k in t for k in ["BOOL"]):
        return "BOOLEAN", "sa.Boolean()"
    elif any(k in t for k in ["BIGINT"]):
        return "BIGINT", "sa.BigInteger()"
    elif any(k in t for k in ["INT", "INTEGER", "SERIAL"]):
        return "INTEGER", "sa.Integer()"
    elif any(k in t for k in ["NUMERIC", "DECIMAL"]):
        m = re.search(r"\((\d+)\s*,\s*(\d+)\)", t)
        if m:
            p, s = m.group(1), m.group(2)
            return f"NUMERIC({p}, {s})", f"sa.Numeric(precision={p}, scale={s})"
        return "NUMERIC(10, 2)", "sa.Numeric(10, 2)"
    elif any(k in t for k in ["FLOAT", "REAL", "DOUBLE"]):
        return "DOUBLE PRECISION", "sa.Float()"
    elif any(k in t for k in ["TIMESTAMP", "DATETIME"]):
        return "TIMESTAMP WITH TIME ZONE", "sa.DateTime(timezone=True)"
    elif any(k in t for k in ["DATE"]):
        return "DATE", "sa.Date()"
    elif any(k in t for k in ["JSONB"]):
        return "JSONB", "sa.JSON()"
    elif any(k in t for k in ["JSON"]):
        return "JSON", "sa.JSON()"
    elif any(k in t for k in ["TEXT"]):
        return "TEXT", "sa.Text()"
    elif any(k in t for k in ["VARCHAR", "STRING", "CHAR"]):
        m = re.search(r"\((\d+)\)", t)
        length = m.group(1) if m else "255"
        return f"VARCHAR({length})", f"sa.String(length={length})"
    elif any(k in t for k in ["UUID"]):
        return "UUID", "sa.UUID()"
    else:
        return "VARCHAR(255)", "sa.String(255)"


def generate_migration_plan(
    prompt: str,
    table_context: Optional[Union[List[str], str, List[TableSchema]]] = None,
    dialect: str = "postgresql",
    safety_mode: str = "read_only"
) -> str:
    """
    Translates a migration request into DDL, Alembic Python scripts, and rollback logic.
    """
    schema_map = parse_schema_context(table_context)
    p_lower = prompt.lower()
    dialect_lower = dialect.lower()

    # 1. Detect target table
    target_table = None
    for t_key, t_info in schema_map.items():
        if t_key in p_lower or t_info["name"].lower() in p_lower:
            target_table = t_info["name"]
            break

    if not target_table:
        # Match table name following "in table", "to table", "from table", "on table", "table <name>"
        t_match = re.search(r"\b(?:in|to|from|on|table)\s+([a-zA-Z0-9_]+)\b", prompt, re.IGNORECASE)
        if t_match and t_match.group(1).lower() not in {"a", "the", "column", "table", "index", "alembic"}:
            target_table = t_match.group(1)
        elif schema_map:
            target_table = next(iter(schema_map.values()))["name"]
        else:
            target_table = "users"

    clean_table = target_table.strip('"` ')

    # 2. Detect Operation Intent
    # Operation A: DROP COLUMN
    if any(k in p_lower for k in ["drop column", "remove column", "delete column"]):
        col_match = re.search(r"\b(?:drop|remove|delete)\s+column\s+([a-zA-Z0-9_]+)\b", prompt, re.IGNORECASE)
        col_name = col_match.group(1) if col_match else "deprecated_col"
        
        # Risk analysis
        risk_level = "CRITICAL"
        risk_desc = (
            f"**Data Loss Hazard**: Dropping column `{col_name}` from `{clean_table}` is irreversible. "
            f"All existing values in `{col_name}` will be permanently erased. Active ORMs and client queries "
            f"referencing `{col_name}` will encounter immediate runtime errors."
        )

        up_ddl = f"ALTER TABLE {clean_table}\nDROP COLUMN IF EXISTS {col_name};"
        down_ddl = (
            f"-- Rollback DDL (Warning: Data previously in {col_name} cannot be recovered)\n"
            f"ALTER TABLE {clean_table}\nADD COLUMN {col_name} VARCHAR(255);"
        )

        alembic_code = (
            f"def upgrade() -> None:\n"
            f"    # CRITICAL: Drops column {col_name}\n"
            f"    op.drop_column('{clean_table}', '{col_name}')\n\n"
            f"def downgrade() -> None:\n"
            f"    # Rollback schema (Note: Data loss is irreversible)\n"
            f"    op.add_column('{clean_table}', sa.Column('{col_name}', sa.String(255), nullable=True))"
        )
        migration_title = f"Drop column `{col_name}` from `{clean_table}`"

    # Operation B: RENAME COLUMN
    elif any(k in p_lower for k in ["rename column", "rename"]):
        m = re.search(r"\brename(?:\s+column)?\s+([a-zA-Z0-9_]+)\s+to\s+([a-zA-Z0-9_]+)\b", prompt, re.IGNORECASE)
        if m:
            old_col, new_col = m.group(1), m.group(2)
        else:
            old_col, new_col = "old_column", "new_column"

        risk_level = "HIGH"
        risk_desc = (
            f"**Downtime / Interface Risk**: Renaming `{old_col}` to `{new_col}` causes breaking changes "
            f"for all running application code, API handlers, and reporting queries that reference `{old_col}`. "
            f"For zero-downtime architectures, use a 3-phase rollout: (1) Add new column, (2) Dual-write, (3) Deprecate old."
        )

        up_ddl = f"ALTER TABLE {clean_table}\nRENAME COLUMN {old_col} TO {new_col};"
        down_ddl = f"ALTER TABLE {clean_table}\nRENAME COLUMN {new_col} TO {old_col};"

        alembic_code = (
            f"def upgrade() -> None:\n"
            f"    op.alter_column('{clean_table}', '{old_col}', new_column_name='{new_col}')\n\n"
            f"def downgrade() -> None:\n"
            f"    op.alter_column('{clean_table}', '{new_col}', new_column_name='{old_col}')"
        )
        migration_title = f"Rename `{old_col}` to `{new_col}` on `{clean_table}`"

    # Operation C: CHANGE / ALTER TYPE
    elif any(k in p_lower for k in ["change type", "alter type", "modify column", "convert column"]):
        m = re.search(r"\b(?:change|alter|modify)\s+(?:column\s+)?([a-zA-Z0-9_]+)\s+(?:type\s+)?(?:to\s+)?([a-zA-Z0-9_(),\s]+)", prompt, re.IGNORECASE)
        col_name = m.group(1) if m else "target_col"
        raw_type = m.group(2) if m else "VARCHAR(255)"
        sql_type, sa_type = _infer_sql_and_sa_type(raw_type)

        risk_level = "HIGH"
        risk_desc = (
            f"**Table Lock & Type Cast Hazard**: Altering `{col_name}` to `{sql_type}` requires an `ACCESS EXCLUSIVE` lock "
            f"on table `{clean_table}`, blocking read and write operations while table rows are rewritten. If any existing value "
            f"cannot be cast to `{sql_type}`, the entire migration will abort."
        )

        if dialect_lower == "duckdb":
            up_ddl = f"ALTER TABLE {clean_table}\nALTER COLUMN {col_name} TYPE {sql_type};"
            down_ddl = f"ALTER TABLE {clean_table}\nALTER COLUMN {col_name} TYPE VARCHAR(255);"
        else:
            up_ddl = f"ALTER TABLE {clean_table}\nALTER COLUMN {col_name} TYPE {sql_type}\nUSING {col_name}::{sql_type};"
            down_ddl = f"ALTER TABLE {clean_table}\nALTER COLUMN {col_name} TYPE VARCHAR(255)\nUSING {col_name}::VARCHAR;"

        alembic_code = (
            f"def upgrade() -> None:\n"
            f"    op.alter_column('{clean_table}', '{col_name}', type_={sa_type}, postgresql_using='{col_name}::{sql_type}')\n\n"
            f"def downgrade() -> None:\n"
            f"    op.alter_column('{clean_table}', '{col_name}', type_=sa.String(255), postgresql_using='{col_name}::varchar')"
        )
        migration_title = f"Alter `{col_name}` type to `{sql_type}` on `{clean_table}`"

    # Operation D: ADD INDEX
    elif any(k in p_lower for k in ["add index", "create index", "index on"]):
        m = re.search(r"\b(?:add\s+index|create\s+index|index\s+on)\s+(?:on\s+)?(?:[a-zA-Z0-9_]+\s+)?\(?([a-zA-Z0-9_,\s]+)\)?", prompt, re.IGNORECASE)
        col_name = m.group(1).strip() if m else "created_at"
        col_name = col_name.split()[0] if col_name else "created_at"
        idx_name = f"idx_{clean_table}_{col_name}"

        risk_level = "LOW"
        risk_desc = (
            f"**Index Creation**: Indexing `{clean_table}({col_name})` accelerates search and filter queries. "
            f"In PostgreSQL production environments, use `CONCURRENTLY` to build the index without blocking writes."
        )

        if dialect_lower == "postgresql":
            up_ddl = f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {idx_name}\nON {clean_table} ({col_name});"
            down_ddl = f"DROP INDEX CONCURRENTLY IF EXISTS {idx_name};"
        else:
            up_ddl = f"CREATE INDEX IF NOT EXISTS {idx_name}\nON {clean_table} ({col_name});"
            down_ddl = f"DROP INDEX IF EXISTS {idx_name};"

        alembic_code = (
            f"def upgrade() -> None:\n"
            f"    op.create_index('{idx_name}', '{clean_table}', ['{col_name}'], unique=False)\n\n"
            f"def downgrade() -> None:\n"
            f"    op.drop_index('{idx_name}', table_name='{clean_table}')"
        )
        migration_title = f"Create index on `{clean_table}({col_name})`"

    # Operation E: ADD COLUMN (Default / Most Common)
    else:
        # Extract column name and type
        m = re.search(r"\badd\s+(?:column\s+)?([a-zA-Z0-9_]+)\s*([a-zA-Z0-9_(),\s]*)", prompt, re.IGNORECASE)
        col_name = m.group(1) if m else "new_column"
        raw_type = m.group(2).strip() if m else "VARCHAR"
        
        # Check if type is present or infer
        if not raw_type or raw_type.lower() in {"to", "in", "with", "column"}:
            if "boolean" in p_lower or "bool" in p_lower:
                raw_type = "BOOLEAN"
            elif "int" in p_lower or "integer" in p_lower or "count" in p_lower:
                raw_type = "INTEGER"
            elif "timestamp" in p_lower or "date" in p_lower:
                raw_type = "TIMESTAMP"
            elif "float" in p_lower or "price" in p_lower:
                raw_type = "FLOAT"
            else:
                raw_type = "VARCHAR(255)"

        sql_type, sa_type = _infer_sql_and_sa_type(raw_type)

        # Detect default value
        default_clause = ""
        sa_default = ""
        def_match = re.search(r"\bdefault\s+([a-zA-Z0-9_'\"]+)", prompt, re.IGNORECASE)
        if def_match:
            dval = def_match.group(1)
            default_clause = f" DEFAULT {dval}"
            sa_default = f", server_default=sa.text('{dval}')"
        elif "bool" in sql_type.lower():
            default_clause = " DEFAULT FALSE"
            sa_default = ", server_default=sa.text('false')"

        # Nullability
        is_nullable = "not null" not in p_lower
        null_clause = " NULL" if is_nullable else " NOT NULL"

        risk_level = "LOW" if is_nullable or default_clause else "MEDIUM"
        risk_desc = (
            f"**Safe Column Addition**: Adding `{col_name}` with `{sql_type}` to `{clean_table}`. "
        )
        if not is_nullable and not default_clause:
            risk_desc += (
                "**WARNING**: Adding a `NOT NULL` column without a `DEFAULT` value will fail if "
                f"`{clean_table}` already contains existing records."
            )

        up_ddl = f"ALTER TABLE {clean_table}\nADD COLUMN {col_name} {sql_type}{default_clause}{null_clause};"
        down_ddl = f"ALTER TABLE {clean_table}\nDROP COLUMN IF EXISTS {col_name};"

        alembic_code = (
            f"def upgrade() -> None:\n"
            f"    op.add_column(\n"
            f"        '{clean_table}',\n"
            f"        sa.Column('{col_name}', {sa_type}, nullable={is_nullable}{sa_default})\n"
            f"    )\n\n"
            f"def downgrade() -> None:\n"
            f"    op.drop_column('{clean_table}', '{col_name}')"
        )
        migration_title = f"Add column `{col_name}` ({sql_type}) to `{clean_table}`"

    # Assemble Markdown Response
    today_str = datetime.date.today().isoformat()
    rev_id = f"rev_{int(datetime.datetime.now().timestamp())}"

    # Determine code block tag based on safety
    tag = "sql:executable" if safety_mode != "read_only" or risk_level == "LOW" else "sql"

    output = [
        f"### Schema Migration: {migration_title}",
        "",
        f"**Risk Level**: `{risk_level}`",
        f"> {risk_desc}",
        "",
        "#### 1. SQL Forward Migration (UP)",
        f"```{tag}\n{up_ddl}\n```",
        "",
        "#### 2. SQL Rollback Script (DOWN)",
        f"```sql\n{down_ddl}\n```",
        "",
        "#### 3. Production Alembic Migration Script",
        "```python",
        f'"""{migration_title}\n\nRevision ID: {rev_id}\nRevises: None\nCreate Date: {today_str}\n"""',
        "from alembic import op",
        "import sqlalchemy as sa",
        "",
        alembic_code,
        "```",
        "",
        "#### 4. Pre-Flight Safety Verification",
        "- [ ] Test forward migration on a local or staging database replica first.",
        f"- [ ] Verify no long-running transactions are active on `{clean_table}` before executing.",
        "- [ ] Confirm rollback script executes cleanly and restores schema state."
    ]

    return "\n".join(output)


class MigrationArchitect:
    """Class wrapper for schema migration generation."""

    def __init__(self, dialect: str = "postgresql", safety_mode: str = "read_only"):
        self.dialect = dialect
        self.safety_mode = safety_mode

    def plan_migration(
        self,
        prompt: str,
        table_context: Optional[Union[List[str], str, List[TableSchema]]] = None
    ) -> str:
        return generate_migration_plan(
            prompt=prompt,
            table_context=table_context,
            dialect=self.dialect,
            safety_mode=self.safety_mode
        )
