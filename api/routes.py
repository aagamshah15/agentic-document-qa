import os
import json
import shutil
import urllib.request
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from api.models import (
    QueryRequest,
    QueryResponse,
    DocumentItem,
    DocumentListResponse,
    SessionItem,
    SessionListResponse,
    MessageItem,
    SessionDetailResponse,
    CreateSessionRequest,
    UpdateSessionRequest,
    SavePartialMessageRequest,
    ModelListResponse,
)
from services.document_processor import (
    process_document,
    process_pdf,
    SUPPORTED_EXTENSIONS,
)
from services.vector_store import (
    add_documents_to_store,
    get_document_chunk_counts,
    delete_document_from_store,
    clear_vector_store,
)
from services.agent import (
    get_agent_executor,
    format_chat_history,
    extract_sources,
    get_session_history,
    clear_session_history,
)
import services.session_store as session_store
from services.summarizer import (
    generate_document_summary,
    stream_document_summary,
)
from services.router import determine_query_route
from services.web_search import (
    answer_with_web_search,
    stream_web_search_answer,
)
from langchain_core.messages import HumanMessage, AIMessage

router = APIRouter()

class ClearChatRequest(BaseModel):
    session_id: Optional[str] = "default"

# Directory to temporarily store uploaded files
UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

# ==============================================================================
# Model Discovery Endpoint
# ==============================================================================

@router.get("/models", response_model=ModelListResponse)
async def list_models():
    """
    Query local Ollama instance for installed models, with fallback defaults.
    """
    models = []
    default_model = "llama3"
    try:
        req = urllib.request.Request("http://localhost:11434/api/tags", headers={"User-Agent": "AgenticQA/1.0"})
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            for m in data.get("models", []):
                name = m.get("name")
                if name:
                    models.append(name)
        if models:
            if "llama3:latest" in models:
                default_model = "llama3:latest"
            elif "llama3" in models:
                default_model = "llama3"
            elif "llama3.1:8b" in models:
                default_model = "llama3.1:8b"
            else:
                default_model = models[0]
    except Exception:
        # Fallback when Ollama API cannot be reached directly (e.g. sandboxed test)
        models = ["llama3", "llama3.1:8b", "qwen3:4b", "qwen2.5:0.5b", "mistral"]
        default_model = "llama3"
        
    return ModelListResponse(models=models, default_model=default_model)

# ==============================================================================
# Multi-Chat & Persistent Session Endpoints
# ==============================================================================

@router.get("/sessions", response_model=SessionListResponse)
async def get_sessions():
    """List all saved chat sessions ordered by most recently updated."""
    sessions = session_store.list_sessions()
    return SessionListResponse(sessions=[SessionItem(**s) for s in sessions])

@router.post("/sessions", response_model=SessionItem)
async def create_session(request: CreateSessionRequest):
    """Create a new chat session."""
    s_id = request.session_id or f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{os.urandom(3).hex()}"
    session = session_store.create_or_get_session(
        session_id=s_id,
        title=request.title or "New Chat",
        model=request.model or "llama3",
        effort=request.effort or "medium"
    )
    return SessionItem(**session)

@router.get("/sessions/{session_id}", response_model=SessionDetailResponse)
async def get_session(session_id: str):
    """Retrieve full message history and metadata for a specific session."""
    details = session_store.get_session_details(session_id)
    if not details:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")
    return SessionDetailResponse(
        session=SessionItem(**details["session"]),
        messages=[MessageItem(**m) for m in details["messages"]]
    )

@router.patch("/sessions/{session_id}", response_model=SessionItem)
async def update_session(session_id: str, request: UpdateSessionRequest):
    """Update settings, title, pin status, or archive status for a specific session."""
    updated = session_store.update_session_settings(
        session_id=session_id,
        title=request.title,
        model=request.model,
        effort=request.effort,
        pinned=request.pinned,
        archived=request.archived
    )
    if not updated:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found or no updates provided.")
    details = session_store.get_session_details(session_id)
    return SessionItem(**details["session"])

