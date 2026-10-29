import os
import json
import sqlite3
from datetime import datetime
from typing import List, Dict, Any, Optional
from langchain_core.messages import HumanMessage, AIMessage, BaseMessage

# Path to the persistent SQLite database
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "chat_history.db")

def get_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    """Initialize SQLite database tables for multi-chat sessions and persistent message memory."""
    with get_db_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                model TEXT NOT NULL DEFAULT 'llama3',
                effort TEXT NOT NULL DEFAULT 'medium',
                pinned INTEGER DEFAULT 0,
                archived INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Ensure pinned and archived columns exist in existing databases
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(sessions)")
        cols = [row["name"] for row in cursor.fetchall()]
        if "pinned" not in cols:
            cursor.execute("ALTER TABLE sessions ADD COLUMN pinned INTEGER DEFAULT 0")
        if "archived" not in cols:
            cursor.execute("ALTER TABLE sessions ADD COLUMN archived INTEGER DEFAULT 0")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                sources TEXT,
                route TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_messages_session_id ON messages(session_id)
        """)
        conn.commit()

# Ensure tables exist on module import
init_db()

def create_or_get_session(
    session_id: str,
    title: Optional[str] = "New Chat",
    model: str = "llama3",
    effort: str = "medium",
    pinned: bool = False,
    archived: bool = False
) -> Dict[str, Any]:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM sessions WHERE id = ?", (session_id,))
        row = cursor.fetchone()
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if not row:
            cursor.execute(
                """
                INSERT INTO sessions (id, title, model, effort, pinned, archived, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (session_id, title or "New Chat", model or "llama3", effort or "medium", 1 if pinned else 0, 1 if archived else 0, now_str, now_str)
            )
            conn.commit()
            return {
                "id": session_id,
                "title": title or "New Chat",
                "model": model or "llama3",
                "effort": effort or "medium",
                "pinned": bool(pinned),
                "archived": bool(archived),
                "created_at": now_str,
                "updated_at": now_str,
                "message_count": 0,
            }
        
        # Count messages
        cursor.execute("SELECT COUNT(*) as count FROM messages WHERE session_id = ?", (session_id,))
        count_row = cursor.fetchone()
        msg_count = count_row["count"] if count_row else 0
        return {
            "id": row["id"],
            "title": row["title"],
            "model": row["model"],
            "effort": row["effort"],
            "pinned": bool(row["pinned"]) if "pinned" in row.keys() else False,
            "archived": bool(row["archived"]) if "archived" in row.keys() else False,
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
            "message_count": msg_count,
        }

def list_sessions(include_archived: bool = True) -> List[Dict[str, Any]]:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        query = """
            SELECT s.*, COUNT(m.id) as message_count
            FROM sessions s
            LEFT JOIN messages m ON s.id = m.session_id
        """
        if not include_archived:
            query += " WHERE s.archived = 0 "
        query += """
            GROUP BY s.id
            ORDER BY s.pinned DESC, s.updated_at DESC
        """
        cursor.execute(query)
        rows = cursor.fetchall()
        return [
            {
                "id": row["id"],
                "title": row["title"],
                "model": row["model"],
                "effort": row["effort"],
                "pinned": bool(row["pinned"]) if "pinned" in row.keys() else False,
                "archived": bool(row["archived"]) if "archived" in row.keys() else False,
                "created_at": str(row["created_at"]),
                "updated_at": str(row["updated_at"]),
                "message_count": row["message_count"],
            }
            for row in rows
        ]

