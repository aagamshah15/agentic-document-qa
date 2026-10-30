from typing import List, Dict, Any, Optional, Set
import sqlalchemy
from sqlalchemy import inspect, text

from core.db_models import (
    ColumnInfo,
    ForeignKeyInfo,
    TableSchema,
    DatabaseSchemaResponse,
)
from services.db_connection import DBConnectionHandler


def detect_undeclared_links(
    table_name: str,
    columns: List[ColumnInfo],
    all_table_columns: Dict[str, Set[str]],
    existing_fks: List[ForeignKeyInfo],
) -> List[ForeignKeyInfo]:
    """
    Detects undeclared relational links between tables based on naming conventions.
    For example: `order_items.product_id` -> `products.id`
    """
    inferred_fks: List[ForeignKeyInfo] = []
    already_constrained = {
        col for fk in existing_fks for col in fk.constrained_columns
    }

    for col in columns:
        if col.name in already_constrained:
            continue

        c_lower = col.name.lower()
        if not (c_lower.endswith("_id") or (c_lower.startswith("id_") and len(c_lower) > 3)):
            continue

        # Extract base target candidate
        if c_lower.endswith("_id"):
            target_base = c_lower[:-3]
        else:
            target_base = c_lower[3:]

        if not target_base:
            continue

        # Generate pluralization candidates
        candidates = [target_base, f"{target_base}s", f"{target_base}es"]
        if target_base.endswith("y"):
            candidates.append(f"{target_base[:-1]}ies")

        # Search for a matching table in the schema
        matched_table = None
        for cand in candidates:
            for tbl in all_table_columns.keys():
                if tbl.lower() == cand and tbl.lower() != table_name.lower():
                    matched_table = tbl
                    break
            if matched_table:
                break

        if matched_table:
            # Check if referenced table has an 'id' or '<target>_id' column
            ref_cols = all_table_columns[matched_table]
            if "id" in ref_cols:
                inferred_fks.append(
                    ForeignKeyInfo(
                        constrained_columns=[col.name],
                        referred_table=matched_table,
                        referred_columns=["id"],
                    )
                )
            elif col.name in ref_cols:
                inferred_fks.append(
                    ForeignKeyInfo(
                        constrained_columns=[col.name],
                        referred_table=matched_table,
                        referred_columns=[col.name],
                    )
                )

    return inferred_fks