@router.delete("/sessions/{session_id}")
async def delete_session_endpoint(session_id: str):
    """Delete a specific session and all its stored messages."""
    deleted = session_store.delete_session(session_id)
    clear_session_history(session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")
    return {"message": f"Successfully deleted session '{session_id}'."}

@router.post("/sessions/{session_id}/clear")
async def clear_session_endpoint(session_id: str):
    """Clear all messages inside a specific session."""
    session_store.clear_session_messages(session_id)
    clear_session_history(session_id)
    return {"message": f"Successfully cleared messages for session '{session_id}'."}

@router.post("/chat/stop")
async def stop_chat_stream(request: SavePartialMessageRequest):
    """
    Save partially streamed assistant response when user stops generation early.
    """
    if request.content.strip():
        sources_dicts = [
            (s.model_dump() if hasattr(s, "model_dump") else s.dict())
            for s in (request.sources or [])
        ]
        session_store.add_message(
            session_id=request.session_id,
            role=request.role,
            content=request.content.strip(),
            sources=sources_dicts,
            route=request.route
        )
    return {"message": "Partial stream state saved."}

# ==============================================================================
# Document Management Endpoints
# ==============================================================================

@router.get("/documents", response_model=DocumentListResponse)
async def list_documents():
    """
    List all uploaded documents with size, modification date, and indexed chunk count.
    """
    try:
        chunk_counts = get_document_chunk_counts()
        documents = []
        total_chunks = 0
        
        if os.path.exists(UPLOAD_DIR):
            for filename in os.listdir(UPLOAD_DIR):
                if filename.startswith("."):
                    continue
                file_path = os.path.join(UPLOAD_DIR, filename)
                if os.path.isfile(file_path):
                    stat = os.stat(file_path)
                    uploaded_at = datetime.fromtimestamp(stat.st_mtime).strftime("%b %d, %Y %I:%M %p")
                    count = chunk_counts.get(filename, 0)
                    total_chunks += count
                    documents.append(
                        DocumentItem(
                            filename=filename,
                            size_bytes=stat.st_size,
                            uploaded_at=uploaded_at,
                            chunk_count=count,
                        )
                    )
        
        # Sort documents alphabetically by filename
        documents.sort(key=lambda d: d.filename.lower())
        return DocumentListResponse(documents=documents, total_chunks=total_chunks)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/documents/{filename}")
async def delete_document(filename: str):
    """
    Delete a specific uploaded document file and remove all its chunks from the vector database.
    """
    try:
        # Prevent directory traversal attacks
        safe_filename = os.path.basename(filename)
        file_path = os.path.join(UPLOAD_DIR, safe_filename)
        
        deleted_file = False
        if os.path.exists(file_path):
            os.remove(file_path)
            deleted_file = True
            
        deleted_chunks = delete_document_from_store(safe_filename)
        
        if not deleted_file and deleted_chunks == 0:
            raise HTTPException(status_code=404, detail=f"Document '{safe_filename}' not found.")
            
        return {
            "message": f"Successfully deleted {safe_filename}.",
            "deleted_chunks": deleted_chunks,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/documents/clear")
async def clear_all_documents():
    """
    Delete all uploaded documents and wipe the vector store clean.
    """
    try:
        if os.path.exists(UPLOAD_DIR):
            for filename in os.listdir(UPLOAD_DIR):
                file_path = os.path.join(UPLOAD_DIR, filename)
                if os.path.isfile(file_path):
                    os.remove(file_path)
                    
        clear_vector_store()
        return {"message": "Successfully cleared all documents and reset the knowledge base."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/upload")
async def upload_document(file: UploadFile = File(...)):
    raise HTTPException(
        status_code=400,
        detail="Document uploads (.pdf, .docx, .txt, .md) have been disabled. Dimension has been repurposed into the Autonomous Data & Schema Studio. Please connect a database or ingest tabular/database files (.csv, .tsv, .parquet, .sqlite, .db) via /api/db/connect."
    )

@router.post("/documents/{filename}/summarize")
async def summarize_document_endpoint(filename: str):
    """
    Generate a full executive summary for a specific document.
    """
    safe_filename = os.path.basename(filename)
    file_path = os.path.join(UPLOAD_DIR, safe_filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail=f"Document '{safe_filename}' not found.")
    
    try:
        summary = generate_document_summary(file_path)
        return {
            "filename": safe_filename,
            "summary": summary,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/documents/{filename}/summarize/stream")
async def summarize_document_stream_endpoint(filename: str):
    """
    Stream an executive summary for a specific document token-by-token.
    """
    safe_filename = os.path.basename(filename)
    file_path = os.path.join(UPLOAD_DIR, safe_filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail=f"Document '{safe_filename}' not found.")

    async def event_generator():
        try:
            async for token in stream_document_summary(file_path):
                yield f"data: {json.dumps({'token': token})}\n\n"
            yield f"data: {json.dumps({'done': True, 'filename': safe_filename})}\n\n"
        except Exception as stream_err:
            yield f"data: {json.dumps({'error': str(stream_err)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )

# ==============================================================================
# Query & Real-Time Streaming Endpoints
# ==============================================================================

@router.post("/query", response_model=QueryResponse)
async def query_agent(request: QueryRequest):
    try:
        session_id = request.session_id or "default"
        model = request.model or "llama3"
        effort = request.effort or "medium"
        
        # Ensure session exists in SQLite and record user message
        session_store.create_or_get_session(session_id, model=model, effort=effort)
        session_store.add_message(session_id, "user", request.query)
        session_store.update_session_title_if_default(session_id, request.query)

        route, score = determine_query_route(request.query)

        # Autonomous Web Search Route
        if route == "web_search":
            res = answer_with_web_search(request.query, model=model, effort=effort)
            server_history = get_session_history(session_id)
            server_history.append(HumanMessage(content=request.query))
            server_history.append(AIMessage(content=res["answer"]))
            
            # Persist to SQLite
            session_store.add_message(
                session_id=session_id,
                role="assistant",
                content=res["answer"],
                sources=res["sources"],
                route="web_search"
            )
            
            return QueryResponse(
                answer=res["answer"],
                sources=res["sources"],
                route="web_search",
                notice=res.get("notice"),
            )

        # Local Context Route
        agent_executor = get_agent_executor(model=model, effort=effort)
        
        # Determine history: use explicit client history if provided, else server session store
        if request.history:
            chat_history = format_chat_history(request.history)
        else:
            chat_history = get_session_history(session_id)
        
        # Execute the agent
        response = agent_executor.invoke({
            "input": request.query,
            "chat_history": chat_history,
        })
        
        answer = response["output"]
        sources = response.get("sources", [])
        
        # Update server-side session memory & SQLite
        server_history = get_session_history(session_id)
        server_history.append(HumanMessage(content=request.query))
        server_history.append(AIMessage(content=answer))
        
        session_store.add_message(
            session_id=session_id,
            role="assistant",
            content=answer,
            sources=sources,
            route="local_context"
        )
        
        return QueryResponse(
            answer=answer,
            sources=sources,
            route="local_context",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/query/stream")
async def query_agent_stream(request: QueryRequest):
    """
    Server-Sent Events (SSE) stream returning tokens in real time,
    with model/effort selection and autonomous routing between local documents and live web search.
    """
    try:
        session_id = request.session_id or "default"
        model = request.model or "llama3"
        effort = request.effort or "medium"
        
        # Ensure session exists in SQLite and record user message
        session_store.create_or_get_session(session_id, model=model, effort=effort)
        session_store.add_message(session_id, "user", request.query)
        session_store.update_session_title_if_default(session_id, request.query)

        route, score = determine_query_route(request.query)

        # Web Search Streaming Route
        if route == "web_search":
            async def web_event_generator():
                full_answer = []
                sources = []
                try:
                    async for event in stream_web_search_answer(request.query, model=model, effort=effort):
                        if "token" in event:
                            full_answer.append(event["token"])
                        if "sources" in event and event["sources"]:
                            sources = event["sources"]
                        yield f"data: {json.dumps(event)}\n\n"
                    
                    full_str = "".join(full_answer)
                    server_history = get_session_history(session_id)
                    server_history.append(HumanMessage(content=request.query))
                    server_history.append(AIMessage(content=full_str))
                    
                    # Persist to SQLite
                    session_store.add_message(
                        session_id=session_id,
                        role="assistant",
                        content=full_str,
                        sources=sources,
                        route="web_search"
                    )
                except Exception as err:
                    yield f"data: {json.dumps({'error': str(err)})}\n\n"

            return StreamingResponse(
                web_event_generator(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                }
            )

        # Local Context Streaming Route
        agent_executor = get_agent_executor(model=model, effort=effort)
        
        if request.history:
            chat_history = format_chat_history(request.history)
        else:
            chat_history = get_session_history(session_id)

        async def local_event_generator():
            full_answer = []
            sources = []
            try:
                yield f"data: {json.dumps({'route': 'local_context'})}\n\n"

                async for chunk in agent_executor.astream({
                    "input": request.query,
                    "chat_history": chat_history,
                }):
                    if "context" in chunk and not sources:
                        sources = extract_sources(chunk["context"])
                    if "answer" in chunk:
                        token = chunk["answer"]
                        if token:
                            full_answer.append(token)
                            yield f"data: {json.dumps({'token': token})}\n\n"
                
                full_str = "".join(full_answer)
                # Persist to server session history
                server_history = get_session_history(session_id)
                server_history.append(HumanMessage(content=request.query))
                server_history.append(AIMessage(content=full_str))
                
                # Persist to SQLite
                session_store.add_message(
                    session_id=session_id,
                    role="assistant",
                    content=full_str,
                    sources=sources,
                    route="local_context"
                )
                
                # Yield completion event with sources
                yield f"data: {json.dumps({'done': True, 'sources': sources, 'route': 'local_context'})}\n\n"
            except Exception as stream_err:
                yield f"data: {json.dumps({'error': str(stream_err)})}\n\n"

        return StreamingResponse(
            local_event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            }
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/chat/clear")
async def clear_chat(request: ClearChatRequest):
    """
    Clears the server-side conversational memory for a given session.
    """
    try:
        session_id = request.session_id or "default"
        clear_session_history(session_id)
        session_store.clear_session_messages(session_id)
        return {"message": "Chat history cleared successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
