import os
import time
import json
from typing import Optional
from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from fastapi.responses import StreamingResponse

from core.db_models import (
    DatabaseConnectionRequest,
    DatabaseSchemaResponse,
    QueryRequest,
    QueryResponse,
    ProfileResponse,
    AgentPromptRequest,
)

router = APIRouter(tags=["Database & Schema Studio"])

UPLOAD_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "db_uploads")
os.makedirs(UPLOAD_DATA_DIR, exist_ok=True)

SUPPORTED_DATA_EXTENSIONS = {".csv", ".tsv", ".parquet", ".pq", ".sqlite", ".sqlite3", ".db"}


def _get_db_manager():
    try:
        from services.db_manager import db_manager
        return db_manager
    except ImportError:
        return None


def _get_profiler():
    try:
        from services.profiler import run_table_profile
        return run_table_profile
    except ImportError:
        return None


def _get_data_agent():
    try:
        from services.data_agent import stream_data_agent_response
        return stream_data_agent_response
    except ImportError:
        return None


@router.post("/db/connect", response_model=DatabaseSchemaResponse)
async def connect_database(
    connection_string: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
):
    """
    Connect to a live SQL database or ingest a CSV/Parquet/SQLite file.
    """
    manager = _get_db_manager()
    if not manager:
        raise HTTPException(
            status_code=503,
            detail="Database Manager service (services/db_manager.py) is being initialized by Branch 1.",
        )

    if file:
        ext = os.path.splitext(file.filename)[1].lower()
        if ext not in SUPPORTED_DATA_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported format '{ext}'. Dimension Data Studio only accepts structured database & tabular files (.csv, .tsv, .parquet, .sqlite, .db). Document files (.pdf, .docx, .txt, .md) are not supported."
            )
        file_path = os.path.join(UPLOAD_DATA_DIR, file.filename)
        with open(file_path, "wb") as f:
            content = await file.read()
            f.write(content)
        try:
            return manager.connect_file(file_path, file.filename)
        except ValueError as ve:
            raise HTTPException(status_code=400, detail=str(ve))

    if connection_string:
        return manager.connect_connection_string(connection_string)

    raise HTTPException(status_code=400, detail="Either connection_string or a file must be provided.")


@router.get("/db/schema", response_model=DatabaseSchemaResponse)
async def get_current_schema():
    """
    Get introspected schema for the currently active database connection.
    """
    manager = _get_db_manager()
    if not manager:
        raise HTTPException(status_code=503, detail="Database Manager service not yet ready.")
    return manager.get_schema()


@router.post("/db/query", response_model=QueryResponse)
async def execute_sql_query(payload: QueryRequest):
    """
    Execute a SQL query with read-only safety guardrails.
    """
    manager = _get_db_manager()
    if not manager:
        raise HTTPException(status_code=503, detail="Database Manager service not yet ready.")
    return manager.execute_query(payload.query, mode=payload.mode, limit=payload.limit)


@router.post("/db/profile", response_model=ProfileResponse)
async def profile_table(payload: dict):
    """
    Run automated profiling and anomaly detection for a specific table.
    """
    profiler = _get_profiler()
    manager = _get_db_manager()
    if not profiler or not manager:
        raise HTTPException(status_code=503, detail="Profiler service (services/profiler.py) is being initialized by Branch 2.")
    
    table_name = payload.get("table")
    if not table_name:
        raise HTTPException(status_code=400, detail="Field 'table' is required.")
    
    return profiler(manager, table_name)


@router.post("/agent/stream")
async def stream_data_agent(payload: AgentPromptRequest):
    """
    Autonomous Data Agent for NL-to-SQL, cleaning recipes, and migration generation.
    """
    agent_stream = _get_data_agent()
    if not agent_stream:
        # Fallback SSE generator informing client service is initializing
        def dummy_stream():
            yield "data: " + json.dumps({"token": "Data Agent toolkit (Branch 2) is being initialized..."}) + "\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(dummy_stream(), media_type="text/event-stream")

    return StreamingResponse(agent_stream(payload), media_type="text/event-stream")
