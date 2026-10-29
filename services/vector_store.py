import os
from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings

# Avoid network timeouts when offline
os.environ.setdefault("HF_HUB_OFFLINE", "1")

# Directory to save the local Chroma database
CHROMA_PERSIST_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "chroma_db")

_CACHED_EMBEDDINGS = None

def get_embeddings():
    global _CACHED_EMBEDDINGS
    if _CACHED_EMBEDDINGS is None:
        _CACHED_EMBEDDINGS = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
    return _CACHED_EMBEDDINGS

def get_vector_store(*, create_if_missing: bool = True):
    """
    Open the Chroma store; search callers can forbid creating missing storage.
    """
    if not create_if_missing and not os.path.isfile(os.path.join(CHROMA_PERSIST_DIR, "chroma.sqlite3")):
        raise FileNotFoundError("The document index does not exist. Upload and index a PDF first.")

    embeddings = get_embeddings()
    
    # Check if the persist directory exists
    if create_if_missing:
        os.makedirs(CHROMA_PERSIST_DIR, exist_ok=True)
    
    vector_store = Chroma(
        collection_name="agentic_qa_collection",
        embedding_function=embeddings,
        persist_directory=CHROMA_PERSIST_DIR,
        create_collection_if_not_exists=create_if_missing,
    )
    return vector_store

def add_documents_to_store(chunks):
    """
    Add a list of document chunks to the vector store.
    """
    vector_store = get_vector_store()
    vector_store.add_documents(chunks)

def get_retriever(target_filename: str = None, k: int = 4):
    """
    Returns a retriever interface for the vector store.
    If target_filename is specified, scopes retrieval to that document's source path.
    """
    vector_store = get_vector_store()
    search_kwargs = {"k": k}
    if target_filename:
        if os.path.isabs(target_filename):
            search_kwargs["filter"] = {"source": target_filename}
        else:
            from services.document_catalog import UPLOAD_DIR
            search_kwargs["filter"] = {"source": str(UPLOAD_DIR / target_filename)}
    return vector_store.as_retriever(search_kwargs=search_kwargs)

def get_targeted_document_chunks(filename: str, query: str = "", k: int = 5):
    """
    Directly retrieves relevant chunks for a specific document.
    """
    from services.document_catalog import UPLOAD_DIR
    vector_store = get_vector_store()
    abs_path = os.path.join(str(UPLOAD_DIR), filename)
    try:
        results = vector_store.similarity_search(
            query if query else "summary overview introduction main content",
            k=k,
            filter={"source": abs_path}
        )
        if results:
            return results
    except Exception:
        pass

    try:
        collection = vector_store._collection
        data = collection.get(include=["metadatas", "documents"])
        matched_ids = []
        for doc_id, meta in zip(data.get("ids", []), data.get("metadatas", [])):
            if meta and (os.path.basename(meta.get("source", "")) == filename or meta.get("source", "") == filename):
                matched_ids.append(doc_id)

        if matched_ids:
            raw = collection.get(ids=matched_ids[:k], include=["metadatas", "documents"])
            from langchain_core.documents import Document
            return [
                Document(page_content=text, metadata=meta)
                for text, meta in zip(raw.get("documents", []), raw.get("metadatas", []))
            ]
    except Exception:
        pass
    return []

def get_document_chunk_counts() -> dict:
    """
    Returns a dictionary of {filename: chunk_count} from the Chroma collection.
    """
    try:
        vector_store = get_vector_store(create_if_missing=False)
        collection = vector_store._collection
        data = collection.get(include=["metadatas"])
        counts = {}
        for meta in data.get("metadatas", []):
            if not meta:
                continue
            src = meta.get("source", "")
            fname = os.path.basename(src) if src else "Unknown Document"
            counts[fname] = counts.get(fname, 0) + 1
        return counts
    except Exception:
        return {}

def delete_document_from_store(filename: str) -> int:
    """
    Deletes all vectors belonging to a specific filename from ChromaDB.
    Returns the number of chunks deleted.
    """
    try:
        vector_store = get_vector_store(create_if_missing=False)
        collection = vector_store._collection
        data = collection.get(include=["metadatas"])
        ids_to_delete = []
        for doc_id, meta in zip(data.get("ids", []), data.get("metadatas", [])):
            if not meta:
                continue
            src = meta.get("source", "")
            if os.path.basename(src) == filename or src == filename:
                ids_to_delete.append(doc_id)
        if ids_to_delete:
            collection.delete(ids=ids_to_delete)
        return len(ids_to_delete)
    except Exception:
        return 0

def clear_vector_store():
    """
    Deletes all vectors from the Chroma collection.
    """
    try:
        vector_store = get_vector_store(create_if_missing=False)
        collection = vector_store._collection
        all_ids = collection.get().get("ids", [])
        if all_ids:
            collection.delete(ids=all_ids)
    except Exception:
        pass

