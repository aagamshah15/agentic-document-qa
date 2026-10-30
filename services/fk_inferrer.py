"""
Autonomous Data & Schema Studio — Heuristic Foreign Key Inferrer.
Calculates empirical value containment, name similarity, and cardinality fitness,
penalizing lookup-table and shared-sequence false-positive traps.
"""

import re
from typing import Dict, Any, List, Optional, Set, Tuple
from sqlalchemy import text
from sqlalchemy.engine import Engine

from services.app_db import StudioAppDB


def _normalize_name(name: str) -> str:
    """Strips common suffixes and prefixes for fuzzy relational matching."""
    n = name.lower()
    for sfx in ("_id", "id", "_code", "_cd", "_key", "_fk"):
        if n.endswith(sfx) and len(n) > len(sfx):
            n = n[:-len(sfx)]
            break
    for pfx in ("tbl_", "dim_", "fact_", "ref_"):
        if n.startswith(pfx):
            n = n[len(pfx):]
            break
    # Remove trailing plural 's'
    if n.endswith("s") and len(n) > 3:
        n = n[:-1]
    return n


def _calculate_name_similarity(child_col: str, parent_table: str, parent_col: str) -> float:
    """
    Scores semantic name correspondence between child column and parent table/column.
    """
    c_col = child_col.lower()
    p_tbl = parent_table.lower()
    p_col = parent_col.lower()

    # Exact column name match (e.g. account_id -> account_id)
    if c_col == p_col and c_col not in ("id", "code", "status", "type"):
        return 0.95

    # Child col is parent_table + _id (e.g. customer_id -> customers.id, or cust_id -> customers.id)
    norm_c = _normalize_name(c_col)
    norm_p_tbl = _normalize_name(p_tbl)

    if norm_c == norm_p_tbl and p_col in ("id", f"{p_tbl}_id", f"{norm_p_tbl}_id"):
        return 1.0

    if norm_c in norm_p_tbl or norm_p_tbl in norm_c:
        return 0.85

    # Generic uninformative names like status, id, code get low similarity
    if c_col in ("id", "code", "status", "type", "state", "flag"):
        return 0.1

    return 0.2


