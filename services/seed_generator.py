"""
Autonomous Data & Schema Studio — Topological Synthetic Seed Generator.
Sorts tables in relational dependency order, resolves cycles, preserves foreign key integrity,
and generates realistic test data using Faker without leaking production PII.
"""

import random
from typing import Dict, Any, List, Optional, Set
from collections import defaultdict, deque
from sqlalchemy import text
from sqlalchemy.engine import Engine

try:
    from faker import Faker
    fake = Faker()
except ImportError:
    fake = None


class SeedGenerator:
    def __init__(self, seed: int = 42):
        self.seed = seed
        random.seed(seed)
        if fake:
            Faker.seed(seed)

    @staticmethod
    def topological_sort_tables(structure: Dict[str, Any]) -> List[str]:
        """
        Sorts tables so parent tables appear before child tables (respecting FK dependencies).
        Handles circular dependencies using Kahn's algorithm with cycle breaking.
        """
        tables = structure.get("tables", [])
        all_table_names = [t["name"] for t in tables]
        all_set = set(all_table_names)

        in_degree: Dict[str, int] = {t: 0 for t in all_table_names}
        adj_list: Dict[str, Set[str]] = defaultdict(set)

        # Build dependency edges: parent -> child
        for tbl in tables:
            child = tbl["name"]
            for fk in tbl.get("foreign_keys", []):
                parent = fk.get("referred_table")
                if parent and parent in all_set and parent != child:
                    if child not in adj_list[parent]:
                        adj_list[parent].add(child)
                        in_degree[child] += 1

        # Kahn's algorithm
        queue = deque([t for t, deg in in_degree.items() if deg == 0])
        ordered = []

        while queue:
            node = queue.popleft()
            ordered.append(node)

            for neighbor in adj_list[node]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        # If cycles exist, append remaining nodes
        if len(ordered) < len(all_table_names):
            remaining = [t for t in all_table_names if t not in ordered]
            ordered.extend(remaining)

        return ordered

    def build_generation_plan(
        self,
        structure: Dict[str, Any],
        row_counts: Optional[Dict[str, int]] = None,
    ) -> Dict[str, Any]:
        """
        Creates a table-by-table generation plan in topological order.
        """
        default_counts = row_counts or {}
        ordered_tables = self.topological_sort_tables(structure)
        tables_map = {t["name"]: t for t in structure.get("tables", [])}

        plan_tables = []
        for t_name in ordered_tables:
            tbl = tables_map.get(t_name, {})
            desired_rows = default_counts.get(t_name, 10)

            col_generators = {}
            for col in tbl.get("columns", []):
                c_name = col["name"]
                c_type = col["type"].upper()
                c_lower = c_name.lower()

                # FK check
                is_fk = False
                for fk in tbl.get("foreign_keys", []):
                    if c_name in fk.get("constrained_columns", []):
                        is_fk = True
                        ref_tbl = fk.get("referred_table")
                        ref_col = fk.get("referred_columns", ["id"])[0]
                        col_generators[c_name] = f"fk_reference({ref_tbl}.{ref_col})"
                        break

                if is_fk:
                    continue

                if col.get("primary_key"):
                    col_generators[c_name] = "primary_key_sequence"
                elif any(kw in c_lower for kw in ("email", "mail")):
                    col_generators[c_name] = "faker.email"
                elif any(kw in c_lower for kw in ("name", "first_name", "last_name")):
                    col_generators[c_name] = "faker.name"
                elif any(kw in c_lower for kw in ("phone", "mobile", "tel")):
                    col_generators[c_name] = "faker.phone_number"
                elif any(kw in c_lower for kw in ("address", "city", "state", "street")):
                    col_generators[c_name] = "faker.address"
                elif any(t in c_type for t in ("INT", "SERIAL")):
                    col_generators[c_name] = "random_integer(1, 1000)"
                elif any(t in c_type for t in ("NUMERIC", "REAL", "FLOAT", "DOUBLE", "DECIMAL")):
                    col_generators[c_name] = "random_float(10.0, 500.0)"
                elif any(t in c_type for t in ("DATE", "TIME")):
                    col_generators[c_name] = "random_date('2023-01-01', '2026-01-01')"
                elif any(t in c_type for t in ("BOOL",)):
                    col_generators[c_name] = "random_boolean"
                else:
                    col_generators[c_name] = "random_text(8)"

            plan_tables.append({
                "table": t_name,
                "target_rows": desired_rows,
                "generators": col_generators,
            })

        return {
            "topological_order": ordered_tables,
            "tables": plan_tables,
        }

    def generate_data(
        self,
        structure: Dict[str, Any],
        row_counts: Optional[Dict[str, int]] = None,
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Generates realistic data rows for each table, maintaining foreign key references.
        """
        plan = self.build_generation_plan(structure, row_counts)
        tables_map = {t["name"]: t for t in structure.get("tables", [])}

        generated_data: Dict[str, List[Dict[str, Any]]] = {}
        pk_pools: Dict[str, List[Any]] = defaultdict(list)

        for p_tbl in plan["tables"]:
            t_name = p_tbl["table"]
            target_rows = p_tbl["target_rows"]
            tbl_meta = tables_map.get(t_name, {})
            cols = tbl_meta.get("columns", [])

            # Foreign key lookup map: col_name -> (referred_table, referred_col)
            fk_lookup = {}
            for fk in tbl_meta.get("foreign_keys", []):
                ref_t = fk.get("referred_table")
                for c, r in zip(fk.get("constrained_columns", []), fk.get("referred_columns", [])):
                    if ref_t:
                        fk_lookup[c] = (ref_t, r)

            rows = []
            for row_idx in range(1, target_rows + 1):
                row_dict = {}
                for col in cols:
                    c_name = col["name"]
                    c_type = col["type"].upper()
                    c_lower = c_name.lower()

                    # 1. Primary key
                    if col.get("primary_key"):
                        val = row_idx
                        pk_pools[t_name].append(val)
                    # 2. Foreign key reference
                    elif c_name in fk_lookup:
                        ref_t, ref_c = fk_lookup[c_name]
                        parent_ids = pk_pools.get(ref_t, [1])
                        val = random.choice(parent_ids) if parent_ids else 1
                    # 3. PII Fields (Faker)
                    elif fake and any(kw in c_lower for kw in ("email", "mail")):
                        val = fake.email()
                    elif fake and any(kw in c_lower for kw in ("name", "first_name", "last_name")):
                        val = fake.name()
                    elif fake and any(kw in c_lower for kw in ("phone", "tel")):
                        val = fake.phone_number()
                    elif fake and any(kw in c_lower for kw in ("address", "city", "street")):
                        val = fake.city()
                    # 4. Standard primitives
                    elif any(t in c_type for t in ("INT", "SERIAL")):
                        val = random.randint(1, 100)
                    elif any(t in c_type for t in ("NUMERIC", "REAL", "FLOAT", "DOUBLE", "DECIMAL")):
                        val = round(random.uniform(5.0, 300.0), 2)
                    elif any(t in c_type for t in ("DATE", "TIME")):
                        val = f"2024-{random.randint(1,12):02d}-{random.randint(1,28):02d}"
                    elif any(t in c_type for t in ("BOOL",)):
                        val = random.choice([True, False])
                    else:
                        val = f"{c_name}_{row_idx}"

                    row_dict[c_name] = val
                rows.append(row_dict)

            generated_data[t_name] = rows

        return generated_data

    def generate_sql_inserts(
        self,
        structure: Dict[str, Any],
        row_counts: Optional[Dict[str, int]] = None,
    ) -> str:
        """Emits valid ordered SQL INSERT statements satisfying all foreign key constraints."""
        data = self.generate_data(structure, row_counts)
        ordered_tables = self.topological_sort_tables(structure)

        insert_statements = []
        for t_name in ordered_tables:
            rows = data.get(t_name, [])
            if not rows:
                continue

            for r in rows:
                cols = list(r.keys())
                col_str = ", ".join(cols)
                val_parts = []
                for c in cols:
                    v = r[c]
                    if v is None:
                        val_parts.append("NULL")
                    elif isinstance(v, (int, float)):
                        val_parts.append(str(v))
                    elif isinstance(v, bool):
                        val_parts.append("1" if v else "0")
                    else:
                        safe_str = str(v).replace("'", "''")
                        val_parts.append(f"'{safe_str}'")

                val_str = ", ".join(val_parts)
                insert_statements.append(f"INSERT INTO {t_name} ({col_str}) VALUES ({val_str});")

        return "\n".join(insert_statements)


seed_generator = SeedGenerator()
