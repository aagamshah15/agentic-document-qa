import os
from typing import AsyncGenerator
from langchain_ollama import ChatOllama
from langchain_core.prompts import ChatPromptTemplate
from services.document_processor import process_document

SUMMARY_SYSTEM_PROMPT = (
    "You are an expert executive document analyst. "
    "Generate a clear, high-quality executive summary of the provided document text. "
    "Structure your summary with the following clean sections:\n"
    "• Executive Overview\n"
    "• Key Findings & Main Points\n"
    "• Significant Details & Metrics\n"
    "• Conclusions & Strategic Takeaways\n\n"
    "Keep the summary concise, objective, and well-organized."
)

def prepare_summary_text(file_path: str, max_chars: int = 16000) -> str:
    chunks = process_document(file_path)
    if not chunks:
        return ""
    full_text = "\n\n".join(c.page_content for c in chunks)
    if len(full_text) > max_chars:
        full_text = full_text[:max_chars] + "\n\n... [Content truncated for summary] ..."
    return full_text

def generate_document_summary(file_path: str, max_chars: int = 16000, model: str = "llama3") -> str:
    text = prepare_summary_text(file_path, max_chars=max_chars)
    if not text:
        return "The document appears to be empty or has no readable text."
    
    llm = ChatOllama(model=model or "llama3", temperature=0.2)
    prompt = ChatPromptTemplate.from_messages([
        ("system", SUMMARY_SYSTEM_PROMPT),
        ("human", "Document content:\n\n{text}")
    ])
    chain = prompt | llm
    result = chain.invoke({"text": text})
    return result.content if hasattr(result, "content") else str(result)

async def stream_document_summary(
    file_path: str,
    max_chars: int = 16000,
    model: str = "llama3"
) -> AsyncGenerator[str, None]:
    text = prepare_summary_text(file_path, max_chars=max_chars)
    if not text:
        yield "The document appears to be empty or has no readable text."
        return

    llm = ChatOllama(model=model or "llama3", temperature=0.2)
    prompt = ChatPromptTemplate.from_messages([
        ("system", SUMMARY_SYSTEM_PROMPT),
        ("human", "Document content:\n\n{text}")
    ])
    chain = prompt | llm
    async for chunk in chain.astream({"text": text}):
        token = chunk.content if hasattr(chunk, "content") else str(chunk)
        if token:
            yield token