class SchemaCartographer:
    """
    Introspects table structures, column types, primary/foreign keys,
    detects undeclared relational links, and builds schema responses.
    """

    @classmethod
    def introspect_schema(cls, handler: DBConnectionHandler) -> DatabaseSchemaResponse:
        if not handler.is_connected:
            return DatabaseSchemaResponse(
                status="disconnected",
                engine="none",
                database_name="none",
                tables=[],
                error="No active database connection.",
            )

        try:
            if handler.engine_type == "duckdb":
                return cls._introspect_duckdb(handler)
            elif handler.engine_type == "sqlalchemy":
                return cls._introspect_sqlalchemy(handler)
            else:
                return DatabaseSchemaResponse(
                    status="error",
                    engine="unknown",
                    database_name="none",
                    tables=[],
                    error=f"Unsupported engine type: {handler.engine_type}",
                )
        except Exception as exc:
            return DatabaseSchemaResponse(
                status="error",
                engine=handler.dialect or "unknown",
                database_name=handler.active_database or "unknown",
                tables=[],
                error=f"Schema introspection failed: {str(exc)}",
            )

    @classmethod
    def _introspect_duckdb(cls, handler: DBConnectionHandler) -> DatabaseSchemaResponse:
        conn = handler.duckdb_conn
        table_rows = conn.execute(
            "SELECT table_name FROM duckdb_tables() WHERE NOT internal ORDER BY table_name"
        ).fetchall()
        table_names = [r[0] for r in table_rows]

        # First pass: collect columns for each table to enable relational link detection
        raw_tables_data: Dict[str, Dict[str, Any]] = {}
        all_table_columns: Dict[str, Set[str]] = {}

        for tbl in table_names:
            # Row count
            try:
                cnt_row = conn.execute(f'SELECT COUNT(*) FROM "{tbl}"').fetchone()
                row_count = int(cnt_row[0]) if cnt_row else 0
            except Exception:
                row_count = 0

            # Columns
            col_info_rows = conn.execute(f'PRAGMA table_info("{tbl}")').fetchall()
            columns: List[ColumnInfo] = []
            for c in col_info_rows:
                # (cid, name, type, notnull, dflt_value, pk)
                col_name = str(c[1])
                data_type = str(c[2])
                nullable = not bool(c[3])
                default_val = str(c[4]) if c[4] is not None else None
                is_pk = bool(c[5])
                columns.append(
                    ColumnInfo(
                        name=col_name,
                        data_type=data_type,
                        primary_key=is_pk,
                        nullable=nullable,
                        default=default_val,
                    )
                )

            # Foreign keys from SQLite ingestion cache or DuckDB constraints
            fks: List[ForeignKeyInfo] = list(handler.explicit_fks.get(tbl, []))

            # Query duckdb_constraints for declared FKs
            try:
                constraint_rows = conn.execute(
                    "SELECT constraint_column_names, referenced_table, referenced_column_names "
                    "FROM duckdb_constraints() WHERE table_name = ? AND constraint_type = 'FOREIGN KEY'",
                    [tbl],
                ).fetchall()
                for c_cols, ref_tbl, ref_cols in constraint_rows:
                    fks.append(
                        ForeignKeyInfo(
                            constrained_columns=list(c_cols),
                            referred_table=ref_tbl,
                            referred_columns=list(ref_cols),
                        )
                    )
            except Exception:
                pass

            raw_tables_data[tbl] = {
                "row_count": row_count,
                "columns": columns,
                "foreign_keys": fks,
            }
            all_table_columns[tbl] = {c.name.lower() for c in columns}

        # Second pass: detect undeclared relational links
        tables: List[TableSchema] = []
        for tbl in table_names:
            data = raw_tables_data[tbl]
            undeclared = detect_undeclared_links(
                tbl, data["columns"], all_table_columns, data["foreign_keys"]
            )
            all_fks = data["foreign_keys"] + undeclared
            tables.append(
                TableSchema(
                    name=tbl,
                    row_count=data["row_count"],
                    columns=data["columns"],
                    foreign_keys=all_fks,
                )
            )

        return DatabaseSchemaResponse(
            status="connected",
            engine="duckdb",
            database_name=handler.active_database or "in-memory",
            tables=tables,
        )

    @classmethod
    def _introspect_sqlalchemy(cls, handler: DBConnectionHandler) -> DatabaseSchemaResponse:
        engine = handler.sqlalchemy_engine
        inspector = inspect(engine)
        table_names = sorted(inspector.get_table_names())

        raw_tables_data: Dict[str, Dict[str, Any]] = {}
        all_table_columns: Dict[str, Set[str]] = {}

        for tbl in table_names:
            # Row count
            row_count = 0
            with engine.connect() as conn:
                try:
                    res = conn.execute(text(f'SELECT COUNT(*) FROM "{tbl}"')).scalar()
                    row_count = int(res) if res is not None else 0
                except Exception:
                    try:
                        res = conn.execute(text(f"SELECT COUNT(*) FROM {tbl}")).scalar()
                        row_count = int(res) if res is not None else 0
                    except Exception:
                        row_count = 0

            # Columns
            cols_meta = inspector.get_columns(tbl)
            pk_constraint = inspector.get_pk_constraint(tbl) or {}
            pk_cols = set(pk_constraint.get("constrained_columns") or [])

            columns: List[ColumnInfo] = []
            for col in cols_meta:
                c_name = col["name"]
                c_type = str(col["type"])
                c_pk = bool(col.get("primary_key")) or (c_name in pk_cols)
                c_nullable = bool(col.get("nullable", True))
                c_default = str(col.get("default")) if col.get("default") is not None else None
                columns.append(
                    ColumnInfo(
                        name=c_name,
                        data_type=c_type,
                        primary_key=c_pk,
                        nullable=c_nullable,
                        default=c_default,
                    )
                )

            # Foreign keys
            fks_meta = inspector.get_foreign_keys(tbl) or []
            foreign_keys: List[ForeignKeyInfo] = []
            for fk in fks_meta:
                foreign_keys.append(
                    ForeignKeyInfo(
                        constrained_columns=fk.get("constrained_columns") or [],
                        referred_table=fk.get("referred_table") or "",
                        referred_columns=fk.get("referred_columns") or [],
                    )
                )

            raw_tables_data[tbl] = {
                "row_count": row_count,
                "columns": columns,
                "foreign_keys": foreign_keys,
            }
            all_table_columns[tbl] = {c.name.lower() for c in columns}

        # Undeclared link detection pass
        tables: List[TableSchema] = []
        for tbl in table_names:
            data = raw_tables_data[tbl]
            undeclared = detect_undeclared_links(
                tbl, data["columns"], all_table_columns, data["foreign_keys"]
            )
            all_fks = data["foreign_keys"] + undeclared
            tables.append(
                TableSchema(
                    name=tbl,
                    row_count=data["row_count"],
                    columns=data["columns"],
                    foreign_keys=all_fks,
                )
            )

        return DatabaseSchemaResponse(
            status="connected",
            engine=handler.dialect or "sqlalchemy",
            database_name=handler.active_database or "database",
            tables=tables,
        )


def introspect_schema(handler: DBConnectionHandler) -> DatabaseSchemaResponse:
    """
    Convenience function returning the introspected schema response.
    """
    return SchemaCartographer.introspect_schema(handler)


def build_schema_context_dict(schema: DatabaseSchemaResponse) -> Dict[str, Any]:
    """
    Converts DatabaseSchemaResponse into a structured context dictionary.
    """
    context: Dict[str, Any] = {}
    for table in schema.tables:
        context[table.name] = {
            "row_count": table.row_count,
            "columns": [
                {
                    "name": col.name,
                    "type": col.data_type,
                    "primary_key": col.primary_key,
                    "nullable": col.nullable,
                    "default": col.default,
                }
                for col in table.columns
            ],
            "foreign_keys": [
                {
                    "columns": fk.constrained_columns,
                    "referred_table": fk.referred_table,
                    "referred_columns": fk.referred_columns,
                }
                for fk in table.foreign_keys
            ],
        }
    return context


def build_schema_prompt_context(schema: DatabaseSchemaResponse) -> str:
    """
    Formats the database schema into a compact, human- and LLM-readable summary.
    """
    lines = [f"Database Engine: {schema.engine} | Name: {schema.database_name}\n"]
    for table in schema.tables:
        lines.append(f"Table: {table.name} ({table.row_count} rows)")
        lines.append("  Columns:")
        for col in table.columns:
            pk_tag = " [PK]" if col.primary_key else ""
            null_tag = " NOT NULL" if not col.nullable else ""
            lines.append(f"    - {col.name}: {col.data_type}{pk_tag}{null_tag}")
        if table.foreign_keys:
            lines.append("  Foreign Keys:")
            for fk in table.foreign_keys:
                lines.append(
                    f"    - ({', '.join(fk.constrained_columns)}) -> {fk.referred_table}({', '.join(fk.referred_columns)})"
                )
        lines.append("")
    return "\n".join(lines)
