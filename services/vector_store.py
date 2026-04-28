import os
from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings

from core.config import settings

# Directory to save the local Chroma database
CHROMA_PERSIST_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "chroma_db")

def get_vector_store():
    """
    Returns an instance of the Chroma vector store.
    """
    # Use HuggingFace embeddings
    embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
    
    # Check if the persist directory exists
    os.makedirs(CHROMA_PERSIST_DIR, exist_ok=True)
    
    vector_store = Chroma(
        collection_name="agentic_qa_collection",
        embedding_function=embeddings,
        persist_directory=CHROMA_PERSIST_DIR
    )
    return vector_store

def add_documents_to_store(chunks):
    """
    Add a list of document chunks to the vector store.
    """
    vector_store = get_vector_store()
    vector_store.add_documents(chunks)
    
def get_retriever():
    """
    Returns a retriever interface for the vector store.
    """
    vector_store = get_vector_store()
    return vector_store.as_retriever(search_kwargs={"k": 4})
