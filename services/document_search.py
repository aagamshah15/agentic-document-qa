"""Retrieve evidence from the existing PDF index without generating an answer."""

import math
from typing import Any, Dict, List, Optional, Protocol, Sequence, Tuple, TypedDict

from services.document_catalog import UPLOAD_DIR


MAX_QUERY_CHARS = 2000
MAX_RESULTS = 8
MAX_EXCERPT_CHARS = 1200


class IndexedChunk(Protocol):
    page_content: str
    metadata: Dict[str, Any]


class SearchBackend(Protocol):
    def similarity_search_with_score(
        self, query: str, *, k: int, filter: Optional[Dict[str, str]] = None
    ) -> Sequence[Tuple[IndexedChunk, float]]:
        ...


class SearchMatch(TypedDict):
    filename: Optional[str]
    page: Optional[int]
    excerpt: str
    truncated: bool
    distance: float


def _open_existing_index() -> SearchBackend:
    # Lazy import: argument validation and tests need no embedding dependencies.
    from services.vector_store import get_vector_store

    return get_vector_store(create_if_missing=False)


def search_documents(
    query: str,
    *,
    filename: Optional[str] = None,
    limit: int = 4,
    backend: Optional[SearchBackend] = None,
) -> List[SearchMatch]:
    """Return up to `limit` nearest indexed passages in backend-ranked order.

    `filename` is an exact PDF basename, scoped before retrieval using the
    absolute source path recorded by the current upload pipeline. No file is
    opened using this input. Omitting it searches the entire indexed collection.

    Page numbers are one-based physical PDF pages; unknown source/page metadata
    remains None. Distances are Chroma distances (lower is closer), not answer
    confidence. No relevance cutoff is applied. Blank chunks are skipped.

    A successful empty search returns []; missing indexes and backend failures
    raise errors. Saved PDFs are not necessarily indexed, and indexed chunks can
    outlive the original file. This function neither uploads nor reindexes PDFs.

    `backend` is an application/test dependency, not a model-facing parameter.
    Reuse an opened backend for repeated queries to avoid reloading embeddings.
    """
    if not isinstance(query, str):
        raise TypeError("query must be a string")
    query = query.strip()
    if not query or len(query) > MAX_QUERY_CHARS:
        raise ValueError(f"query must contain 1 to {MAX_QUERY_CHARS} characters")
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise TypeError("limit must be an integer")
    if not 1 <= limit <= MAX_RESULTS:
        raise ValueError(f"limit must be between 1 and {MAX_RESULTS}")

    source_filter = None
    if filename is not None:
        if not isinstance(filename, str):
            raise TypeError("filename must be a string or None")
        if (
            not filename or filename in (".", "..")
            or any(character in filename for character in ("/", "\\", "\x00"))
            or not filename.lower().endswith(".pdf")
        ):
            raise ValueError("filename must be a PDF basename, not a path")
        source_filter = {"source": str(UPLOAD_DIR / filename)}

    store = backend if backend is not None else _open_existing_index()
    candidates = store.similarity_search_with_score(query, k=limit, filter=source_filter)

    matches: List[SearchMatch] = []
    for chunk, raw_distance in candidates[:limit]:
        text = chunk.page_content
        if not text.strip():
            continue
        metadata = chunk.metadata or {}
        source = metadata.get("source")
        source_name = source.replace("\\", "/").rsplit("/", 1)[-1] if isinstance(source, str) else None
        page = metadata.get("page")
        page_number = page + 1 if isinstance(page, int) and not isinstance(page, bool) and page >= 0 else None
        distance = float(raw_distance)
        if not math.isfinite(distance):
            raise ValueError("Search backend returned a non-finite distance")
        matches.append({
            "filename": source_name or None,
            "page": page_number,
            "excerpt": text[:MAX_EXCERPT_CHARS],
            "truncated": len(text) > MAX_EXCERPT_CHARS,
            "distance": distance,
        })
    return matches
