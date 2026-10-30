import re
import time
import datetime
import decimal
import uuid
from typing import Any, List, Optional
import sqlalchemy
from sqlalchemy import text

from core.db_models import QueryResponse
from services.db_connection import DBConnectionHandler


def is_mutating_query(query: str) -> bool:
    """
    AST/Token-level keyword inspection: checks whether the query contains
    destructive/mutating statements outside string literals and comments.
    """
    # 1. Remove block comments /* ... */
    q = re.sub(r"/\*.*?\*/", " ", query, flags=re.DOTALL)
    # 2. Remove single-line comments -- ...
    q = re.sub(r"--[^\r\n]*", " ", q)
    # 3. Remove single-quoted strings: '...', handling escaped quotes ''
    q = re.sub(r"'(?:''|[^'])*'", "''", q)
    # 4. Remove dollar-quoted strings: $$...$$
    q = re.sub(r"\$\$.*?\$\$", "''", q, flags=re.DOTALL)

    # Check for mutating keywords
    pattern = r"\b(DROP|DELETE|TRUNCATE|ALTER|UPDATE|INSERT)\b"
    return bool(re.search(pattern, q, re.IGNORECASE))


def serialize_cell(val: Any) -> Any:
    """
    Ensure all cell values are JSON-serializable primitives.
    """
    if val is None:
        return None
    if isinstance(val, (int, float, bool, str)):
        return val
    if isinstance(val, (datetime.date, datetime.datetime)):
        return val.isoformat()
    if isinstance(val, decimal.Decimal):
        return float(val) if val % 1 else int(val)
    if isinstance(val, (bytes, bytearray)):
        return val.decode("utf-8", errors="replace")
    if isinstance(val, uuid.UUID):
        return str(val)
    if isinstance(val, (list, tuple)):
        return [serialize_cell(item) for item in val]
    if isinstance(val, dict):
        return {str(k): serialize_cell(v) for k, v in val.items()}
    return str(val)


class SafeSQLExecutor:
    """
    Executes SQL queries against the active connection with read-only
    guardrails, query timing, pagination limits, and result serialization.
    """

    @classmethod
    def execute(
        cls,
        handler: DBConnectionHandler,
        query: str,
        mode: str = "read_only",
        limit: Optional[int] = 100,
    ) -> QueryResponse:
        clean_query = query.strip()
        if not clean_query:
            return QueryResponse(
                status="error",
                columns=[],
                rows=[],
                row_count=0,
                execution_time_ms=0.0,
                truncated=False,
                error="Empty query provided.",
            )

        # Safety rule: block mutating statements in read_only mode via AST sql_guard
        if mode == "read_only":
            try:
                from services.sql_guard import sql_guard
                dialect = "duckdb" if getattr(handler, "engine_type", "") == "duckdb" else "sqlite"
                clean_query, _ = sql_guard.enforce_read_only(clean_query, dialect=dialect)
            except Exception as ge:
                return QueryResponse(
                    status="error",
                    columns=[],
                    rows=[],
                    row_count=0,
                    execution_time_ms=0.0,
                    truncated=False,
                    error="Mutating statements blocked in read_only mode.",
                )

        if not handler.is_connected:
            return QueryResponse(
                status="error",
                columns=[],
                rows=[],
                row_count=0,
                execution_time_ms=0.0,
                truncated=False,
                error="No active database connection.",
            )

        start_time = time.perf_counter()

        try:
            if handler.engine_type == "duckdb":
                return cls._execute_duckdb(handler, clean_query, limit, start_time)
            elif handler.engine_type == "sqlalchemy":
                return cls._execute_sqlalchemy(handler, clean_query, limit, start_time)
            else:
                elapsed_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
                return QueryResponse(
                    status="error",
                    columns=[],
                    rows=[],
                    row_count=0,
                    execution_time_ms=elapsed_ms,
                    truncated=False,
                    error=f"Unsupported engine type: {handler.engine_type}",
                )
        except Exception as exc:
            elapsed_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
            return QueryResponse(
                status="error",
                columns=[],
                rows=[],
                row_count=0,
                execution_time_ms=elapsed_ms,
                truncated=False,
                error=str(exc),
            )

    @classmethod
    def _execute_duckdb(
        cls,
        handler: DBConnectionHandler,
        query: str,
        limit: Optional[int],
        start_time: float,
    ) -> QueryResponse:
        conn = handler.duckdb_conn
        result = conn.execute(query)

        if result.description:
            columns = [col[0] for col in result.description]
            if limit is not None and limit > 0:
                raw_fetched = result.fetchmany(limit + 1)
                truncated = len(raw_fetched) > limit
                raw_rows = raw_fetched[:limit]
            else:
                raw_rows = result.fetchall()
                truncated = False

            rows = [[serialize_cell(cell) for cell in row] for row in raw_rows]
            row_count = len(rows)
        else:
            columns = []
            rows = []
            row_count = 0
            truncated = False

        elapsed_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
        return QueryResponse(
            status="success",
            columns=columns,
            rows=rows,
            row_count=row_count,
            execution_time_ms=elapsed_ms,
            truncated=truncated,
            error=None,
        )

    @classmethod
    def _execute_sqlalchemy(
        cls,
        handler: DBConnectionHandler,
        query: str,
        limit: Optional[int],
        start_time: float,
    ) -> QueryResponse:
        engine = handler.sqlalchemy_engine
        with engine.connect() as conn:
            result = conn.execute(text(query))

            if result.returns_rows:
                columns = list(result.keys())
                if limit is not None and limit > 0:
                    raw_fetched = result.fetchmany(limit + 1)
                    truncated = len(raw_fetched) > limit
                    raw_rows = raw_fetched[:limit]
                else:
                    raw_rows = result.fetchall()
                    truncated = False

                rows = [[serialize_cell(cell) for cell in row] for row in raw_rows]
                row_count = len(rows)
            else:
                conn.commit()
                columns = []
                rows = []
                row_count = result.rowcount if result.rowcount >= 0 else 0
                truncated = False

        elapsed_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
        return QueryResponse(
            status="success",
            columns=columns,
            rows=rows,
            row_count=row_count,
            execution_time_ms=elapsed_ms,
            truncated=truncated,
            error=None,
        )


def execute_query(
    handler: DBConnectionHandler,
    query: str,
    mode: str = "read_only",
    limit: Optional[int] = 100,
) -> QueryResponse:
    """
    Convenience function to run a SQL query through SafeSQLExecutor.
    """
    return SafeSQLExecutor.execute(handler, query, mode=mode, limit=limit)
