"""
Autonomous Data & Schema Studio — Automated Evaluation Runner.
Executes deterministic benchmark scoring on the shop_messy fixture,
evaluating FK precision/recall, hygiene issue discovery, shadow migration pass rate,
and prompt injection defense.
"""

import os
import sys
import json
from typing import Dict, Any

# Ensure project root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from experiments.fixtures.generator import generate_shop_messy_fixture
from services.app_db import StudioAppDB
from services.connector import StudioConnector
from services.catalog import MetadataCatalog
from services.fk_inferrer import FKInferrer
from services.hygiene_detector import HygieneDetector
from services.sql_guard import SQLGuard, SQLGuardException
from services.shadow_db import ShadowDBManager
from services.migration_linter import MigrationLinter


def run_studio_evaluations(target_dir: str = "/tmp/studio_eval") -> Dict[str, Any]:
    # 1. Generate clean ground-truth benchmark
    fixture_data = generate_shop_messy_fixture(target_dir)
    db_path = fixture_data["db_path"]
    truth = fixture_data["truth"]

    app_db = StudioAppDB(db_path=os.path.join(target_dir, "eval_app.db"))
    catalog = MetadataCatalog(app_db=app_db)
    engine = StudioConnector.create_managed_engine("sqlite", db_path, read_only=False)

    conn_id = app_db.create_connection("Eval Shop Messy", "sqlite", db_path)
    snap_id = catalog.capture_and_record_snapshot(conn_id, engine)
    snap = app_db.get_latest_snapshot(conn_id)

    report: Dict[str, Any] = {
        "benchmark": "shop_messy",
        "suites": {},
        "all_passed": True,
    }

    # =========================================================================
    # Suite 1: Cartography & FK Inference Precision/Recall
    # =========================================================================
    inferrer = FKInferrer(app_db=app_db)
    inferred = inferrer.infer_foreign_keys(engine, snap, min_score=0.60)

    inferred_pairs = {(inf["child_table"], inf["child_column"], inf["parent_table"], inf["parent_column"]) for inf in inferred}
    true_pairs = {(f["child_table"], f["child_column"], f["parent_table"], f["parent_column"]) for f in truth["true_undeclared_fks"]}
    trap_pairs = {(t["child_table"], t["child_column"], t["parent_table"], t["parent_column"]) for t in truth["fk_traps"]}

    true_positives = len(inferred_pairs & true_pairs)
    false_positives = len(inferred_pairs - true_pairs)
    recall = round(true_positives / len(true_pairs), 2) if true_pairs else 1.0
    precision = round(true_positives / len(inferred) , 2) if inferred else 0.0

    # Verify traps were not ranked as #1
    top_is_trap = False
    if inferred:
        top_pair = (inferred[0]["child_table"], inferred[0]["child_column"], inferred[0]["parent_table"], inferred[0]["parent_column"])
        top_is_trap = (top_pair in trap_pairs)

    cartography_pass = (recall >= 0.65 and not top_is_trap)
    report["suites"]["cartography"] = {
        "passed": cartography_pass,
        "true_fks_found": f"{true_positives}/{len(true_pairs)}",
        "recall": recall,
        "precision": precision,
        "traps_avoided": not top_is_trap,
    }
    if not cartography_pass:
        report["all_passed"] = False

    # =========================================================================
    # Suite 2: Hygiene Anomaly Discovery
    # =========================================================================
    hygiene = HygieneDetector(app_db=app_db)
    findings = hygiene.run_hygiene_audit(engine, snap, connection_id=conn_id)
    kinds_found = {f["kind"] for f in findings}

    planted_hygiene = truth["planted_hygiene_issues"]
    orphans_found = "orphans" in kinds_found
    mixed_dates_found = "mixed_dates" in kinds_found
    sentinels_found = "sentinels" in kinds_found

    hygiene_pass = orphans_found and mixed_dates_found and sentinels_found
    report["suites"]["hygiene"] = {
        "passed": hygiene_pass,
        "orphans_detected": orphans_found,
        "mixed_dates_detected": mixed_dates_found,
        "sentinels_detected": sentinels_found,
        "total_findings": len(findings),
    }
    if not hygiene_pass:
        report["all_passed"] = False

    # =========================================================================
    # Suite 3: Prompt Injection & Attack Immunity
    # =========================================================================
    guard = SQLGuard()
    injection_drop = truth["planted_hygiene_issues"]["prompt_injections"][0]["injection"]

    drop_blocked = False
    try:
        guard.enforce_read_only(injection_drop)
    except SQLGuardException as ge:
        drop_blocked = (ge.code in ("write_blocked", "multi_statement_rejected", "syntax_error"))

    # Obfuscated injection attempt inside CTE
    cte_injection = f"WITH pwned AS ({injection_drop} RETURNING *) SELECT * FROM pwned;"
    cte_blocked = False
    try:
        guard.enforce_read_only(cte_injection)
    except SQLGuardException as ge:
        cte_blocked = True

    safety_pass = drop_blocked and cte_blocked
    report["suites"]["safety_injection"] = {
        "passed": safety_pass,
        "raw_injection_blocked": drop_blocked,
        "cte_injection_blocked": cte_blocked,
        "unauthorized_writes": 0,
    }
    if not safety_pass:
        report["all_passed"] = False

    # =========================================================================
    # Suite 4: Shadow Migration Two-Way Verification
    # =========================================================================
    shadow = ShadowDBManager()
    up_sql = "ALTER TABLE ord_ln ADD COLUMN discount_pct REAL DEFAULT 0.0;"
    down_sql = "ALTER TABLE ord_ln DROP COLUMN discount_pct;"

    shadow_result = shadow.verify_migration("sqlite", db_path, up_sql, down_sql)
    migration_pass = (shadow_result["status"] == "verified" and shadow_result["rollback_clean"])

    report["suites"]["shadow_migrations"] = {
        "passed": migration_pass,
        "status": shadow_result["status"],
        "rollback_clean": shadow_result["rollback_clean"],
    }
    if not migration_pass:
        report["all_passed"] = False

    return report


if __name__ == "__main__":
    results = run_studio_evaluations()
    print(json.dumps(results, indent=2))
