"""
Output Refinement & Cognitive Polish Engine (Squad C - Agentic Intelligence).

Elevates agent responses from plain SQL snippets to sharp, executive-grade intelligence
(similar to Cursor, Julius AI, and Hex Magic) through a 3-pass reasoning pipeline:

- Pass 1: Schema Grounding & Self-Correction:
  * Inspects SQL against the active database schema (db_manager.get_schema()).
  * Detects hallucinated or slightly misspelled column/table names and auto-corrects them
    using fuzzy matching against actual schema columns.
  * Verifies dialect compliance (DuckDB vs PostgreSQL vs SQLite).

- Pass 2: Executive Polish & Cognitive Framing:
  * Eliminates conversational filler (e.g., "Sure, here is the SQL query you asked for...").
  * Formats output with a punchy direct headline / key finding.
  * Cleanly wraps executable SQL in ```sql:executable.
  * Adds an "Analytical Lens" / Key Takeaways section explaining what patterns or metrics
    this query reveals.

- Pass 3: Interactive Next-Action Synthesis:
  * Generates 2-3 high-value, contextual follow-up questions/actions
    (e.g., "Filter by status = 'completed'", "Break down by month", "Export cleaned view as CSV").
  * Formats these as actionable suggestion chips:
    <!-- suggestions: ["Filter by status = 'completed'", "Break down by month", "Export cleaned view as CSV"] -->
"""

import difflib
import json
import re
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from core.db_models import DatabaseSchemaResponse, TableSchema
from services.nl_sql import parse_schema_context


SQL_KEYWORDS: Set[str] = {
    "select", "from", "where", "join", "inner", "left", "right", "full", "cross", "natural",
    "on", "using", "group", "by", "order", "asc", "desc", "limit", "offset", "as", "and", "or",
    "not", "in", "is", "null", "like", "ilike", "between", "exists", "having", "union", "all",
    "distinct", "case", "when", "then", "else", "end", "with", "count", "sum", "avg", "min",
    "max", "coalesce", "cast", "over", "partition", "row_number", "rank", "dense_rank", "lag",
    "lead", "first_value", "last_value", "round", "floor", "ceil", "trim", "lower", "upper",
    "substr", "substring", "concat", "replace", "length", "len", "abs", "true", "false",
    "table", "view", "index", "values", "into", "insert", "update", "delete", "drop", "alter",
    "create", "truncate", "rename", "add", "column", "set", "primary", "key", "foreign",
    "references", "constraint", "default", "cascade", "restrict", "strftime", "date_trunc",
    "to_char", "date", "year", "month", "day", "hour", "minute", "second", "now", "interval"
}

COMMON_SYNONYMS: Dict[str, str] = {
    "cust_id": "customer_id",
    "clnt_id": "customer_id",
    "client_id": "customer_id",
    "user_id": "customer_id",
    "cust_name": "name",
    "customer_name": "name",
    "prod_name": "product_name",
    "prod_id": "product_id",
    "item_id": "product_id",
    "qty": "quantity",
    "stock": "stock_quantity",
    "amt": "amount",
    "amont": "amount",
    "tot_amt": "total_amount",
    "tot_amount": "total_amount",
    "totl_amount": "total_amount",
    "createdat": "created_at",
    "updatedat": "updated_at",
    "orderdate": "order_date",
    "ord_date": "order_date",
    "statuss": "status",
    "order_statuss": "order_status",
    "lead_statuss": "lead_status",
    "desc": "description",
    "descr": "description",
    "addr": "address",
    "num": "number",
    "pct": "percentage",
    "catgory": "category",
    "categ": "category",
}


