from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field


class ColumnInfo(BaseModel):
    name: str
    data_type: str
    primary_key: bool = False
    nullable: bool = True
    default: Optional[str] = None


class ForeignKeyInfo(BaseModel):
    constrained_columns: List[str]
    referred_table: str
    referred_columns: List[str]


class TableSchema(BaseModel):
    name: str
    row_count: int = 0
    columns: List[ColumnInfo] = []
    foreign_keys: List[ForeignKeyInfo] = []


class DatabaseConnectionRequest(BaseModel):
    connection_string: Optional[str] = None
    database_type: Optional[str] = "duckdb"  # "duckdb", "sqlite", "postgres", "mysql"


class DatabaseSchemaResponse(BaseModel):
    status: str = "connected"
    engine: str
    database_name: str
    tables: List[TableSchema] = []
    error: Optional[str] = None


class QueryRequest(BaseModel):
    query: str
    mode: str = "read_only"  # "read_only" or "mutation"
    limit: Optional[int] = 100


class QueryResponse(BaseModel):
    status: str = "success"  # "success" or "error"
    columns: List[str] = []
    rows: List[List[Any]] = []
    row_count: int = 0
    execution_time_ms: float = 0.0
    truncated: bool = False
    error: Optional[str] = None


class ColumnProfile(BaseModel):
    name: str
    data_type: str
    null_count: int
    null_percentage: float
    unique_count: int
    sample_values: List[Any] = []
    min_value: Optional[Any] = None
    max_value: Optional[Any] = None


class AnomalyReport(BaseModel):
    category: str  # "null_burst", "duplicate_pk", "pii_risk", "unindexed_fk"
    severity: str  # "info", "warning", "critical"
    table: str
    column: Optional[str] = None
    description: str
    suggested_action: Optional[str] = None


class ProfileResponse(BaseModel):
    status: str = "success"
    table: str
    total_rows: int
    total_columns: int
    columns_profile: List[ColumnProfile] = []
    anomalies: List[AnomalyReport] = []
    error: Optional[str] = None


class AgentPromptRequest(BaseModel):
    prompt: str
    table_context: List[str] = []
    model: str = "gemini-1.5-flash"
    safety_mode: str = "read_only"
