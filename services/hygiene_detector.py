"""
Autonomous Data & Schema Studio — Data Hygiene & Anomaly Detector.
Scans for mixed date formats, sentinels, high null rates, orphaned records, unindexed FKs,
and generates stable fingerprints so dismissed findings never duplicate.
"""

import re
import hashlib
from typing import Dict, Any, List, Optional
from sqlalchemy import text
from sqlalchemy.engine import Engine

from services.app_db import StudioAppDB
from services.pii_detector import PIIDetector


SENTINEL_PATTERNS = [
    r"^000-00-0000$",
    r"^999-99-9999$",
    r"^1900-01-01",
    r"^1970-01-01",
    r"^-999$",
    r"^99999$",
    r"^n/a$",
    r"^unknown$",
    r"^none$",
    r"^test@test\.com$",
]


class HygieneDetector:
    def __init__(self, app_db: Optional[StudioAppDB] = None):
        self.app_db = app_db or StudioAppDB()

    def run_hygiene_audit(
        self,
        engine: Engine,
        snapshot: Dict[str, Any],
        connection_id: str,
    ) -> List[Dict[str, Any]]:
        """
        Executes comprehensive hygiene scan over database tables and persists new findings.
        """
        structure = snapshot.get("structure", snapshot)
        tables = structure.get("tables", [])
        findings = []

        # Load confirmed/inferred relationships from app DB to check orphans on discovered links
        inferred_by_table = {}
        snap_id = snapshot.get("id")
        if snap_id:
            try:
                with self.app_db._get_connection() as app_conn:
                    inf_rows = app_conn.execute(
                        "SELECT child_table, child_column, parent_table, parent_column FROM relationship_inferences WHERE snapshot_id = ? AND status != 'rejected';",
                        (snap_id,),
                    ).fetchall()
                    for r in inf_rows:
                        inferred_by_table.setdefault(r["child_table"], []).append({
                            "name": f"inferred_{r['child_column']}_{r['parent_table']}",
                            "constrained_columns": [r["child_column"]],
                            "referred_table": r["parent_table"],
                            "referred_columns": [r["parent_column"]],
                            "is_inferred": True,
                        })
            except Exception:
                pass

        with engine.connect() as conn:
            for tbl in tables:
                t_name = tbl["name"]
                cols = tbl.get("columns", [])
                fks = tbl.get("foreign_keys", [])
                indexes = tbl.get("indexes", [])

                # 1. Check Unindexed Foreign Keys
                indexed_cols = set()
                for idx in indexes:
                    for col in idx.get("column_names", []):
                        indexed_cols.add(col)

                for fk in fks:
                    for fk_col in fk.get("constrained_columns", []):
                        if fk_col not in indexed_cols:
                            fp = hashlib.sha256(f"unindexed_fk|{t_name}|{fk_col}".encode("utf-8")).hexdigest()
                            findings.append({
                                "connection_id": connection_id,
                                "kind": "unindexed_fk",
                                "severity": "warning",
                                "target": f"{t_name}.{fk_col}",
                                "summary": f"Foreign key column '{t_name}.{fk_col}' has no index, which may cause full-table scans on joins.",
                                "evidence": {"foreign_key": fk.get("name"), "references": fk.get("referred_table")},
                                "fix": {"suggested_sql": f"CREATE INDEX idx_{t_name}_{fk_col} ON {t_name}({fk_col});"},
                                "fingerprint": fp,
                            })

                # 2. Check Orphaned Records across declared and inferred foreign keys
                all_rel_fks = list(fks) + inferred_by_table.get(t_name, [])
                for fk in all_rel_fks:
                    ref_tbl = fk.get("referred_table")
                    for c_col, p_col in zip(fk.get("constrained_columns", []), fk.get("referred_columns", [])):
                        if ref_tbl and c_col and p_col:
                            try:
                                orphan_sql = f"""
                                    SELECT COUNT(*)
                                    FROM {t_name} c
                                    LEFT JOIN {ref_tbl} p ON c.{c_col} = p.{p_col}
                                    WHERE c.{c_col} IS NOT NULL AND p.{p_col} IS NULL;
                                """
                                orphan_count = conn.execute(text(orphan_sql)).scalar() or 0
                                if orphan_count > 0:
                                    fp = hashlib.sha256(f"orphans|{t_name}|{c_col}".encode("utf-8")).hexdigest()
                                    findings.append({
                                        "connection_id": connection_id,
                                        "kind": "orphans",
                                        "severity": "error",
                                        "target": f"{t_name}.{c_col}",
                                        "summary": f"Found {orphan_count} orphaned records in '{t_name}.{c_col}' with no matching record in '{ref_tbl}.{p_col}'.",
                                        "evidence": {"orphan_count": orphan_count, "parent_table": ref_tbl, "is_inferred": fk.get("is_inferred", False)},
                                        "fix": {"suggested_action": "Cleanse orphaned child records or assign to default parent."},
                                        "fingerprint": fp,
                                    })
                            except Exception:
                                pass

                # 3. Column-Level Scans (Null rates, Sentinels, Mixed Dates, PII)
                for col in cols:
                    c_name = col["name"]
                    c_type = col["type"]

                    try:
                        # Total count and null count
                        q_null = f"SELECT COUNT(*), COUNT({c_name}) FROM {t_name};"
                        row = conn.execute(text(q_null)).fetchone()
                        total_rows, non_null_rows = row[0] or 0, row[1] or 0
                        null_rows = total_rows - non_null_rows

                        if total_rows > 0:
                            null_ratio = float(null_rows) / float(total_rows)
                            # High null rate alert (> 80%)
                            if null_ratio >= 0.80 and not col.get("primary_key"):
                                fp = hashlib.sha256(f"high_null_rate|{t_name}|{c_name}".encode("utf-8")).hexdigest()
                                findings.append({
                                    "connection_id": connection_id,
                                    "kind": "high_null_rate",
                                    "severity": "info",
                                    "target": f"{t_name}.{c_name}",
                                    "summary": f"Column '{t_name}.{c_name}' has an extremely high null rate ({int(null_ratio * 100)}% nulls).",
                                    "evidence": {"null_count": null_rows, "total_rows": total_rows, "null_pct": round(null_ratio * 100, 1)},
                                    "fix": {"suggested_action": "Verify if column is obsolete or should be marked optional."},
                                    "fingerprint": fp,
                                })

                        # Text column inspections
                        if any(t in c_type for t in ("CHAR", "TEXT", "STRING")):
                            # Sample up to 100 non-null values
                            q_sample = f"SELECT DISTINCT {c_name} FROM {t_name} WHERE {c_name} IS NOT NULL LIMIT 100;"
                            sample_vals = [str(r[0]) for r in conn.execute(text(q_sample)).fetchall() if r[0] is not None]

                            # Sentinel value checks
                            detected_sentinels = []
                            for v in sample_vals:
                                for spat in SENTINEL_PATTERNS:
                                    if re.search(spat, v.strip(), re.IGNORECASE):
                                        detected_sentinels.append(v)
                                        break

                            if detected_sentinels:
                                fp = hashlib.sha256(f"sentinels|{t_name}|{c_name}".encode("utf-8")).hexdigest()
                                findings.append({
                                    "connection_id": connection_id,
                                    "kind": "sentinels",
                                    "severity": "warning",
                                    "target": f"{t_name}.{c_name}",
                                    "summary": f"Detected sentinel / placeholder values in '{t_name}.{c_name}': {', '.join(detected_sentinels[:3])}.",
                                    "evidence": {"samples": detected_sentinels[:5]},
                                    "fix": {"suggested_action": "Convert sentinels to NULL or clean placeholder entries."},
                                    "fingerprint": fp,
                                })

                            # Mixed date string format checks
                            date_formats_found = set()
                            for v in sample_vals:
                                v_clean = v.strip()
                                if re.match(r"^\d{4}-\d{2}-\d{2}$", v_clean):
                                    date_formats_found.add("YYYY-MM-DD")
                                elif re.match(r"^\d{2}/\d{2}/\d{4}$", v_clean):
                                    date_formats_found.add("MM/DD/YYYY")
                                elif re.match(r"^\d{2}-\d{2}-\d{4}$", v_clean):
                                    date_formats_found.add("DD-MM-YYYY")

                            if len(date_formats_found) > 1:
                                fp = hashlib.sha256(f"mixed_dates|{t_name}|{c_name}".encode("utf-8")).hexdigest()
                                findings.append({
                                    "connection_id": connection_id,
                                    "kind": "mixed_dates",
                                    "severity": "warning",
                                    "target": f"{t_name}.{c_name}",
                                    "summary": f"Column '{t_name}.{c_name}' contains mixed date string formats: {', '.join(date_formats_found)}.",
                                    "evidence": {"formats_detected": list(date_formats_found)},
                                    "fix": {"suggested_action": "Standardize date strings to ISO 8601 YYYY-MM-DD."},
                                    "fingerprint": fp,
                                })

                            # PII Detection check
                            pii_matches = PIIDetector.detect_pii_in_column(c_name, sample_vals)
                            if pii_matches.get("has_pii"):
                                fp = hashlib.sha256(f"pii|{t_name}|{c_name}".encode("utf-8")).hexdigest()
                                findings.append({
                                    "connection_id": connection_id,
                                    "kind": "pii",
                                    "severity": "error",
                                    "target": f"{t_name}.{c_name}",
                                    "summary": f"Column '{t_name}.{c_name}' appears to contain sensitive {pii_matches['detected_entity'].upper()} data.",
                                    "evidence": {"entity": pii_matches["detected_entity"], "confidence": pii_matches["confidence"]},
                                    "fix": {"suggested_action": "Ensure masking is enabled; review retention policies."},
                                    "fingerprint": fp,
                                })

                    except Exception:
                        continue

        # Save findings to App DB, respecting dismissed findings
        saved_findings = []
        with self.app_db._get_connection() as app_conn:
            # Query currently dismissed or accepted findings by fingerprint
            existing = {
                r["fingerprint"]: r["status"]
                for r in app_conn.execute("SELECT fingerprint, status FROM findings WHERE connection_id = ?;", (connection_id,)).fetchall()
            }

            for f in findings:
                fp = f["fingerprint"]
                if fp in existing and existing[fp] in ("dismissed", "accepted"):
                    # Respect user decision, do not recreate dismissed finding
                    continue

                import json
                import uuid
                f_id = f"find_{uuid.uuid4().hex[:10]}"
                f["id"] = f_id
                app_conn.execute(
                    """
                    INSERT OR REPLACE INTO findings (
                        id, connection_id, kind, severity, target, summary,
                        evidence_json, fix_json, status, fingerprint, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, datetime('now', 'utc'));
                    """,
                    (
                        f_id, connection_id, f["kind"], f["severity"], f["target"],
                        f["summary"], json.dumps(f.get("evidence", {})),
                        json.dumps(f.get("fix", {})), fp,
                    ),
                )
                saved_findings.append(f)
            app_conn.commit()

        return saved_findings
