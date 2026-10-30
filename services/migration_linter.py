"""
Autonomous Data & Schema Studio — Lock-Risk & Migration Impact Linter.
Analyzes DDL for ACCESS EXCLUSIVE locks, missing CONCURRENTLY/NOT VALID clauses,
computes dependent object impact, and exports to Alembic & Flyway.
"""

import re
from typing import Dict, Any, List, Optional


class MigrationLinter:
    def __init__(self):
        pass

    def lint_ddl(
        self,
        up_sql: str,
        engine_type: str = "postgres",
        table_row_estimates: Optional[Dict[str, int]] = None,
    ) -> Dict[str, Any]:
        """
        Scans DDL statements for dangerous locking patterns and suggests safe alternatives.
        """
        row_estimates = table_row_estimates or {}
        warnings = []
        suggestions = []
        is_risky = False

        eng_norm = engine_type.lower()
        up_upper = up_sql.upper()

        # 1. Missing CONCURRENTLY on CREATE INDEX (Postgres)
        if "CREATE INDEX" in up_upper and "CONCURRENTLY" not in up_upper and eng_norm in ("postgres", "postgresql"):
            is_risky = True
            warnings.append("CREATE INDEX locks the table for concurrent writes. Use CREATE INDEX CONCURRENTLY to avoid downtime.")
            suggestions.append(re.sub(r"CREATE\s+INDEX", "CREATE INDEX CONCURRENTLY", up_sql, flags=re.IGNORECASE))

        # 2. Missing NOT VALID on ADD CONSTRAINT FOREIGN KEY
        if "ADD CONSTRAINT" in up_upper and "FOREIGN KEY" in up_upper:
            if "NOT VALID" not in up_upper and eng_norm in ("postgres", "postgresql"):
                is_risky = True
                warnings.append("ADD CONSTRAINT FOREIGN KEY requires scanning entire table while holding lock. Suggest adding NOT VALID and validating separately.")
                suggestions.append(up_sql.strip().rstrip(";") + " NOT VALID;")

        # 3. ALTER TABLE ... ALTER COLUMN TYPE (Full Table Rewrite Lock)
        if "ALTER COLUMN" in up_upper and any(kw in up_upper for kw in ("TYPE", "SET DATA TYPE")):
            is_risky = True
            warnings.append("Altering column data type causes a full table rewrite holding an ACCESS EXCLUSIVE lock on PostgreSQL.")

        # 4. DROP COLUMN (Breaking Change Impact)
        if "DROP COLUMN" in up_upper:
            is_risky = True
            warnings.append("Dropping a column is an irreversible breaking change for running applications and dependent views.")

        # 5. Non-null column without default
        if "ADD COLUMN" in up_upper and "NOT NULL" in up_upper and "DEFAULT" not in up_upper:
            is_risky = True
            warnings.append("Adding a NOT NULL column without a DEFAULT will fail on tables with existing rows.")

        return {
            "is_risky": is_risky,
            "risk_level": "critical" if is_risky else "low",
            "warnings": warnings,
            "suggestions": suggestions,
        }

    def analyze_impact(
        self,
        up_sql: str,
        structure: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Identifies tables, columns, and foreign keys affected by the migration.
        """
        tables = structure.get("tables", [])
        known_tables = {t["name"].lower(): t for t in tables}

        affected_tables = set()
        affected_columns = []
        broken_foreign_keys = []

        up_lower = up_sql.lower()
        for t_name, t_data in known_tables.items():
            if t_name in up_lower:
                affected_tables.add(t_data["name"])

                # Check if any FK refers to this table
                for other_t in tables:
                    for fk in other_t.get("foreign_keys", []):
                        if (fk.get("referred_table") or "").lower() == t_name:
                            broken_foreign_keys.append({
                                "source_table": other_t["name"],
                                "fk_columns": fk.get("constrained_columns", []),
                                "target_table": t_data["name"],
                            })

        return {
            "affected_tables": sorted(list(affected_tables)),
            "potentially_impacted_foreign_keys": broken_foreign_keys,
            "view_dependencies_count": 0,
        }

    @staticmethod
    def export_alembic(goal: str, up_sql: str, down_sql: str, revision_id: str = "rev_001") -> str:
        """Exports migration as a standard Python Alembic migration script."""
        import datetime
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        return f'''"""
{goal}

Revision ID: {revision_id}
Create Date: {now_str}
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '{revision_id}'
down_revision = None
branch_labels = None
depends_on = None

def upgrade() -> None:
    # UP Migration Statements
{indent_sql_as_op_execute(up_sql)}

def downgrade() -> None:
    # DOWN Rollback Statements
{indent_sql_as_op_execute(down_sql)}
'''

    @staticmethod
    def export_flyway(goal: str, up_sql: str, version: str = "1") -> str:
        """Exports migration as a standard Flyway versioned SQL file."""
        return f"-- Flyway Migration: V{version}__{re.sub(r'[^a-zA-Z0-9_]', '_', goal)}.sql\n\n{up_sql}\n"


def indent_sql_as_op_execute(sql: str) -> str:
    lines = []
    for stmt in sql.strip().split(";"):
        stmt = stmt.strip()
        if stmt:
            lines.append(f'    op.execute("""{stmt};""")')
    return "\n".join(lines) if lines else "    pass"


migration_linter = MigrationLinter()