class OutputRefiner:
    """
    Intelligent Multi-Pass Output Refinement Engine.
    Elevates raw agent outputs into schema-grounded, executive-grade intelligence.
    """

    def __init__(self, db_manager: Optional[Any] = None):
        self._db_manager = db_manager

    @classmethod
    def refine(
        cls,
        raw_text: str,
        schema: Optional[Union[DatabaseSchemaResponse, Dict[str, Any], List[str], str]] = None,
        dialect: Optional[str] = None,
        prompt: Optional[str] = "",
        safety_mode: str = "read_only",
    ) -> str:
        """
        Public classmethod to refine agent text through the 3-pass reasoning pipeline.
        """
        instance = cls()
        return instance.process(
            raw_text=raw_text,
            schema=schema,
            dialect=dialect,
            prompt=prompt or "",
            safety_mode=safety_mode,
        )

    def process(
        self,
        raw_text: str,
        schema: Optional[Union[DatabaseSchemaResponse, Dict[str, Any], List[str], str]] = None,
        dialect: Optional[str] = None,
        prompt: str = "",
        safety_mode: str = "read_only",
    ) -> str:
        """
        Executes the 3-pass reasoning pipeline.
        """
        if not raw_text or not raw_text.strip():
            return ""

        # Normalize schema context
        schema_map = self._resolve_schema_map(schema)
        target_dialect = self._resolve_dialect(dialect)

        # Pass 1: Schema Grounding & Self-Correction
        grounded_text, extracted_queries = self.pass1_schema_grounding(
            text=raw_text,
            schema_map=schema_map,
            dialect=target_dialect,
        )

        # Pass 2: Executive Polish & Cognitive Framing
        polished_text = self.pass2_executive_polish(
            text=grounded_text,
            prompt=prompt,
            schema_map=schema_map,
            safety_mode=safety_mode,
            extracted_queries=extracted_queries,
        )

        # Pass 3: Interactive Next-Action Synthesis
        final_text = self.pass3_action_synthesis(
            text=polished_text,
            prompt=prompt,
            schema_map=schema_map,
            extracted_queries=extracted_queries,
        )

        return final_text

    # --------------------------------------------------------------------------
    # PASS 1: Schema Grounding & Self-Correction
    # --------------------------------------------------------------------------
    def pass1_schema_grounding(
        self,
        text: str,
        schema_map: Dict[str, Dict[str, Any]],
        dialect: str,
    ) -> Tuple[str, List[str]]:
        """
        Pass 1:
        - Inspects SQL queries inside code blocks (and plain text queries if unescaped).
        - Corrects misspelled or hallucinated table and column names using fuzzy matching.
        - Verifies dialect compliance (DuckDB vs PostgreSQL vs SQLite).
        """
        extracted_queries: List[str] = []

        # Find code blocks ```lang ... ```
        code_block_pattern = r"```([a-zA-Z0-9_:-]*)[^\S\r\n]*\r?\n([\s\S]*?)```"
        matches = list(re.finditer(code_block_pattern, text))

        if matches:
            # Reconstruct text replacing SQL inside blocks
            parts = []
            last_idx = 0
            for m in matches:
                parts.append(text[last_idx:m.start()])
                lang = m.group(1).strip().lower()
                code_content = m.group(2)

                if "sql" in lang or not lang:
                    # Ground and correct this SQL
                    corrected_sql = self._ground_and_correct_sql(
                        sql=code_content,
                        schema_map=schema_map,
                        dialect=dialect,
                    )
                    extracted_queries.append(corrected_sql.strip())
                    parts.append(f"```{lang}\n{corrected_sql.strip()}\n```")
                else:
                    parts.append(m.group(0))
                last_idx = m.end()
            parts.append(text[last_idx:])
            grounded_text = "".join(parts)
        else:
            # Check if text contains a naked SQL query (e.g., SELECT ... FROM ...)
            naked_sql_match = re.search(
                r"(SELECT\s+[\s\S]+?FROM\s+[a-zA-Z0-9_]+[\s\S]*?;?)",
                text,
                re.IGNORECASE,
            )
            if naked_sql_match:
                raw_sql = naked_sql_match.group(1)
                corrected_sql = self._ground_and_correct_sql(
                    sql=raw_sql,
                    schema_map=schema_map,
                    dialect=dialect,
                )
                extracted_queries.append(corrected_sql.strip())
                grounded_text = (
                    text[:naked_sql_match.start()]
                    + f"```sql:executable\n{corrected_sql.strip()}\n```"
                    + text[naked_sql_match.end():]
                )
            else:
                grounded_text = text

        return grounded_text, extracted_queries

    def _ground_and_correct_sql(
        self,
        sql: str,
        schema_map: Dict[str, Dict[str, Any]],
        dialect: str,
    ) -> str:
        """
        Inspects SQL against schema, performs fuzzy typo correction, and enforces dialect compliance.
        """
        if not schema_map:
            return self._enforce_dialect_compliance(sql, dialect)

        working_sql = sql

        # 1. Identify and Correct Table Names
        table_replacements: Dict[str, str] = {}
        all_schema_tables = list(schema_map.keys())

        # Match table occurrences after FROM, JOIN, UPDATE, INTO, TABLE
        table_pattern = r"\b(FROM|JOIN|UPDATE|INTO|TABLE)\s+([a-zA-Z0-9_]+)"
        for match in re.finditer(table_pattern, working_sql, re.IGNORECASE):
            tbl_token = match.group(2)
            tbl_token_lower = tbl_token.lower()

            if tbl_token_lower in schema_map:
                continue

            # Fuzzy match table against schema tables
            best_table = self._find_best_table_match(tbl_token_lower, all_schema_tables)
            if best_table and best_table != tbl_token:
                real_table_name = schema_map[best_table].get("name", best_table)
                table_replacements[tbl_token] = real_table_name

        if table_replacements:
            working_sql = self._replace_outside_quotes(working_sql, table_replacements)

        # 2. Identify tables active in this query
        active_tables: Set[str] = set()
        for t_name in all_schema_tables:
            if re.search(r"\b" + re.escape(t_name) + r"\b", working_sql, re.IGNORECASE):
                active_tables.add(t_name)

        # Build candidate column pool for active tables (or fallback to all tables)
        target_tables = active_tables if active_tables else set(all_schema_tables)
        candidate_columns: Dict[str, str] = {}  # col_lower -> exact_col_name
        for t in target_tables:
            for col in schema_map.get(t, {}).get("columns", []):
                col_name = col.get("name", "")
                if col_name:
                    candidate_columns[col_name.lower()] = col_name

        # 3. Detect and Correct Column Typos
        column_replacements: Dict[str, str] = {}

        # Scan for identifiers in SQL
        id_pattern = r"\b([a-zA-Z_][a-zA-Z0-9_]*)\b"
        tokens = re.findall(id_pattern, working_sql)

        for token in tokens:
            token_lower = token.lower()

            # Ignore SQL reserved words, numbers, or table names/aliases
            if token_lower in SQL_KEYWORDS:
                continue
            if token_lower in all_schema_tables:
                continue
            if token_lower in candidate_columns:
                # Exact column match
                continue

            # Check if this identifier is a misspelled column
            best_col = self._find_best_column_match(token, list(candidate_columns.values()))
            if best_col and best_col.lower() != token_lower:
                column_replacements[token] = best_col

        if column_replacements:
            working_sql = self._replace_outside_quotes(working_sql, column_replacements)

        # 4. Enforce Dialect Compliance
        working_sql = self._enforce_dialect_compliance(working_sql, dialect)

        return working_sql

    def _find_best_table_match(self, table_name: str, candidates: List[str]) -> Optional[str]:
        """Fuzzy match table name against schema tables."""
        t_lower = table_name.lower()

        # Plural / singular simple match
        if t_lower + "s" in candidates:
            return t_lower + "s"
        if t_lower.endswith("s") and t_lower[:-1] in candidates:
            return t_lower[:-1]

        # difflib close match
        matches = difflib.get_close_matches(t_lower, candidates, n=1, cutoff=0.55)
        if matches:
            return matches[0]

        return None

    def _find_best_column_match(self, col_name: str, candidates: List[str]) -> Optional[str]:
        """Fuzzy match column name against schema columns, considering synonyms and typos."""
        c_lower = col_name.lower()

        # 1. Check known synonym / typo dictionary
        if c_lower in COMMON_SYNONYMS:
            syn = COMMON_SYNONYMS[c_lower]
            for cand in candidates:
                if cand.lower() == syn.lower() or syn.lower() in cand.lower():
                    return cand

        # 2. Check prefix/suffix stripping (e.g. cust_name -> name)
        for cand in candidates:
            cand_lower = cand.lower()
            if cand_lower == c_lower:
                return cand
            # e.g., token is 'name' and candidate is 'customer_name'
            if cand_lower.endswith("_" + c_lower) or c_lower.endswith("_" + cand_lower):
                return cand

        # 3. difflib close match
        cand_map = {c.lower(): c for c in candidates}
        matches = difflib.get_close_matches(c_lower, list(cand_map.keys()), n=1, cutoff=0.60)
        if matches:
            return cand_map[matches[0]]

        return None

    def _enforce_dialect_compliance(self, sql: str, dialect: str) -> str:
        """
        Enforces target dialect syntax compatibility across DuckDB, PostgreSQL, and SQLite.
        """
        d = (dialect or "duckdb").lower()
        res = sql

        # 1. Convert SQL Server 'TOP n' to standard 'LIMIT n'
        top_match = re.search(r"SELECT\s+TOP\s+(\d+)\s+(.+?)\s+FROM\s+", res, re.IGNORECASE | re.DOTALL)
        if top_match:
            limit_n = top_match.group(1)
            cols = top_match.group(2)
            res = re.sub(
                r"SELECT\s+TOP\s+\d+\s+" + re.escape(cols),
                f"SELECT {cols}",
                res,
                flags=re.IGNORECASE,
            )
            if not re.search(r"\bLIMIT\s+\d+", res, re.IGNORECASE):
                res = res.rstrip("; \t\n") + f" LIMIT {limit_n};"

        # 2. SQLite Dialect adjustments
        if "sqlite" in d:
            # Convert date_trunc('month', col) -> strftime('%Y-%m-01', col)
            res = re.sub(
                r"date_trunc\s*\(\s*['\"]month['\"]\s*,\s*([a-zA-Z0-9_.]+)\s*\)",
                r"strftime('%Y-%m-01', \1)",
                res,
                flags=re.IGNORECASE,
            )
            res = re.sub(
                r"date_trunc\s*\(\s*['\"]year['\"]\s*,\s*([a-zA-Z0-9_.]+)\s*\)",
                r"strftime('%Y-01-01', \1)",
                res,
                flags=re.IGNORECASE,
            )
            # ILIKE -> LIKE in SQLite
            res = re.sub(r"\bILIKE\b", "LIKE", res, flags=re.IGNORECASE)

        # 3. PostgreSQL Dialect adjustments
        elif "postgres" in d:
            # Convert strftime(col, '%Y-%m') or strftime('%Y-%m', col) -> to_char(col, 'YYYY-MM')
            res = re.sub(
                r"strftime\s*\(\s*([a-zA-Z0-9_.]+)\s*,\s*['\"]%Y-%m['\"]\s*\)",
                r"to_char(\1, 'YYYY-MM')",
                res,
                flags=re.IGNORECASE,
            )
            res = re.sub(
                r"strftime\s*\(\s*['\"]%Y-%m['\"]\s*,\s*([a-zA-Z0-9_.]+)\s*\)",
                r"to_char(\1, 'YYYY-MM')",
                res,
                flags=re.IGNORECASE,
            )
            # IFNULL -> COALESCE
            res = re.sub(r"\bIFNULL\s*\(", "COALESCE(", res, flags=re.IGNORECASE)

        # 4. DuckDB Dialect adjustments
        else:
            # DuckDB universal COALESCE
            res = re.sub(r"\bIFNULL\s*\(", "COALESCE(", res, flags=re.IGNORECASE)

        return res

    def _replace_outside_quotes(self, text: str, replacements: Dict[str, str]) -> str:
        """
        Replaces word-bounded tokens in text strictly outside single-quoted string literals.
        """
        if not replacements:
            return text

        pattern = r"('(?:''|[^'])*')"
        tokens = re.split(pattern, text)
        parts = []

        for i, token in enumerate(tokens):
            if i % 2 == 1:
                # Inside single quotes: preserve exactly
                parts.append(token)
            else:
                modified = token
                for old_w, new_w in replacements.items():
                    modified = re.sub(
                        r"\b" + re.escape(old_w) + r"\b",
                        new_w,
                        modified,
                        flags=re.IGNORECASE,
                    )
                parts.append(modified)

        return "".join(parts)

    # --------------------------------------------------------------------------
    # PASS 2: Executive Polish & Cognitive Framing
    # --------------------------------------------------------------------------
    def pass2_executive_polish(
        self,
        text: str,
        prompt: str,
        schema_map: Dict[str, Dict[str, Any]],
        safety_mode: str,
        extracted_queries: List[str],
    ) -> str:
        """
        Pass 2:
        - Eliminates conversational filler ("Sure, here is...").
        - Ensures a punchy direct headline / key finding.
        - Cleanly wraps executable SQL in ```sql:executable.
        - Adds an "Analytical Lens" / Key Takeaways section.
        """
        # 1. Eliminate Conversational Filler
        cleaned = self._strip_conversational_filler(text)

        # 2. Ensure Executable Code Blocks
        # In read_only mode, mutating queries stay in ```sql (never executable)
        cleaned = self._normalize_executable_blocks(cleaned, safety_mode)

        # 3. Ensure Punchy Direct Headline
        has_h3 = bool(re.search(r"^###\s+", cleaned, re.MULTILINE))
        has_h2 = bool(re.search(r"^##\s+", cleaned, re.MULTILINE))
        has_h1 = bool(re.search(r"^#\s+", cleaned, re.MULTILINE))

        if not (has_h1 or has_h2 or has_h3):
            headline = self._synthesize_headline(prompt, extracted_queries, schema_map)
            cleaned = f"{headline}\n\n{cleaned}"

        # 4. Ensure Analytical Lens / Key Takeaways Section
        has_lens = bool(
            re.search(
                r"(###|####)?\s*(🔍\s*)?(Analytical Lens|Key Takeaways|Executive Summary)",
                cleaned,
                re.IGNORECASE,
            )
        )
        if not has_lens and extracted_queries:
            lens_section = self._synthesize_analytical_lens(
                prompt=prompt,
                sql=extracted_queries[0] if extracted_queries else "",
                schema_map=schema_map,
            )
            # Insert before suggestion tag if present, else at the end
            sugg_idx = cleaned.find("<!-- suggestions:")
            if sugg_idx != -1:
                cleaned = (
                    cleaned[:sugg_idx].rstrip()
                    + f"\n\n{lens_section}\n\n"
                    + cleaned[sugg_idx:]
                )
            else:
                cleaned = cleaned.rstrip() + f"\n\n{lens_section}"

        return cleaned.strip()

    def _strip_conversational_filler(self, text: str) -> str:
        """Strips pleasantries and conversational preambles from assistant output."""
        filler_lead_patterns = [
            r"^(?:Sure|Certainly|Of course|Gladly|Hello|Hi|Hey|Great)[!,.]?\s*",
            r"^(?:I'd be happy to help(?: you with that)?|I would be glad to help)[!,.]?\s*",
            r"^(?:Here is|Here's|Below is|Following is|I have generated|I've generated|This is)\s+(?:the\s+)?(?:optimized\s+|executable\s+)?(?:SQL\s+query|query|result|code|script|recipe|solution)(?:\s+you asked for|\s+you requested|\s+to answer your question|\s+based on your schema)?(?:[:.]|\s+to\s+.*?:)?\s*",
            r"^As an AI(?: assistant)?,?.*?(?:[:.]\s*|\n+)",
            r"^In response to your (?:request|question)[!,.:]?\s*",
            r"^To answer your question,?\s*",
        ]

        lines = text.strip().split("\n")
        cleaned_lines = []
        stripping = True

        for line in lines:
            trimmed = line.strip()
            if stripping:
                if not trimmed:
                    continue
                # Keep stripping matching filler prefixes in a loop
                progress = True
                while progress:
                    progress = False
                    for fp in filler_lead_patterns:
                        m = re.match(fp, trimmed, re.IGNORECASE)
                        if m:
                            trimmed = trimmed[m.end():].strip()
                            progress = True
                            break

                # If the entire line was filler or empty, skip it
                if not trimmed:
                    continue
                # If what remains is a residual sentence fragment like "to view customer balances:"
                if re.match(r"^to\s+(?:view|find|get|show|retrieve|see|display|filter)\s+.*?:\s*$", trimmed, re.IGNORECASE):
                    continue

                stripping = False
            cleaned_lines.append(trimmed if stripping else line)

        return "\n".join(cleaned_lines).strip()

    def _normalize_executable_blocks(self, text: str, safety_mode: str) -> str:
        """
        Ensures SELECT and safe queries are in ```sql:executable blocks,
        while mutating queries in read_only mode stay in ```sql.
        """
        code_block_pattern = r"```([a-zA-Z0-9_:-]*)[^\S\r\n]*\r?\n([\s\S]*?)```"
        mutating_keywords = {"drop", "delete", "truncate", "alter", "update", "insert", "create"}

        def replace_block(match):
            lang = match.group(1).strip().lower()
            code = match.group(2)

            if "sql" not in lang and lang != "":
                return match.group(0)

            # Check for mutating statements
            first_words = {w.lower() for w in re.findall(r"\b[a-zA-Z]+\b", code[:100])}
            is_mutation = bool(first_words & mutating_keywords)

            if safety_mode == "read_only" and is_mutation:
                return f"```sql\n{code.strip()}\n```"

            return f"```sql:executable\n{code.strip()}\n```"

        return re.sub(code_block_pattern, replace_block, text)

    def _synthesize_headline(
        self,
        prompt: str,
        queries: List[str],
        schema_map: Dict[str, Dict[str, Any]],
    ) -> str:
        """Generates a sharp, executive-grade headline."""
        p_lower = (prompt or "").lower()
        combined_sql = " ".join(queries).lower() if queries else ""

        if any(w in p_lower for w in ["clean", "hygiene", "dedup", "trim", "null"]):
            return "### 🧹 Data Hygiene & Normalization Blueprint"
        if any(w in p_lower for w in ["migration", "alter", "alembic", "ddl", "add column"]):
            return "### ⚡ Schema Evolution & Migration Strategy"
        if "order by" in combined_sql and "limit" in combined_sql:
            return "### 📊 Top-Tier Distribution & Ranking Analysis"
        if "strftime" in combined_sql or "date_trunc" in combined_sql or "to_char" in combined_sql:
            return "### 📈 Longitudinal Metric & Cohort Trajectory"
        if "count" in combined_sql or "sum" in combined_sql or "avg" in combined_sql:
            return "### 📋 Aggregate Volume & Metric Composition"
        if "join" in combined_sql:
            return "### 🔗 Relational Cross-Entity Analysis"

        return "### 📊 Executive Data Intelligence Query"

    def _synthesize_analytical_lens(
        self,
        prompt: str,
        sql: str,
        schema_map: Dict[str, Dict[str, Any]],
    ) -> str:
        """Synthesizes high-impact bullet points detailing the analytical lens and key takeaways."""
        sql_lower = sql.lower()

        bullets: List[str] = []

        if "order by" in sql_lower and "limit" in sql_lower:
            bullets.append(
                "- **Pareto Concentration**: Evaluates high-impact records driving disproportionate volume or balance across the cohort."
            )
            bullets.append(
                "- **Targeted Prioritization**: Surfaced entities can be directly targeted for VIP engagement, risk hedging, or pipeline acceleration."
            )
        elif "strftime" in sql_lower or "date_trunc" in sql_lower or "group by" in sql_lower:
            bullets.append(
                "- **Temporal Velocity**: Exposes period-over-period run-rates to identify demand acceleration, seasonality, or inflection points."
            )
            bullets.append(
                "- **Longitudinal Baseline**: Establishes historic trend lines for forward-looking cohort forecasting and variance analysis."
            )
        elif any(k in sql_lower for k in ["count", "sum", "avg", "min", "max"]):
            bullets.append(
                "- **Macro Scale & Capacity**: Quantifies aggregate system volume to inform capacity limits and macro KPI benchmarking."
            )
            bullets.append(
                "- **Distribution Symmetry**: Reveals metric variance and dispersion across aggregated operational dimensions."
            )
        else:
            bullets.append(
                "- **Relational Integrity**: Grounds multi-attribute metrics into verified database schema dimensions without synthetic distortion."
            )
            bullets.append(
                "- **Cohort Segmentation**: Isolates target records matching operational criteria for immediate review and auditing."
            )

        bullets.append(
            "- **Actionable Telemetry**: Delivers clean tabular projections ready for downstream decision-making and automated reporting."
        )

        return "#### 🔍 Analytical Lens & Key Takeaways\n" + "\n".join(bullets)

    # --------------------------------------------------------------------------
    # PASS 3: Interactive Next-Action Synthesis
    # --------------------------------------------------------------------------
    def pass3_action_synthesis(
        self,
        text: str,
        prompt: str,
        schema_map: Dict[str, Dict[str, Any]],
        extracted_queries: List[str],
    ) -> str:
        """
        Pass 3:
        Generates 2-3 high-value, contextual follow-up questions/actions and formats them
        as actionable suggestion chips in HTML comment syntax:
        <!-- suggestions: ["Filter by status = 'completed'", "Break down by month", "Export cleaned view as CSV"] -->
        """
        # If suggestions already present, ensure clean formatting
        existing_match = re.search(r"<!--\s*suggestions:\s*(\[[\s\S]*?\])\s*-->", text)
        if existing_match:
            return text

        actions = self._generate_next_actions(prompt, extracted_queries, schema_map)
        actions_json = json.dumps(actions)
        suggestion_tag = f"<!-- suggestions: {actions_json} -->"

        return f"{text.rstrip()}\n\n{suggestion_tag}\n"

    def _generate_next_actions(
        self,
        prompt: str,
        queries: List[str],
        schema_map: Dict[str, Dict[str, Any]],
    ) -> List[str]:
        """Dynamically generates 2-3 contextual next actions based on query, schema, and intent."""
        actions: List[str] = []
        p_lower = (prompt or "").lower()
        sql_combined = " ".join(queries).lower() if queries else ""

        # Identify active tables in query
        active_tables = [t for t in schema_map if re.search(r"\b" + re.escape(t) + r"\b", sql_combined)]
        if not active_tables and schema_map:
            active_tables = list(schema_map.keys())

        # Collect columns for active tables
        all_cols = []
        for t in active_tables:
            all_cols.extend(schema_map.get(t, {}).get("columns", []))
        col_names = [c.get("name", "").lower() for c in all_cols]

        # 1. Cleaning Intent
        if any(k in p_lower for k in ["clean", "dedup", "trim", "whitespace", "null"]):
            return [
                "Preview deduplicated rows",
                "Export cleaned view as CSV",
                "Audit null distribution after cleaning"
            ]

        # 2. Migration Intent
        if any(k in p_lower for k in ["migration", "alter", "alembic", "ddl"]):
            return [
                "Validate rollback SQL DOWN script",
                "Inspect affected foreign key constraints",
                "Generate synthetic staging rows"
            ]

        # 3. Status Filter Check
        has_status_col = any("status" in c or "state" in c for c in col_names)
        if has_status_col and "status" not in sql_combined:
            actions.append("Filter by status = 'completed'")
        elif has_status_col and "completed" in sql_combined:
            actions.append("Filter by status = 'active'")

        # 4. Temporal Breakdown Check
        has_date_col = any(any(d in c for d in ["date", "time", "created_at", "updated_at"]) for c in col_names)
        if has_date_col and not any(k in sql_combined for k in ["strftime", "date_trunc", "group by"]):
            actions.append("Break down by month")
        elif "strftime" in sql_combined or "date_trunc" in sql_combined:
            actions.append("Calculate month-over-month growth rate")

        # 5. Cross-Table Relational Link
        if "customers" in active_tables and "orders" in schema_map and "orders" not in sql_combined:
            actions.append("Join with orders to view purchase volume")
        elif "orders" in active_tables and "customers" in schema_map and "customers" not in sql_combined:
            actions.append("Join with customers to view buyer demographics")

        # 6. High-Value Universal Analytics Fallbacks
        fallbacks = [
            "Export cleaned view as CSV",
            "Calculate summary statistics (AVG, MIN, MAX)",
            "Expand to top 50 records"
        ]
        for fb in fallbacks:
            if len(actions) >= 3:
                break
            if fb not in actions:
                actions.append(fb)

        return actions[:3]

    # --------------------------------------------------------------------------
    # Helper Context Resolvers
    # --------------------------------------------------------------------------
    def _resolve_schema_map(
        self,
        schema: Optional[Union[DatabaseSchemaResponse, Dict[str, Any], List[str], str]]
    ) -> Dict[str, Dict[str, Any]]:
        """Resolves schema into a normalized dictionary."""
        if schema:
            return parse_schema_context(schema)

        # Fallback to active db_manager
        if self._db_manager:
            try:
                active_s = self._db_manager.get_schema()
                if active_s:
                    return parse_schema_context(active_s)
            except Exception:
                pass

        try:
            from services.db_manager import db_manager
            if db_manager and db_manager.is_connected:
                return parse_schema_context(db_manager.get_schema())
        except Exception:
            pass

        return {}

    def _resolve_dialect(self, dialect: Optional[str]) -> str:
        """Resolves active database dialect."""
        if dialect:
            return dialect

        if self._db_manager and getattr(self._db_manager, "engine_type", None):
            return self._db_manager.engine_type

        try:
            from services.db_manager import db_manager
            if db_manager and db_manager.engine_type:
                return db_manager.engine_type
        except Exception:
            pass

        return "duckdb"


# Module-level default singleton
output_refiner = OutputRefiner()
