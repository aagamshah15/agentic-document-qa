import os
import stat
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional, Union

# Base upload directory as a Path instance (used across search and inventory modules)
UPLOAD_DIR = Path(__file__).resolve().parent.parent / "data" / "uploads"


def list_documents(upload_dir: Optional[Union[str, Path]] = None) -> List[Dict[str, Any]]:
    """
    Lists all PDF documents in the upload directory with basic metadata.
    Adheres strictly to the document catalog contract:
    - Only includes regular files ending in .pdf (case-insensitive)
    - Returns filename, size_bytes, and indexing_status='unknown'
    - Sorted case-insensitively with stable tie-breaking
    """
    dir_path = Path(upload_dir) if upload_dir is not None else UPLOAD_DIR
    
    if dir_path.is_file():
        raise NotADirectoryError(f"Upload path is a regular file: {dir_path}")
    if not dir_path.exists():
        return []

    documents: List[Dict[str, Any]] = []
    for entry in dir_path.iterdir():
        if not entry.name.lower().endswith(".pdf"):
            continue
        try:
            st = entry.lstat()
        except FileNotFoundError:
            # File removed during directory iteration
            continue

        # Ignore symlinks, directories, sockets, FIFOs
        if not stat.S_ISREG(st.st_mode):
            continue

        documents.append({
            "filename": entry.name,
            "size_bytes": st.st_size,
            "indexing_status": "unknown",
        })

    # Case-insensitive alphabetical sort with stable tie-breaking
    documents.sort(key=lambda d: (d["filename"].casefold(), d["filename"]))
    return documents


def get_document_inventory(upload_dir: Optional[Union[str, Path]] = None) -> List[Dict[str, Any]]:
    """
    Returns list of all uploaded documents (.pdf, .txt, .docx, .md, etc.)
    sorted by modification time descending (most recent upload first).
    """
    dir_path = Path(upload_dir) if upload_dir is not None else UPLOAD_DIR
    if not dir_path.exists() or not dir_path.is_dir():
        return []

    docs = []
    for entry in dir_path.iterdir():
        if entry.name.startswith("."):
            continue
        try:
            st = entry.lstat()
        except FileNotFoundError:
            continue

        if not stat.S_ISREG(st.st_mode):
            continue

        docs.append({
            "filename": entry.name,
            "path": str(entry.resolve()),
            "mtime": st.st_mtime,
            "size_bytes": st.st_size,
            "formatted_time": datetime.fromtimestamp(st.st_mtime).strftime("%b %d, %Y %I:%M %p"),
        })

    docs.sort(key=lambda d: d["mtime"], reverse=True)
    return docs


def get_most_recent_document(upload_dir: Optional[Union[str, Path]] = None) -> Optional[Dict[str, Any]]:
    """Returns the most recently uploaded file, or None if no documents exist."""
    docs = get_document_inventory(upload_dir)
    return docs[0] if docs else None


def get_document_manifest_text() -> str:
    """
    Formats the indexed document catalog into a concise markdown manifest for LLM prompts.
    """
    docs = get_document_inventory()
    if not docs:
        return "No documents currently uploaded."

    lines = ["Available Uploaded Documents (most recent first):"]
    for i, doc in enumerate(docs):
        tag = " [MOST RECENT UPLOAD]" if i == 0 else ""
        lines.append(f"• \"{doc['filename']}\" (Uploaded: {doc['formatted_time']}){tag}")
    return "\n".join(lines)


def resolve_target_document(query: str, history: Optional[List[Any]] = None) -> Optional[str]:
    """
    Determines if a query (or recent conversation context) explicitly or implicitly
    targets a specific document or the most recently uploaded document.
    """
    docs = get_document_inventory()
    if not docs:
        return None

    q_lower = query.lower().strip()

    # 1. Recency & latest-document trigger phrases
    recency_triggers = [
        "just uploaded",
        "last uploaded",
        "last doc",
        "latest doc",
        "latest file",
        "latest pdf",
        "recent doc",
        "recent file",
        "recently uploaded",
        "newest doc",
        "newest file",
        "the doc i uploaded",
        "the file i uploaded",
        "the pdf i uploaded",
        "the uploaded doc",
        "the uploaded file",
        "the uploaded pdf",
        "what was the last doc",
        "what is the last doc",
        "which doc was last",
        "what did i upload",
        "most recent doc",
        "most recent document",
        "most recent file",
        "last document",
        "latest document",
    ]
    if any(trigger in q_lower for trigger in recency_triggers):
        return docs[0]["filename"]

    # 2. Exact or partial filename matches
    stop_words = {"in", "on", "at", "for", "and", "the", "a", "an", "to", "is", "of", "with", "by", "pdf", "txt", "md", "docx"}
    for doc in docs:
        fname = doc["filename"]
        fname_lower = fname.lower()
        fname_no_ext = os.path.splitext(fname_lower)[0]

        # Exact match or match without extension
        if fname_lower in q_lower or fname_no_ext in q_lower:
            return fname

        # Meaningful tokens from filename
        raw_words = [w for w in fname_no_ext.replace("_", " ").replace("-", " ").split() if w]
        meaningful_words = [w for w in raw_words if w not in stop_words and len(w) >= 2]

        # Check if consecutive phrase appears in query (e.g. "te 460")
        for i in range(len(meaningful_words) - 1):
            phrase = f"{meaningful_words[i]} {meaningful_words[i+1]}"
            if phrase in q_lower:
                return fname

        # Distinctive tokens matching query
        matches = [w for w in meaningful_words if w in q_lower]
        if len(matches) >= 2 or (len(matches) == 1 and len(matches[0]) >= 6):
            return fname

    # 3. Check history if the current query is an isolated follow-up
    if history:
        for prev in reversed(history[-2:]):
            prev_content = getattr(prev, "content", "") if hasattr(prev, "content") else str(prev)
            prev_lower = prev_content.lower()
            if any(trigger in prev_lower for trigger in recency_triggers):
                return docs[0]["filename"]

    # 4. If there is only ONE document in the system and user refers to "the doc" or "the document"
    if len(docs) == 1 and ("doc" in q_lower or "document" in q_lower or "pdf" in q_lower or "file" in q_lower):
        return docs[0]["filename"]

    return None
