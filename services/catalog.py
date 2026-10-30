"""
Autonomous Data & Schema Studio — Metadata Catalog, Snapshot Diffing & ERD Cartography.
Introspects schemas, detects schema drift via SHA-256 diffing, and generates graph topology.
"""

import json
import hashlib
from typing import Dict, Any, List, Optional, Tuple, Set
import sqlalchemy
from sqlalchemy import inspect
from sqlalchemy.engine import Engine

from services.app_db import StudioAppDB


class MetadataCatalog:
    def __init__(self, app_db: Optional[StudioAppDB] = None):
        self.app_db = app_db or StudioAppDB()

    def introspect_schema(self, engine: Engine) -> Dict[str, Any]:
        """
        Deep structural introspection across any engine (Postgres, SQLite, DuckDB).
        Returns a normalized JSON-serializable dictionary.
        """
        insp = inspect(engine)
        table_names = insp.get_table_names()

        tables_data = []
        for tbl in sorted(table_names):
            columns_data = []
            cols = insp.get_columns(tbl)
            pks = set(insp.get_pk_constraint(tbl).get("constrained_columns", []))

            for col in cols:
                c_name = col["name"]
                c_type = str(col.get("type", "TEXT")).upper()
                columns_data.append({
                    "name": c_name,
                    "type": c_type,
                    "nullable": bool(col.get("nullable", True)),
                    "primary_key": c_name in pks,
                    "default": str(col.get("default")) if col.get("default") is not None else None,
                })

            fks_data = []
            try:
                fks = insp.get_foreign_keys(tbl)
                for fk in fks:
                    fks_data.append({
                        "name": fk.get("name"),
                        "constrained_columns": fk.get("constrained_columns", []),
                        "referred_table": fk.get("referred_table"),
                        "referred_columns": fk.get("referred_columns", []),
                    })
            except Exception:
                fks_data = []

            indexes_data = []
            try:
                idxs = insp.get_indexes(tbl)
                for idx in idxs:
                    indexes_data.append({
                        "name": idx.get("name"),
                        "unique": bool(idx.get("unique", False)),
                        "column_names": idx.get("column_names", []),
                    })
            except Exception:
                indexes_data = []

            tables_data.append({
                "name": tbl,
                "columns": columns_data,
                "primary_keys": sorted(list(pks)),
                "foreign_keys": fks_data,
                "indexes": indexes_data,
            })

        return {
            "tables": tables_data,
            "table_count": len(tables_data),
            "column_count": sum(len(t["columns"]) for t in tables_data),
        }

    def capture_and_record_snapshot(
        self,
        connection_id: str,
        engine: Engine,
        server_version: Optional[str] = None,
        source: str = "refresh",
    ) -> str:
        """Introspects schema, computes canonical hash, and saves snapshot in app_db."""
        structure = self.introspect_schema(engine)
        snap_id = self.app_db.record_snapshot(
            connection_id=connection_id,
            structure=structure,
            server_version=server_version,
            source=source,
        )
        return snap_id

    @staticmethod
    def compute_snapshot_diff(
        snap_a: Dict[str, Any],
        snap_b: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Computes structural delta between two snapshots (Snapshot A -> Snapshot B).
        Identifies added/dropped tables, added/dropped columns, and type changes.
        """
        struct_a = snap_a.get("structure", snap_a)
        struct_b = snap_b.get("structure", snap_b)

        tables_a = {t["name"]: t for t in struct_a.get("tables", [])}
        tables_b = {t["name"]: t for t in struct_b.get("tables", [])}

        names_a = set(tables_a.keys())
        names_b = set(tables_b.keys())

        added_tables = sorted(list(names_b - names_a))
        dropped_tables = sorted(list(names_a - names_b))
        common_tables = sorted(list(names_a & names_b))

        modified_tables = {}

        for tbl in common_tables:
            t_a = tables_a[tbl]
            t_b = tables_b[tbl]

            cols_a = {c["name"]: c for c in t_a.get("columns", [])}
            cols_b = {c["name"]: c for c in t_b.get("columns", [])}

            c_names_a = set(cols_a.keys())
            c_names_b = set(cols_b.keys())

            added_cols = sorted(list(c_names_b - c_names_a))
            dropped_cols = sorted(list(c_names_a - c_names_b))
            common_cols = sorted(list(c_names_a & c_names_b))

            altered_cols = []
            for c_name in common_cols:
                col_a = cols_a[c_name]
                col_b = cols_b[c_name]
                if col_a["type"] != col_b["type"] or col_a["nullable"] != col_b["nullable"]:
                    altered_cols.append({
                        "name": c_name,
                        "old_type": col_a["type"],
                        "new_type": col_b["type"],
                        "old_nullable": col_a["nullable"],
                        "new_nullable": col_b["nullable"],
                    })

            if added_cols or dropped_cols or altered_cols:
                modified_tables[tbl] = {
                    "added_columns": added_cols,
                    "dropped_columns": dropped_cols,
                    "altered_columns": altered_cols,
                }

        has_changes = bool(added_tables or dropped_tables or modified_tables)

        return {
            "has_changes": has_changes,
            "added_tables": added_tables,
            "dropped_tables": dropped_tables,
            "modified_tables": modified_tables,
        }

    @staticmethod
    def generate_erd_graph(
        structure: Dict[str, Any],
        inferred_relationships: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Generates nodes and edges ready for interactive ERD rendering.
        Declared foreign keys render as solid lines; inferred relationships as dashed lines.
        """
        tables = structure.get("tables", [])
        nodes = []
        edges = []
        seen_edges: Set[str] = set()

        # Build nodes
        for idx, tbl in enumerate(tables):
            t_name = tbl["name"]
            nodes.append({
                "id": t_name,
                "label": t_name,
                "columns": [
                    {
                        "name": c["name"],
                        "type": c["type"],
                        "is_pk": c["primary_key"],
                    }
                    for c in tbl.get("columns", [])
                ],
                "primary_keys": tbl.get("primary_keys", []),
            })

            # Declared Foreign Keys
            for fk in tbl.get("foreign_keys", []):
                ref_tbl = fk.get("referred_table")
                if not ref_tbl:
                    continue

                for col, ref_col in zip(fk.get("constrained_columns", []), fk.get("referred_columns", [])):
                    edge_id = f"edge_decl_{tbl['name']}_{ref_tbl}_{col}_{ref_col}"
                    if edge_id not in seen_edges:
                        seen_edges.add(edge_id)
                        edges.append({
                            "id": edge_id,
                            "source": ref_tbl,
                            "target": tbl["name"],
                            "source_column": ref_col,
                            "target_column": col,
                            "kind": "declared",
                            "label": f"{col} → {ref_tbl}.{ref_col}",
                            "animated": False,
                        })

        # Inferred Relationships
        if inferred_relationships:
            for rel in inferred_relationships:
                p_tbl = rel.get("parent_table")
                p_col = rel.get("parent_column")
                c_tbl = rel.get("child_table")
                c_col = rel.get("child_column")
                score = rel.get("score", 0.0)

                if p_tbl and c_tbl and p_col and c_col:
                    edge_id = f"edge_inf_{c_tbl}_{p_tbl}_{c_col}_{p_col}"
                    if edge_id not in seen_edges:
                        seen_edges.add(edge_id)
                        edges.append({
                            "id": edge_id,
                            "source": p_tbl,
                            "target": c_tbl,
                            "source_column": p_col,
                            "target_column": c_col,
                            "kind": "inferred",
                            "label": f"Inferred ({int(score * 100)}%): {c_col} → {p_tbl}.{p_col}",
                            "animated": True,
                        })

        return {
            "nodes": nodes,
            "edges": edges,
            "node_count": len(nodes),
            "edge_count": len(edges),
        }
