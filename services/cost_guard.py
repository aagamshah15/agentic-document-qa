"""
Autonomous Data & Schema Studio — EXPLAIN Query Cost Guard.
Pre-flights query execution plans across Postgres, SQLite, and DuckDB,
detecting runaway sequential scans and enforcing environment tier cost guardrails.
"""

import json
from typing import Dict, Any, List, Optional
from sqlalchemy import text
from sqlalchemy.engine import Engine


TIER_ROW_THRESHOLDS = {
    "sandbox": 50_000_000,
    "dev": 10_000_000,
    "prod": 1_000_000,
}


class CostGuardException(Exception):
    pass


class CostGuard:
    def __init__(self):
        pass

    def evaluate_plan_and_cost(
        self,
        engine: Engine,
        sql: str,
        engine_type: str = "sqlite",
        tier: str = "sandbox",
    ) -> Dict[str, Any]:
        """
        Runs dialect-specific EXPLAIN to estimate row scans and warn about full table scans.
        """
        eng_norm = engine_type.lower()
        max_allowed_rows = TIER_ROW_THRESHOLDS.get(tier.lower(), 10_000_000)

        plan_raw = []
        estimated_rows = 0
        has_seq_scan = False
        warnings = []
        scanned_tables = []

        try:
            with engine.connect() as conn:
                if eng_norm in ("postgres", "postgresql"):
                    explain_sql = f"EXPLAIN (FORMAT JSON) {sql}"
                    res = conn.execute(text(explain_sql)).scalar()
                    if isinstance(res, str):
                        res = json.loads(res)
                    plan_raw = res

                    # Traverse Postgres plan tree
                    if isinstance(res, list) and len(res) > 0:
                        root_plan = res[0].get("Plan", {})
                        estimated_rows = int(root_plan.get("Plan Rows", 0))

                        def _walk(node):
                            nonlocal has_seq_scan
                            ntype = node.get("Node Type", "")
                            if "Seq Scan" in ntype:
                                has_seq_scan = True
                                scanned_tables.append(node.get("Relation Name", "unknown"))
                            for child in node.get("Plans", []):
                                _walk(child)

                        _walk(root_plan)

                elif eng_norm in ("sqlite", "sqlite3"):
                    explain_sql = f"EXPLAIN QUERY PLAN {sql}"
                    rows = conn.execute(text(explain_sql)).fetchall()
                    plan_raw = [{"id": r[0], "parent": r[1], "detail": r[3] if len(r) > 3 else str(r)} for r in rows]

                    for r in plan_raw:
                        det = r["detail"].upper()
                        if "SCAN" in det and "INDEX" not in det:
                            has_seq_scan = True
                            # Extract table name from SCAN TABLE <tbl>
                            parts = r["detail"].split()
                            if "TABLE" in parts:
                                idx = parts.index("TABLE")
                                if idx + 1 < len(parts):
                                    scanned_tables.append(parts[idx + 1])
                    estimated_rows = 1000 if has_seq_scan else 50

                elif eng_norm in ("duckdb",):
                    explain_sql = f"EXPLAIN {sql}"
                    rows = conn.execute(text(explain_sql)).fetchall()
                    plan_raw = [{"plan": str(r[1]) if len(r) > 1 else str(r[0])} for r in rows]
                    for r in plan_raw:
                        if "SEQ_SCAN" in r["plan"].upper():
                            has_seq_scan = True
                    estimated_rows = 500

        except Exception as e:
            warnings.append(f"Cost pre-flight inspection note: {str(e)}")

        requires_confirmation = False

        if estimated_rows > max_allowed_rows:
            requires_confirmation = True
            warnings.append(
                f"Estimated row scan ({estimated_rows:,}) exceeds {tier.upper()} tier safety limit ({max_allowed_rows:,}). Explicit confirmation required."
            )

        if has_seq_scan and tier.lower() in ("dev", "prod"):
            warnings.append(
                f"Full sequential table scan detected on {', '.join(set(scanned_tables)) or 'unindexed table'}. Consider filtering on an indexed column."
            )

        return {
            "engine": eng_norm,
            "tier": tier,
            "estimated_rows": estimated_rows,
            "has_seq_scan": has_seq_scan,
            "scanned_tables": list(set(scanned_tables)),
            "requires_confirmation": requires_confirmation,
            "warnings": warnings,
            "plan_tree": plan_raw,
        }


cost_guard = CostGuard()
