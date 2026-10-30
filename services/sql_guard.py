"""
Autonomous Data & Schema Studio — AST SQL Guard.
Powered by sqlglot. Parses, classifies, and enforces statement security policies,
blocks multi-statement & CTE-masked write attacks, rewrites row limits, and issues query tokens.
"""

import time
import hmac
import hashlib
import json
from typing import Dict, Any, List, Optional, Set, Tuple
import sqlglot
from sqlglot import exp


# Internal HMAC secret for signing authorized query tokens
_GUARD_SECRET = b"dimension_studio_guard_secret_2026"


class SQLGuardException(Exception):
    def __init__(self, message: str, code: str = "guard_violation", retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


class SQLGuard:
    def __init__(self, default_limit: int = 500, max_limit: int = 10000):
        self.default_limit = default_limit
        self.max_limit = max_limit

    def inspect_and_classify(
        self,
        sql: str,
        dialect: str = "postgres",
    ) -> Dict[str, Any]:
        """
        Parses SQL using sqlglot and extracts classification, referenced tables, and security flags.
        """
        if not sql or not sql.strip():
            raise SQLGuardException("Empty SQL query supplied.", code="empty_query")

        # Map dialects
        norm_dialect = dialect.lower()
        if norm_dialect in ("sqlite", "sqlite3"):
            glot_dialect = "sqlite"
        elif norm_dialect in ("duckdb",):
            glot_dialect = "duckdb"
        elif norm_dialect in ("postgres", "postgresql"):
            glot_dialect = "postgres"
        elif norm_dialect in ("mysql", "mariadb"):
            glot_dialect = "mysql"
        else:
            glot_dialect = "postgres"

        try:
            parsed = sqlglot.parse(sql, read=glot_dialect)
        except Exception as e:
            raise SQLGuardException(f"SQL syntax parse failure: {str(e)}", code="syntax_error")

        if not parsed:
            raise SQLGuardException("Failed to generate AST for query.", code="parse_error")

        # Multi-statement check
        if len(parsed) > 1:
            raise SQLGuardException(
                f"Multi-statement execution rejected ({len(parsed)} statements detected). Only single statements permitted.",
                code="multi_statement_rejected",
            )

        statement = parsed[0]
        if statement is None:
            raise SQLGuardException("Null expression detected in AST.", code="invalid_statement")

        # Statement type classification
        is_read = isinstance(statement, (exp.Select, exp.Union))
        is_write = isinstance(statement, (exp.Insert, exp.Update, exp.Delete, exp.Merge))
        is_ddl = isinstance(statement, (exp.Create, exp.Alter, exp.Drop, exp.TruncateTable))
        is_transaction = isinstance(statement, (exp.Transaction, exp.Commit, exp.Rollback))
        is_command = isinstance(statement, (exp.Command, exp.Set, exp.Pragma))

        # Check for CTE write attacks inside SELECT (e.g. WITH d AS (DELETE FROM ... RETURNING *) SELECT * FROM d)
        for cte in statement.find_all(exp.CTE):
            inner_expr = cte.this
            if isinstance(inner_expr, (exp.Delete, exp.Insert, exp.Update)):
                is_write = True
                is_read = False

        # Check for SELECT ... INTO (which writes tables)
        if statement.find(exp.Into):
            is_write = True
            is_read = False

        # Extract referenced tables
        tables: Set[str] = set()
        for tbl in statement.find_all(exp.Table):
            if tbl.name:
                tables.add(tbl.name)

        # Class string
        if is_read:
            stmt_class = "READ"
        elif is_write:
            stmt_class = "WRITE"
        elif is_ddl:
            stmt_class = "DDL"
        elif is_transaction:
            stmt_class = "TRANSACTION"
        elif is_command:
            stmt_class = "COMMAND"
        else:
            stmt_class = "UNKNOWN"

        return {
            "statement": statement,
            "dialect": glot_dialect,
            "class": stmt_class,
            "is_read": is_read,
            "is_write": is_write,
            "is_ddl": is_ddl,
            "tables": sorted(list(tables)),
        }

    def enforce_read_only(
        self,
        sql: str,
        dialect: str = "postgres",
        enforce_limit: bool = True,
    ) -> Tuple[str, Dict[str, Any]]:
        """
        Validates that the SQL is strictly read-only and injects/clamps LIMIT clauses.
        Returns: (rewritten_sql, metadata)
        """
        meta = self.inspect_and_classify(sql, dialect=dialect)

        if not meta["is_read"]:
            raise SQLGuardException(
                f"Non-read statement ({meta['class']}) rejected in read-only execution context.",
                code="write_blocked",
            )

        statement = meta["statement"]

        # Limit rewriting
        limit_applied = False
        current_limit = None

        limit_node = statement.find(exp.Limit)
        if limit_node:
            try:
                current_limit = int(limit_node.expression.name)
            except Exception:
                current_limit = None

        if enforce_limit:
            if current_limit is None:
                # Inject default limit
                statement = statement.limit(self.default_limit)
                limit_applied = True
                final_limit = self.default_limit
            elif current_limit > self.max_limit:
                # Clamp excessive limit
                statement.set("limit", exp.Limit(expression=exp.Literal.number(self.max_limit)))
                limit_applied = True
                final_limit = self.max_limit
            else:
                final_limit = current_limit
        else:
            final_limit = current_limit

        rewritten_sql = statement.sql(dialect=meta["dialect"])

        meta["final_limit"] = final_limit
        meta["limit_rewritten"] = limit_applied
        meta["sanitized_sql"] = rewritten_sql

        return rewritten_sql, meta

    def issue_query_token(
        self,
        sanitized_sql: str,
        connection_id: str,
        tier: str,
        meta: Dict[str, Any],
        ttl_seconds: int = 300,
    ) -> str:
        """Generates an HMAC-signed query token proving the query has cleared the AST guard."""
        expiry = int(time.time()) + ttl_seconds
        payload = {
            "sql": sanitized_sql,
            "conn_id": connection_id,
            "tier": tier,
            "cls": meta.get("class", "READ"),
            "exp": expiry,
        }
        encoded = json.dumps(payload, sort_keys=True)
        sig = hmac.new(_GUARD_SECRET, encoded.encode("utf-8"), hashlib.sha256).hexdigest()
        token = f"qtok_{encoded}_{sig}"
        return token

    def verify_query_token(self, token: str) -> Dict[str, Any]:
        """Verifies HMAC signature and expiration on a query token."""
        if not token.startswith("qtok_"):
            raise SQLGuardException("Invalid query token header.", code="invalid_token")

        parts = token[5:].rsplit("_", 1)
        if len(parts) != 2:
            raise SQLGuardException("Malformed query token structure.", code="invalid_token")

        encoded, sig = parts
        expected_sig = hmac.new(_GUARD_SECRET, encoded.encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected_sig):
            raise SQLGuardException("Query token HMAC signature mismatch.", code="tampered_token")

        payload = json.loads(encoded)
        if time.time() > payload.get("exp", 0):
            raise SQLGuardException("Query token expired. Please re-check the query.", code="expired_token")

        return payload


# Global singleton
sql_guard = SQLGuard()
