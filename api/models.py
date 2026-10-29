from typing import List, Optional, Any
from pydantic import BaseModel

class ChatMessage(BaseModel):
    role: str  # "user" or "assistant"
    content: str

class SourceItem(BaseModel):
    source: str
    page: Optional[int] = None
    url: Optional[str] = None
    snippet: str

class QueryRequest(BaseModel):
    query: str
    session_id: Optional[str] = "default"
    history: Optional[List[ChatMessage]] = []
    model: Optional[str] = "llama3"
    effort: Optional[str] = "medium"

class QueryResponse(BaseModel):
    answer: str
    sources: List[SourceItem] = []
    route: str = "local_context"
    notice: Optional[str] = None

class DocumentItem(BaseModel):
    filename: str
    size_bytes: int
    uploaded_at: str
    chunk_count: int

class DocumentListResponse(BaseModel):
    documents: List[DocumentItem]
    total_chunks: int

class SessionItem(BaseModel):
    id: str
    title: str
    model: str = "llama3"
    effort: str = "medium"
    pinned: bool = False
    archived: bool = False
    created_at: str
    updated_at: str
    message_count: int = 0

class SessionListResponse(BaseModel):
    sessions: List[SessionItem]

class MessageItem(BaseModel):
    id: int
    session_id: str
    role: str
    content: str
    sources: List[SourceItem] = []
    route: Optional[str] = None
    created_at: str

class SessionDetailResponse(BaseModel):
    session: SessionItem
    messages: List[MessageItem]

class CreateSessionRequest(BaseModel):
    session_id: Optional[str] = None
    title: Optional[str] = "New Chat"
    model: Optional[str] = "llama3"
    effort: Optional[str] = "medium"
    pinned: Optional[bool] = False
    archived: Optional[bool] = False

class UpdateSessionRequest(BaseModel):
    title: Optional[str] = None
    model: Optional[str] = None
    effort: Optional[str] = None
    pinned: Optional[bool] = None
    archived: Optional[bool] = None

class SavePartialMessageRequest(BaseModel):
    session_id: str
    role: str = "assistant"
    content: str
    route: Optional[str] = None
    sources: Optional[List[SourceItem]] = []

class ModelListResponse(BaseModel):
    models: List[str]
    default_model: str
