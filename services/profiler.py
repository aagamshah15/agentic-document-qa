"""
Profiler Service for Squad B (Profiling, Quality & Security).

Computes comprehensive statistical summaries and detects data anomalies:
- Column data types, total rows, total columns
- Null counts and null percentages
- Distinct value counts
- Sample values, minimum and maximum values
- Detects anomalies:
  * Null bursts (>50% missing values)
  * Duplicate values in candidate keys / primary keys
  * Extreme outliers & negative values in positive domains
  * Sensitive PII risks (via services.pii_detector)
"""

import math
import re
from typing import List, Dict, Any, Optional, Tuple, Union

from core.db_models import (
    ProfileResponse,
    ColumnProfile,
    AnomalyReport,
    QueryResponse,
)
from services.pii_detector import scan_column_for_pii


# =====================================================================
# Database Query Execution Helper
# =====================================================================

def _execute(manager: Any, query: str) -> Tuple[List[str], List[List[Any]]]:
    """
    Executes a SQL query against various manager / engine implementations:
    1. Squad A DatabaseManager (with execute_query returning QueryResponse or dict)
    2. SQLAlchemy Engine or Connection
    3. DuckDB / SQLite connection
    
    Returns:
        (column_names, rows)
    """
    # 1. Custom DatabaseManager with execute_query
    if hasattr(manager, "execute_query") and callable(manager.execute_query):
        res = manager.execute_query(query, mode="read_only")
        if isinstance(res, QueryResponse):
            if res.status == "error":
                raise RuntimeError(res.error or "Query execution failed")
            return list(res.columns), [list(r) for r in res.rows]
        elif hasattr(res, "rows") and hasattr(res, "columns"):
            if getattr(res, "status", "success") == "error":
                raise RuntimeError(getattr(res, "error", "Query execution failed"))
            return list(res.columns), [list(r) for r in res.rows]
        elif isinstance(res, dict):
            if res.get("status") == "error":
                raise RuntimeError(res.get("error", "Query execution failed"))
            return list(res.get("columns", [])), [list(r) for r in res.get("rows", [])]

    # 2. Manager with .engine (SQLAlchemy)
    engine = getattr(manager, "engine", None)
    if engine is not None and hasattr(engine, "connect"):
        from sqlalchemy import text
        with engine.connect() as conn:
            result = conn.execute(text(query))
            cols = list(result.keys()) if hasattr(result, "keys") else []
            rows = [list(r) for r in result.fetchall()]
            return cols, rows

    # 3. Direct SQLAlchemy Engine / Connection
    if hasattr(manager, "connect") and callable(manager.connect):
        from sqlalchemy import text
        with manager.connect() as conn:
            result = conn.execute(text(query))
            cols = list(result.keys()) if hasattr(result, "keys") else []
            rows = [list(r) for r in result.fetchall()]
            return cols, rows

    # 4. Connection (DuckDB / SQLite / etc.)
    conn = getattr(manager, "connection", manager)
    if hasattr(conn, "execute") and callable(conn.execute):
        cur = conn.execute(query)
        rows = [list(r) for r in cur.fetchall()]
        cols = [desc[0] for desc in cur.description] if cur.description else []
        return cols, rows

    raise ValueError(f"Unsupported manager type for query execution: {type(manager)}")


def _clean_val(v: Any) -> Any:
    """Ensure value is JSON-serializable."""
    if v is None:
        return None
    if isinstance(v, (int, float, str, bool)):
        # Handle NaN / Infinity floats
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            return str(v)
        return v
    if isinstance(v, bytes):
        return v.hex()
    return str(v)