class FKInferrer:
    def __init__(self, app_db: Optional[StudioAppDB] = None):
        self.app_db = app_db or StudioAppDB()

    def infer_foreign_keys(
        self,
        engine: Engine,
        snapshot: Dict[str, Any],
        min_score: float = 0.65,
        max_candidates: int = 20,
    ) -> List[Dict[str, Any]]:
        """
        Discovers undeclared relational links by computing mathematical containment
        between candidate column pairs and filtering known traps.
        """
        structure = snapshot.get("structure", snapshot)
        tables = structure.get("tables", [])
        snapshot_id = snapshot.get("id", "temp_snap")

        # Collect existing declared FKs to avoid duplicate suggestions
        declared_edges: Set[Tuple[str, str, str, str]] = set()
        for t in tables:
            t_name = t["name"]
            for fk in t.get("foreign_keys", []):
                ref_tbl = fk.get("referred_table")
                for c_col, p_col in zip(fk.get("constrained_columns", []), fk.get("referred_columns", [])):
                    if ref_tbl:
                        declared_edges.add((t_name, c_col, ref_tbl, p_col))

        # Build column profile index
        candidate_pairs = []

        # Compare non-PK columns in Table A with PK / unique columns in Table B
        for child_tbl in tables:
            c_name = child_tbl["name"]
            for c_col in child_tbl.get("columns", []):
                col_name = c_col["name"]
                col_type = c_col["type"]

                # Exclude obvious non-foreign key columns
                if c_col.get("primary_key") and len(child_tbl.get("primary_keys", [])) == 1:
                    # Skip single PKs to avoid shared sequence trap between PKs
                    continue
                if any(kw in col_name.lower() for kw in ("created", "updated", "password", "hash", "secret", "body", "text")):
                    continue

                for parent_tbl in tables:
                    p_name = parent_tbl["name"]
                    if c_name == p_name:
                        # Skip self-referencing for general candidate search unless named manager/parent
                        if not any(k in col_name.lower() for k in ("parent", "manager", "prev")):
                            continue

                    for p_col in parent_tbl.get("columns", []):
                        p_col_name = p_col["name"]
                        p_col_type = p_col["type"]

                        # Parent column should be a primary key or unique index
                        is_parent_pk = p_col.get("primary_key", False)
                        if not is_parent_pk and p_col_name != "id":
                            continue

                        # Check if already declared
                        if (c_name, col_name, p_name, p_col_name) in declared_edges:
                            continue

                        # Type compatibility check
                        c_is_int = any(t in col_type for t in ("INT", "SERIAL", "NUMERIC"))
                        p_is_int = any(t in p_col_type for t in ("INT", "SERIAL", "NUMERIC"))
                        c_is_str = any(t in col_type for t in ("CHAR", "TEXT", "STRING"))
                        p_is_str = any(t in p_col_type for t in ("CHAR", "TEXT", "STRING"))

                        if (c_is_int and p_is_int) or (c_is_str and p_is_str):
                            type_score = 1.0
                        else:
                            type_score = 0.0
                            continue  # Incompatible datatypes cannot form an FK

                        name_score = _calculate_name_similarity(col_name, p_name, p_col_name)

                        # Filter Lookup Table Trap early: if name similarity is very low and child is generic
                        if name_score < 0.2 and col_name.lower() in ("status", "code", "type", "state"):
                            continue

                        candidate_pairs.append({
                            "child_table": c_name,
                            "child_column": col_name,
                            "parent_table": p_name,
                            "parent_column": p_col_name,
                            "name_score": name_score,
                            "type_score": type_score,
                        })

        # Evaluate candidate containment against live data
        inferred_results = []

        with engine.connect() as conn:
            for pair in candidate_pairs:
                c_tbl = pair["child_table"]
                c_col = pair["child_column"]
                p_tbl = pair["parent_table"]
                p_col = pair["parent_column"]

                try:
                    # Query distinct count in child (excluding NULLs)
                    q_c = f"SELECT COUNT(DISTINCT {c_col}) FROM {c_tbl} WHERE {c_col} IS NOT NULL;"
                    distinct_child = conn.execute(text(q_c)).scalar() or 0
                    if distinct_child == 0:
                        continue

                    # Query overlapping distinct count
                    overlap_sql = f"""
                        SELECT COUNT(DISTINCT c.{c_col})
                        FROM {c_tbl} c
                        INNER JOIN {p_tbl} p ON c.{c_col} = p.{p_col}
                        WHERE c.{c_col} IS NOT NULL;
                    """
                    overlapping = conn.execute(text(overlap_sql)).scalar() or 0

                    containment = round(float(overlapping) / float(distinct_child), 4)

                    # Containment must be high (>= 85%) for plausible relational linkage
                    if containment < 0.85:
                        continue

                    # Query parent cardinality ratio (distinct parent values / total parent rows)
                    q_p_card = f"SELECT COUNT(DISTINCT {p_col}), COUNT(*) FROM {p_tbl};"
                    row_p = conn.execute(text(q_p_card)).fetchone()
                    dist_p, total_p = row_p[0] or 0, row_p[1] or 0
                    cardinality_fit = round(float(dist_p) / float(total_p), 4) if total_p > 0 else 0.5

                    # Combined Heuristic Formula
                    total_score = round(
                        (0.50 * containment)
                        + (0.25 * pair["name_score"])
                        + (0.15 * pair["type_score"])
                        + (0.10 * cardinality_fit),
                        3,
                    )

                    if total_score >= min_score:
                        record_id = f"inf_{c_tbl}_{c_col}_{p_tbl}_{p_col}"
                        evidence_query = overlap_sql.strip().replace("\n", " ")

                        inf_obj = {
                            "id": record_id,
                            "snapshot_id": snapshot_id,
                            "child_table": c_tbl,
                            "child_column": c_col,
                            "parent_table": p_tbl,
                            "parent_column": p_col,
                            "score": total_score,
                            "containment": containment,
                            "name_score": pair["name_score"],
                            "type_score": pair["type_score"],
                            "cardinality": cardinality_fit,
                            "evidence_query": evidence_query,
                            "status": "proposed",
                        }
                        inferred_results.append(inf_obj)

                        # Record in app DB if valid snapshot exists
                        if snapshot_id and snapshot_id != "temp_snap":
                            try:
                                with self.app_db._get_connection() as app_conn:
                                    app_conn.execute(
                                        """
                                        INSERT OR REPLACE INTO relationship_inferences (
                                            id, snapshot_id, child_table, child_column,
                                            parent_table, parent_column, score, containment,
                                            name_score, type_score, cardinality, evidence_query,
                                            status, created_at
                                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'proposed', datetime('now', 'utc'));
                                        """,
                                        (
                                            record_id, snapshot_id, c_tbl, c_col, p_tbl, p_col,
                                            total_score, containment, pair["name_score"],
                                            pair["type_score"], cardinality_fit, evidence_query,
                                        ),
                                    )
                                    app_conn.commit()
                            except Exception:
                                pass

                except Exception:
                    continue

        # Sort by total score descending
        inferred_results.sort(key=lambda x: x["score"], reverse=True)
        return inferred_results[:max_candidates]
