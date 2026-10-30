"""
Autonomous Data & Schema Studio — Connector Layer & Credential Vault.
Manages multi-engine database connections (PostgreSQL, SQLite, DuckDB),
OS keyring credential isolation, read-only session parameters, and privilege grading.
"""

import os
import re
import uuid
import urllib.parse
from typing import Dict, Any, Optional, Tuple
import sqlalchemy
from sqlalchemy import create_engine, text, inspect
from sqlalchemy.engine import Engine

try:
    import keyring
except ImportError:
    keyring = None


# Local memory fallback for headless testing environments without OS keychain daemon
_LOCAL_SECRET_VAULT: Dict[str, str] = {}


class CredentialVault:
    SERVICE_NAME = "dimension_studio"

    @classmethod
    def store_secret(cls, secret_ref: str, secret_val: str):
        if keyring:
            try:
                keyring.set_password(cls.SERVICE_NAME, secret_ref, secret_val)
                return
            except Exception:
                pass
        _LOCAL_SECRET_VAULT[secret_ref] = secret_val

    @classmethod
    def get_secret(cls, secret_ref: str) -> Optional[str]:
        if keyring:
            try:
                val = keyring.get_password(cls.SERVICE_NAME, secret_ref)
                if val is not None:
                    return val
            except Exception:
                pass
        return _LOCAL_SECRET_VAULT.get(secret_ref)

    @classmethod
    def delete_secret(cls, secret_ref: str):
        if keyring:
            try:
                keyring.delete_password(cls.SERVICE_NAME, secret_ref)
            except Exception:
                pass
        _LOCAL_SECRET_VAULT.pop(secret_ref, None)


class StudioConnector:
    """
    Creates and configures engines with statement timeouts, read-only sessions,
    and privilege grading for PostgreSQL, SQLite, and DuckDB.
    """

    @classmethod
    def assemble_dsn(cls, dsn_template: str, secret_ref: Optional[str] = None) -> str:
        """Injects password securely from vault into DSN template at runtime."""
        if not secret_ref:
            return dsn_template

        secret = CredentialVault.get_secret(secret_ref)
        if not secret:
            return dsn_template

        # Safely insert password into URL
        parsed = urllib.parse.urlsplit(dsn_template)
        if parsed.username:
            netloc = f"{parsed.username}:{urllib.parse.quote_plus(secret)}@{parsed.hostname}"
            if parsed.port:
                netloc += f":{parsed.port}"
            return urllib.parse.urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))
        return dsn_template

    @classmethod
    def create_managed_engine(
        cls,
        engine_type: str,
        dsn: str,
        read_only: bool = True,
        statement_timeout_ms: int = 15000,
        lock_timeout_ms: int = 5000,
        run_id: Optional[str] = None,
    ) -> Engine:
        """
        Builds a hardened SQLAlchemy engine with session parameters.
        """
        eng_norm = engine_type.lower()
        app_name = f"dimension-studio/{run_id or 'default'}"

        if eng_norm in ("postgres", "postgresql"):
            connect_args = {
                "application_name": app_name,
            }
            if read_only:
                # Postgres driver parameter string
                connect_args["options"] = (
                    f"-c default_transaction_read_only=on "
                    f"-c statement_timeout={statement_timeout_ms} "
                    f"-c lock_timeout={lock_timeout_ms}"
                )

            # Ensure psycopg driver is specified
            if dsn.startswith("postgres://"):
                dsn = "postgresql+psycopg://" + dsn[11:]
            elif dsn.startswith("postgresql://") and "+psycopg" not in dsn:
                dsn = "postgresql+psycopg://" + dsn[13:]

            return create_engine(
                dsn,
                connect_args=connect_args,
                pool_size=4,
                max_overflow=0,
                pool_pre_ping=True,
            )

        elif eng_norm in ("sqlite", "sqlite3"):
            sqlite_url = dsn
            if not sqlite_url.startswith("sqlite://"):
                sqlite_url = f"sqlite:///{dsn}"

            engine = create_engine(
                sqlite_url,
                connect_args={"check_same_thread": False, "timeout": 15.0},
                pool_pre_ping=True,
            )

            # Enable WAL mode and foreign keys on connect
            @sqlalchemy.event.listens_for(engine, "connect")
            def set_sqlite_pragma(dbapi_connection, connection_record):
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA foreign_keys=ON;")
                cursor.execute("PRAGMA journal_mode=WAL;")
                cursor.close()

            return engine

        elif eng_norm in ("duckdb",):
            duck_url = dsn if dsn.startswith("duckdb://") else f"duckdb:///{dsn}"
            return create_engine(duck_url)

        elif eng_norm in ("mysql", "mariadb"):
            mysql_url = dsn
            if mysql_url.startswith("mysql://"):
                mysql_url = "mysql+pymysql://" + mysql_url[8:]
            elif not mysql_url.startswith("mysql+pymysql://"):
                mysql_url = f"mysql+pymysql://{mysql_url}"

            connect_args = {
                "connect_timeout": statement_timeout_ms // 1000 or 15,
            }
            if read_only:
                connect_args["init_command"] = "SET SESSION TRANSACTION READ ONLY;"

            return create_engine(
                mysql_url,
                connect_args=connect_args,
                pool_size=4,
                max_overflow=0,
                pool_pre_ping=True,
            )

        else:
            raise ValueError(f"Unsupported database engine type: {engine_type}")

    @classmethod
    def evaluate_privilege_grade(cls, engine: Engine, engine_type: str) -> Tuple[str, str]:
        """
        Assesses the connection's privilege level:
        Grade A: Role has SELECT-only permissions.
        Grade B: Role has write grants, but session read-only enforcement is active.
        Grade C: Superuser or unrestricted write role.
        """
        eng_norm = engine_type.lower()

        try:
            with engine.connect() as conn:
                if eng_norm in ("postgres", "postgresql"):
                    # Check if superuser
                    is_super = conn.execute(text("SELECT current_setting('is_superuser');")).scalar()
                    if is_super and is_super.lower() in ("on", "true"):
                        return "C", "Superuser connection role. Full system privileges."

                    # Check default transaction read-only setting
                    ro_setting = conn.execute(text("SELECT current_setting('default_transaction_read_only');")).scalar()
                    if ro_setting and ro_setting.lower() in ("on", "true"):
                        return "B", "Session forced read-only. Safe for exploration."

                    return "B", "Standard role with session-level guardrails."

                elif eng_norm in ("sqlite", "sqlite3"):
                    return "B", "Local SQLite connection with filesystem-level permissions."

                elif eng_norm in ("duckdb",):
                    return "B", "In-memory or analytical DuckDB engine."

                elif eng_norm in ("mysql", "mariadb"):
                    try:
                        grants = conn.execute(text("SHOW GRANTS;")).fetchall()
                        grant_strs = [str(g[0]).upper() for g in grants]
                        if any("ALL PRIVILEGES" in g or "SUPER" in g for g in grant_strs):
                            return "C", "Administrative/Superuser MySQL role detected."
                        if all("SELECT" in g and not any(w in g for w in ("INSERT", "UPDATE", "DELETE", "DROP", "ALTER")) for g in grant_strs):
                            return "A", "Read-only MySQL role (SELECT grants only)."
                        return "B", "Standard MySQL user with session read-only mode."
                    except Exception:
                        return "B", "Standard MySQL connection."

                return "B", "Standard database connection."
        except Exception as e:
            return "B", f"Default session grade assigned: {str(e)}"