def _detect_numeric_outliers(
    values: List[Union[int, float]]
) -> Tuple[float, float, List[Union[int, float]]]:
    """
    Computes Tukey's extreme fences (Q1 - 3*IQR, Q3 + 3*IQR) for numerical values.
    """
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    if n < 5:
        return 0.0, 0.0, []

    q1 = sorted_vals[int(n * 0.25)]
    q3 = sorted_vals[int(n * 0.75)]
    iqr = q3 - q1
    if iqr <= 0:
        return float(q1), float(q3), []

    lower_fence = float(q1) - 3.0 * float(iqr)
    upper_fence = float(q3) + 3.0 * float(iqr)
    outliers = [v for v in sorted_vals if v < lower_fence or v > upper_fence]
    return lower_fence, upper_fence, outliers


# =====================================================================
# Main Profiling Function
# =====================================================================

def run_table_profile(manager: Any, table_name: str) -> ProfileResponse:
    """
    Profiles a database table and detects statistical and security anomalies.
    
    Args:
        manager: Database manager, connection, or engine instance.
        table_name: Name of the table to profile.
        
    Returns:
        ProfileResponse containing columns_profile and anomalies.
    """
    try:
        safe_table = table_name.replace('"', '""')

        # 1. Discover Columns and Data Types
        column_meta: List[Dict[str, Any]] = []

        # Check if manager has get_schema()
        if hasattr(manager, "get_schema") and callable(manager.get_schema):
            try:
                schema_resp = manager.get_schema()
                tables = getattr(schema_resp, "tables", [])
                for t in tables:
                    if getattr(t, "name", "").lower() == table_name.lower():
                        for col in getattr(t, "columns", []):
                            column_meta.append({
                                "name": col.name,
                                "type": getattr(col, "data_type", "VARCHAR"),
                                "is_pk": getattr(col, "primary_key", False),
                            })
                        break
            except Exception:
                pass

        # If not found via get_schema, try PRAGMA table_info (SQLite / DuckDB)
        if not column_meta:
            try:
                pragma_cols, pragma_rows = _execute(manager, f'PRAGMA table_info("{safe_table}")')
                if pragma_rows:
                    for row in pragma_rows:
                        # PRAGMA format: (cid, name, type, notnull, dflt_value, pk)
                        col_name = str(row[1])
                        col_type = str(row[2]) if row[2] else "VARCHAR"
                        is_pk = bool(row[5] > 0) if len(row) > 5 else False
                        column_meta.append({
                            "name": col_name,
                            "type": col_type,
                            "is_pk": is_pk,
                        })
            except Exception:
                pass

        # Fallback: SELECT * LIMIT 0 to get column names
        if not column_meta:
            cols, _ = _execute(manager, f'SELECT * FROM "{safe_table}" LIMIT 0')
            for col_name in cols:
                column_meta.append({
                    "name": col_name,
                    "type": "VARCHAR",
                    "is_pk": col_name.lower() in ("id", "pk", "uuid"),
                })

        if not column_meta:
            return ProfileResponse(
                status="error",
                table=table_name,
                total_rows=0,
                total_columns=0,
                columns_profile=[],
                anomalies=[],
                error=f"Table '{table_name}' not found or has no columns.",
            )

        # 2. Get Total Row Count
        count_cols, count_rows = _execute(manager, f'SELECT COUNT(*) FROM "{safe_table}"')
        total_rows = int(count_rows[0][0]) if count_rows and count_rows[0] else 0

        columns_profile: List[ColumnProfile] = []
        anomalies: List[AnomalyReport] = []

        # If table is empty
        if total_rows == 0:
            for col in column_meta:
                columns_profile.append(ColumnProfile(
                    name=col["name"],
                    data_type=col["type"],
                    null_count=0,
                    null_percentage=0.0,
                    unique_count=0,
                    sample_values=[],
                    min_value=None,
                    max_value=None,
                ))
            anomalies.append(AnomalyReport(
                category="empty_table",
                severity="info",
                table=table_name,
                column=None,
                description=f"Table '{table_name}' is currently empty (0 rows).",
                suggested_action="Populate table or seed synthetic records for testing.",
            ))
            return ProfileResponse(
                status="success",
                table=table_name,
                total_rows=0,
                total_columns=len(columns_profile),
                columns_profile=columns_profile,
                anomalies=anomalies,
            )

        # 3. Profile Each Column
        for col in column_meta:
            col_name = col["name"]
            col_type = col["type"]
            is_pk = col["is_pk"]
            safe_col = col_name.replace('"', '""')

            # Fetch aggregate stats: null_count, unique_count, min_val, max_val
            null_count = 0
            unique_count = 0
            min_val = None
            max_val = None

            try:
                # Attempt batched query for stats
                stat_query = (
                    f'SELECT '
                    f'COUNT(*) - COUNT("{safe_col}"), '
                    f'COUNT(DISTINCT "{safe_col}"), '
                    f'MIN("{safe_col}"), '
                    f'MAX("{safe_col}") '
                    f'FROM "{safe_table}"'
                )
                _, stat_rows = _execute(manager, stat_query)
                if stat_rows and stat_rows[0]:
                    null_count = int(stat_rows[0][0]) if stat_rows[0][0] is not None else 0
                    unique_count = int(stat_rows[0][1]) if stat_rows[0][1] is not None else 0
                    min_val = _clean_val(stat_rows[0][2])
                    max_val = _clean_val(stat_rows[0][3])
            except Exception:
                # Fallback to individual queries if batch fails on complex types
                try:
                    _, r = _execute(manager, f'SELECT COUNT(*) - COUNT("{safe_col}") FROM "{safe_table}"')
                    null_count = int(r[0][0]) if r and r[0] else 0
                except Exception:
                    null_count = 0

                try:
                    _, r = _execute(manager, f'SELECT COUNT(DISTINCT "{safe_col}") FROM "{safe_table}"')
                    unique_count = int(r[0][0]) if r and r[0] else 0
                except Exception:
                    unique_count = 0

                try:
                    _, r = _execute(manager, f'SELECT MIN("{safe_col}"), MAX("{safe_col}") FROM "{safe_table}"')
                    if r and r[0]:
                        min_val = _clean_val(r[0][0])
                        max_val = _clean_val(r[0][1])
                except Exception:
                    min_val = None
                    max_val = None

            # Fetch sample values (up to 5 non-null values)
            sample_values: List[Any] = []
            try:
                sample_query = (
                    f'SELECT DISTINCT "{safe_col}" FROM "{safe_table}" '
                    f'WHERE "{safe_col}" IS NOT NULL LIMIT 5'
                )
                _, sample_rows = _execute(manager, sample_query)
                sample_values = [_clean_val(row[0]) for row in sample_rows if row]
            except Exception:
                try:
                    sample_query = (
                        f'SELECT "{safe_col}" FROM "{safe_table}" '
                        f'WHERE "{safe_col}" IS NOT NULL LIMIT 5'
                    )
                    _, sample_rows = _execute(manager, sample_query)
                    sample_values = [_clean_val(row[0]) for row in sample_rows if row]
                except Exception:
                    sample_values = []

            null_percentage = round((null_count / total_rows) * 100.0, 2) if total_rows > 0 else 0.0

            # Build ColumnProfile
            col_profile = ColumnProfile(
                name=col_name,
                data_type=col_type,
                null_count=null_count,
                null_percentage=null_percentage,
                unique_count=unique_count,
                sample_values=sample_values,
                min_value=min_val,
                max_value=max_val,
            )
            columns_profile.append(col_profile)

            # =================================================================
            # Anomaly 1: Null Bursts (>50% missing values)
            # =================================================================
            if null_percentage > 50.0:
                severity = "critical" if null_percentage >= 80.0 else "warning"
                anomalies.append(AnomalyReport(
                    category="null_burst",
                    severity=severity,
                    table=table_name,
                    column=col_name,
                    description=(
                        f"Column '{col_name}' has high null rate: {null_percentage:.1f}% "
                        f"missing values ({null_count}/{total_rows} rows)."
                    ),
                    suggested_action="Investigate upstream ETL pipeline for missing data ingestion or apply null imputation."
                ))

            # =================================================================
            # Anomaly 2: Duplicate Values in Candidate Keys / Primary Keys
            # =================================================================
            is_candidate_key = (
                is_pk
                or col_name.lower() in ("id", "uuid", "guid", "pk", "key")
                or col_name.lower().endswith(("_id", "_uuid", "_key"))
            )
            if is_candidate_key and total_rows > 1:
                non_null_rows = total_rows - null_count
                if unique_count < non_null_rows or (is_pk and unique_count < total_rows):
                    severity = "critical" if (is_pk or col_name.lower() in ("id", "uuid", "pk")) else "warning"
                    anomalies.append(AnomalyReport(
                        category="duplicate_pk",
                        severity=severity,
                        table=table_name,
                        column=col_name,
                        description=(
                            f"Candidate key '{col_name}' contains duplicate values "
                            f"({unique_count} distinct values in {total_rows} rows)."
                        ),
                        suggested_action=f"Enforce UNIQUE constraint on '{col_name}' and deduplicate records."
                    ))

            # =================================================================
            # Anomaly 3: Extreme Outliers & Domain Anomalies
            # =================================================================
            # Check domain anomalies: negative values in typically positive fields
            positive_domain_keywords = (
                "age", "price", "amount", "salary", "quantity", "count",
                "cost", "total", "balance", "inventory", "stock", "revenue"
            )
            if (
                any(kw in col_name.lower() for kw in positive_domain_keywords)
                and min_val is not None
                and isinstance(min_val, (int, float))
                and min_val < 0
            ):
                anomalies.append(AnomalyReport(
                    category="extreme_outlier",
                    severity="warning",
                    table=table_name,
                    column=col_name,
                    description=f"Column '{col_name}' contains unexpected negative values (minimum: {min_val}).",
                    suggested_action=f"Apply non-negative domain constraints on '{col_name}'."
                ))

            # Check statistical outliers for numeric columns
            is_numeric_type = bool(re.search(
                r'(int|float|double|real|numeric|decimal|number)',
                col_type,
                re.I
            )) or (isinstance(min_val, (int, float)) and isinstance(max_val, (int, float)))

            if is_numeric_type and total_rows >= 5:
                try:
                    num_query = (
                        f'SELECT "{safe_col}" FROM "{safe_table}" '
                        f'WHERE "{safe_col}" IS NOT NULL LIMIT 1000'
                    )
                    _, num_rows = _execute(manager, num_query)
                    num_vals = [
                        float(r[0]) for r in num_rows
                        if r and r[0] is not None and isinstance(r[0], (int, float))
                    ]
                    if len(num_vals) >= 5:
                        lower_f, upper_f, outliers = _detect_numeric_outliers(num_vals)
                        if outliers:
                            anomalies.append(AnomalyReport(
                                category="extreme_outlier",
                                severity="warning",
                                table=table_name,
                                column=col_name,
                                description=(
                                    f"Column '{col_name}' has {len(outliers)} extreme outlier(s) "
                                    f"outside [{lower_f:.2f}, {upper_f:.2f}] "
                                    f"(min: {min_val}, max: {max_val})."
                                ),
                                suggested_action=f"Review extreme outlier values in '{col_name}' for entry or sensor errors."
                            ))
                except Exception:
                    pass

            # =================================================================
            # Anomaly 4: Sensitive PII Detection
            # =================================================================
            pii_reports = scan_column_for_pii(
                table_name=table_name,
                column_name=col_name,
                sample_values=sample_values,
                data_type=col_type,
            )
            anomalies.extend(pii_reports)

        return ProfileResponse(
            status="success",
            table=table_name,
            total_rows=total_rows,
            total_columns=len(columns_profile),
            columns_profile=columns_profile,
            anomalies=anomalies,
            error=None,
        )

    except Exception as e:
        return ProfileResponse(
            status="error",
            table=table_name,
            total_rows=0,
            total_columns=0,
            columns_profile=[],
            anomalies=[],
            error=str(e),
        )
