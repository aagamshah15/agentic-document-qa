from typing import Tuple
from services.vector_store import get_vector_store
from services.document_catalog import resolve_target_document, get_document_inventory

WEB_KEYWORDS = [
    "search web", "web search", "search online", "search the web",
    "google", "browse internet", "latest news", "today's weather",
    "weather in", "stock price", "stock of", "who won the", "current news",
    "market cap", "what is happening in the world"
]

DOC_CATALOG_TRIGGERS = [
    "last doc", "latest doc", "just uploaded", "recently uploaded", "recent doc",
    "the doc i", "the file i", "the pdf i", "uploaded doc", "uploaded file",
    "what was the last", "what is the last", "what did i upload", "my upload",
    "what doc", "which doc", "summarise the doc", "summarize the doc",
    "summary of the doc", "last upload", "latest upload", "last document",
    "latest document", "recent document", "newest document", "my files",
    "my documents", "documents uploaded", "uploaded files"
]

def determine_query_route(query: str) -> Tuple[str, float]:
    """
    Decides whether a query should route to 'local_context' or 'web_search'.
    Returns (route_name, score).
    """
    q_lower = query.lower()

    # 1. Keyword check for explicit web search requests
    for kw in WEB_KEYWORDS:
        if kw in q_lower:
            return "web_search", 1.0

    # 2. Check if query is targeting uploaded documents or document library inventory
    docs = get_document_inventory()
    if docs:
        if resolve_target_document(query) is not None:
            return "local_context", 1.0
        if any(trigger in q_lower for trigger in DOC_CATALOG_TRIGGERS):
            return "local_context", 1.0

    # 3. Check if local documents exist in vector store
    try:
        vs = get_vector_store(create_if_missing=False)
        count = vs._collection.count()
        if count == 0:
            return "web_search", 0.0

        # Check semantic similarity score
        results = vs.similarity_search_with_relevance_scores(query, k=1)
        if not results:
            return "web_search", 0.0

        top_doc, score = results[0]
        # In Chroma L2/Cosine, a score < 0.04 indicates no semantic overlap with local docs
        if score < 0.04:
            return "web_search", score

        return "local_context", score
    except Exception:
        # If vector store is empty or unavailable, fallback to web search
        return "web_search", 0.0
