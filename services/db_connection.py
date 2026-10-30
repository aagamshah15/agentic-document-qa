import os
import re
import sqlite3
from typing import Optional, Dict, Any, List
import duckdb
from sqlalchemy import create_engine, Engine
from sqlalchemy.engine.url import make_url

from core.db_models import ForeignKeyInfo


def sanitize_table_name(filename: str) -> str:
    """
    Sanitize an uploaded filename into a valid SQL table identifier.
    """
    base = os.path.basename(filename)
    stem, _ = os.path.splitext(base)
    clean = re.sub(r'[^a-zA-Z0-9_]', '_', stem)
    clean = clean.strip('_')
    if not clean:
        clean = "uploaded_table"
    elif clean[0].isdigit():
        clean = f"t_{clean}"
    return clean.lower()


class DBConnectionHandler:
    """
    Manages DuckDB in-memory lifecycle and SQLAlchemy engine pool.
    """

    def __init__(self):
        self.duckdb_conn: Optional[duckdb.DuckDBPyConnection] = None
        self.sqlalchemy_engine: Optional[Engine] = None
        self.engine_type: Optional[str] = None  # "duckdb" or "sqlalchemy"
        self.dialect: Optional[str] = None      # "duckdb", "sqlite", "postgresql", "mysql", etc.
        self.active_database: Optional[str] = None
        self.masked_url: Optional[str] = None
        self.explicit_fks: Dict[str, List[ForeignKeyInfo]] = {}

    @property
    def is_connected(self) -> bool:
        if self.engine_type == "duckdb" and self.duckdb_conn is not None:
            return True
        if self.engine_type == "sqlalchemy" and self.sqlalchemy_engine is not None:
            return True
        return False

    @property
    def active_connection(self) -> Any:
        if self.engine_type == "duckdb":
            return self.duckdb_conn
        if self.engine_type == "sqlalchemy" and self.sqlalchemy_engine:
            return self.sqlalchemy_engine
        return None

    @property
    def engine_metadata(self) -> Dict[str, Any]:
        return {
            "engine_type": self.engine_type,
            "dialect": self.dialect,
            "database_name": self.active_database,
            "connected": self.is_connected,
            "url": self.masked_url,
        }

    def close(self):
        """
        Close active DuckDB or SQLAlchemy connections and reset state.
        """
        if self.duckdb_conn is not None:
            try:
                self.duckdb_conn.close()
            except Exception:
                pass
            self.duckdb_conn = None

        if self.sqlalchemy_engine is not None:
            try:
                self.sqlalchemy_engine.dispose()
            except Exception:
                pass
            self.sqlalchemy_engine = None

        self.engine_type = None
        self.dialect = None
        self.active_database = None
        self.masked_url = None
        self.explicit_fks = {}

    def connect_file(self, file_path: str, filename: str) -> "DBConnectionHandler":
        """
        Loads CSV, Parquet, or SQLite files into an in-memory DuckDB instance.
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Dataset file not found: {file_path}")

        # If previously connected via SQLAlchemy or closed, initialize DuckDB
        if self.engine_type != "duckdb" or self.duckdb_conn is None:
            self.close()
            self.duckdb_conn = duckdb.connect(database=":memory:")
            self.engine_type = "duckdb"
            self.dialect = "duckdb"
            self.active_database = filename

        ext = os.path.splitext(filename)[1].lower()

        if ext in [".csv", ".tsv"]:
            table_name = sanitize_table_name(filename)
            self.duckdb_conn.execute(
                f'CREATE OR REPLACE TABLE "{table_name}" AS SELECT * FROM read_csv_auto(?)',
                [file_path]
            )
            self.active_database = filename

        elif ext in [".parquet", ".pq"]:
            table_name = sanitize_table_name(filename)
            self.duckdb_conn.execute(
                f'CREATE OR REPLACE TABLE "{table_name}" AS SELECT * FROM read_parquet(?)',
                [file_path]
            )
            self.active_database = filename

        elif ext in [".sqlite", ".sqlite3", ".db"]:
            self._load_sqlite_into_duckdb(file_path)
            self.active_database = filename

        else:
            raise ValueError(f"Unsupported file format '{ext}'. Supported: .csv, .parquet, .sqlite, .sqlite3, .db")

        return self

    def _load_sqlite_into_duckdb(self, sqlite_path: str):
        """
        Ingest all user tables and records from a SQLite database file into DuckDB.
        """
        s_conn = sqlite3.connect(sqlite_path)
        try:
            cur = s_conn.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
            tables = [r[0] for r in cur.fetchall()]

            for tbl in tables:
                cur.execute(f'PRAGMA table_info("{tbl}")')
                col_info = cur.fetchall()
                if not col_info:
                    continue

                col_defs = []
                for c in col_info:
                    cname = c[1]
                    raw_type = c[2].upper() if c[2] else "VARCHAR"
                    pk_clause = " PRIMARY KEY" if c[5] else ""
                    nn_clause = " NOT NULL" if c[3] else ""
                    col_defs.append(f'"{cname}" {raw_type}{pk_clause}{nn_clause}')

                col_str = ", ".join(col_defs)
                self.duckdb_conn.execute(f'CREATE OR REPLACE TABLE "{tbl}" ({col_str})')

                cur.execute(f'SELECT * FROM "{tbl}"')
                rows = cur.fetchall()
                if rows:
                    placeholders = ", ".join(["?"] * len(col_info))
                    self.duckdb_conn.executemany(f'INSERT INTO "{tbl}" VALUES ({placeholders})', rows)

                # Capture foreign keys from SQLite
                cur.execute(f'PRAGMA foreign_key_list("{tbl}")')
                fk_rows = cur.fetchall()
                if fk_rows:
                    fks = []
                    for fk in fk_rows:
                        # (id, seq, table, from, to, on_update, on_delete, match)
                        fks.append(ForeignKeyInfo(
                            constrained_columns=[fk[3]],
                            referred_table=fk[2],
                            referred_columns=[fk[4]]
                        ))
                    self.explicit_fks[tbl] = fks
        finally:
            s_conn.close()

    def connect_url(self, connection_string: str) -> "DBConnectionHandler":
        """
        Connects to PostgreSQL, MySQL, or SQLite via SQLAlchemy engine.
        """
        self.close()

        engine = create_engine(connection_string, pool_pre_ping=True)
        # Test connection
        with engine.connect() as test_conn:
            test_conn.execute(duckdb_text("SELECT 1") if False else sqlalchemy_text("SELECT 1"))

        self.sqlalchemy_engine = engine
        self.engine_type = "sqlalchemy"
        self.dialect = engine.dialect.name

        try:
            url_obj = make_url(connection_string)
            self.active_database = url_obj.database or "database"
            self.masked_url = url_obj.render_as_string(hide_password=True)
        except Exception:
            self.active_database = "database"
            self.masked_url = "connection_string"

        return self

    def connect_connection_string(self, connection_string: str) -> "DBConnectionHandler":
        """
        Alias for connect_url to support flexible caller conventions.
        """
        return self.connect_url(connection_string)


def sqlalchemy_text(sql: str):
    from sqlalchemy import text
    return text(sql)
