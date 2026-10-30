import os
from typing import Optional, Dict, Any, List

from core.db_models import DatabaseSchemaResponse, QueryResponse
from services.db_connection import DBConnectionHandler
from services.schema_cartographer import (
    SchemaCartographer,
    build_schema_context_dict,
    build_schema_prompt_context,
)
from services.sql_executor import SafeSQLExecutor


class DatabaseManager:
    """
    Facade class combining DBConnectionHandler, SchemaCartographer, and SafeSQLExecutor.
    Single point of entry for the application's database lifecycle and operations.
    """

    def __init__(self):
        self.connection_handler = DBConnectionHandler()

    @property
    def is_connected(self) -> bool:
        return self.connection_handler.is_connected

    @property
    def connection(self) -> Any:
        return self.connection_handler.active_connection

    @property
    def engine(self) -> Any:
        return self.connection_handler.sqlalchemy_engine or self.connection_handler.duckdb_conn

    @property
    def engine_type(self) -> Optional[str]:
        return self.connection_handler.engine_type

    @property
    def active_database(self) -> Optional[str]:
        return self.connection_handler.active_database

    @property
    def engine_metadata(self) -> Dict[str, Any]:
        return self.connection_handler.engine_metadata

    def connect_file(self, file_path: str, filename: str) -> DatabaseSchemaResponse:
        """
        Loads CSV, Parquet, or SQLite files into an in-memory DuckDB instance
        and returns the introspected schema response.
        """
        self.connection_handler.connect_file(file_path=file_path, filename=filename)
        return self.get_schema()

    def connect_url(self, connection_string: str) -> DatabaseSchemaResponse:
        """
        Connects to PostgreSQL, MySQL, or SQLite via SQLAlchemy engine
        and returns the introspected schema response.
        """
        self.connection_handler.connect_url(connection_string=connection_string)
        return self.get_schema()

    def connect_connection_string(self, connection_string: str) -> DatabaseSchemaResponse:
        """
        Alias for connect_url to support flexible caller conventions.
        """
        return self.connect_url(connection_string)

    def get_schema(self) -> DatabaseSchemaResponse:
        """
        Inspects tables, columns, foreign keys, and row counts for the active connection.
        """
        return SchemaCartographer.introspect_schema(self.connection_handler)

    def get_schema_context(self) -> Dict[str, Any]:
        """
        Returns a dictionary-based schema context suitable for analysis or serialization.
        """
        schema = self.get_schema()
        return build_schema_context_dict(schema)

    def get_prompt_context(self) -> str:
        """
        Returns a human- and LLM-friendly textual representation of the schema.
        """
        schema = self.get_schema()
        return build_schema_prompt_context(schema)

    def execute_query(
        self,
        query: str,
        mode: str = "read_only",
        limit: Optional[int] = 100,
    ) -> QueryResponse:
        """
        Executes a SQL query against the active database engine with read-only safety guardrails.
        """
        return SafeSQLExecutor.execute(
            handler=self.connection_handler,
            query=query,
            mode=mode,
            limit=limit,
        )

    def close(self):
        """
        Closes any active database connections and resets state.
        """
        self.connection_handler.close()


# Application-wide singleton instance
db_manager = DatabaseManager()

# Auto-mount default sample dataset if present
_default_sample = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "data", "sample_datasets", "ecommerce.sqlite"
)
if os.path.exists(_default_sample):
    try:
        db_manager.connect_file(_default_sample, "ecommerce.sqlite")
    except Exception:
        pass