def get_session_details(session_id: str) -> Optional[Dict[str, Any]]:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM sessions WHERE id = ?", (session_id,))
        s_row = cursor.fetchone()
        if not s_row:
            return None
        
        cursor.execute(
            "SELECT * FROM messages WHERE session_id = ? ORDER BY id ASC",
            (session_id,)
        )
        m_rows = cursor.fetchall()
        messages = []
        for m in m_rows:
            sources = []
            if m["sources"]:
                try:
                    sources = json.loads(m["sources"])
                except Exception:
                    sources = []
            messages.append({
                "id": m["id"],
                "session_id": m["session_id"],
                "role": m["role"],
                "content": m["content"],
                "sources": sources,
                "route": m["route"],
                "created_at": str(m["created_at"]),
            })
        
        return {
            "session": {
                "id": s_row["id"],
                "title": s_row["title"],
                "model": s_row["model"],
                "effort": s_row["effort"],
                "pinned": bool(s_row["pinned"]) if "pinned" in s_row.keys() else False,
                "archived": bool(s_row["archived"]) if "archived" in s_row.keys() else False,
                "created_at": str(s_row["created_at"]),
                "updated_at": str(s_row["updated_at"]),
                "message_count": len(messages),
            },
            "messages": messages,
        }

def add_message(
    session_id: str,
    role: str,
    content: str,
    sources: Optional[List[Dict[str, Any]]] = None,
    route: Optional[str] = None
) -> int:
    create_or_get_session(session_id)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sources_json = json.dumps(sources) if sources else None
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO messages (session_id, role, content, sources, route, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (session_id, role, content, sources_json, route, now_str)
        )
        msg_id = cursor.lastrowid
        cursor.execute(
            "UPDATE sessions SET updated_at = ? WHERE id = ?",
            (now_str, session_id)
        )
        conn.commit()
        return msg_id

def update_session_title_if_default(session_id: str, user_prompt: str):
    """Auto-title the session using the first user prompt if the title is still 'New Chat'."""
    clean_prompt = user_prompt.strip()
    if not clean_prompt:
        return
    # Truncate title cleanly to 42 characters
    title = clean_prompt[:42] + ("..." if len(clean_prompt) > 42 else "")
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT title FROM sessions WHERE id = ?", (session_id,))
        row = cursor.fetchone()
        if row and row["title"] == "New Chat":
            cursor.execute(
                "UPDATE sessions SET title = ? WHERE id = ?",
                (title, session_id)
            )
            conn.commit()

def update_session_settings(
    session_id: str,
    title: Optional[str] = None,
    model: Optional[str] = None,
    effort: Optional[str] = None,
    pinned: Optional[bool] = None,
    archived: Optional[bool] = None
) -> bool:
    updates = []
    params = []
    if title is not None:
        updates.append("title = ?")
        params.append(title)
    if model is not None:
        updates.append("model = ?")
        params.append(model)
    if effort is not None:
        updates.append("effort = ?")
        params.append(effort)
    if pinned is not None:
        updates.append("pinned = ?")
        params.append(1 if pinned else 0)
    if archived is not None:
        updates.append("archived = ?")
        params.append(1 if archived else 0)
    
    if not updates:
        return False
        
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    updates.append("updated_at = ?")
    params.append(now_str)
    params.append(session_id)
    
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            f"UPDATE sessions SET {', '.join(updates)} WHERE id = ?",
            params
        )
        conn.commit()
        return cursor.rowcount > 0

def delete_session(session_id: str) -> bool:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        conn.commit()
        return cursor.rowcount > 0

def clear_session_messages(session_id: str) -> bool:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        conn.commit()
        return True

def get_langchain_history(session_id: str, limit: int = 12) -> List[BaseMessage]:
    """Retrieve the recent conversation history as LangChain BaseMessage objects."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT role, content FROM (
                SELECT id, role, content FROM messages
                WHERE session_id = ?
                ORDER BY id DESC
                LIMIT ?
            ) ORDER BY id ASC
            """,
            (session_id, limit)
        )
        rows = cursor.fetchall()
        history: List[BaseMessage] = []
        for r in rows:
            if r["role"] == "user":
                history.append(HumanMessage(content=r["content"]))
            elif r["role"] == "assistant":
                history.append(AIMessage(content=r["content"]))
        return history
