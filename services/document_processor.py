import os
from typing import List
from langchain_community.document_loaders import PyPDFLoader, TextLoader, Docx2txtLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document

SUPPORTED_EXTENSIONS = {".pdf", ".txt", ".md", ".docx"}

def process_document(file_path: str) -> List[Document]:
    """
    Load a document (.pdf, .txt, .md, .docx), extract text, and split into chunks.
    """
    ext = os.path.splitext(file_path)[1].lower()
    
    if ext == ".pdf":
        loader = PyPDFLoader(file_path)
        docs = loader.load()
    elif ext in [".txt", ".md"]:
        loader = TextLoader(file_path, encoding="utf-8")
        docs = loader.load()
    elif ext == ".docx":
        loader = Docx2txtLoader(file_path)
        docs = loader.load()
    else:
        raise ValueError(f"Unsupported file format: {ext}. Supported formats: {', '.join(SUPPORTED_EXTENSIONS)}")

    # Ensure metadata source is clean and standardized
    for doc in docs:
        if "source" not in doc.metadata:
            doc.metadata["source"] = file_path

    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=200,
        length_function=len,
        is_separator_regex=False,
    )
    chunks = text_splitter.split_documents(docs)
    return chunks

# Backwards compatibility alias
def process_pdf(file_path: str) -> List[Document]:
    return process_document(file_path)

