import os
from typing import List, Optional, Dict, Any, Union
from langchain_ollama import ChatOllama
from langchain.chains import create_history_aware_retriever, create_retrieval_chain
from langchain.chains.combine_documents import create_stuff_documents_chain
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import HumanMessage, AIMessage, BaseMessage

from core.config import settings
from services.vector_store import get_retriever, get_targeted_document_chunks
from services.document_catalog import (
    get_document_manifest_text,
    resolve_target_document,
    get_most_recent_document,
)

# In-memory session history store (for quick mutations and test compatibility)
session_histories: Dict[str, List[BaseMessage]] = {}

def get_session_history(session_id: str) -> List[BaseMessage]:
    if session_id not in session_histories:
        session_histories[session_id] = []
    return session_histories[session_id]

def clear_session_history(session_id: str):
    session_histories[session_id] = []

def format_chat_history(history: Optional[List[Any]]) -> List[BaseMessage]:
    """
    Converts list of chat message dicts or objects into LangChain BaseMessage objects.
    """
    messages: List[BaseMessage] = []
    if not history:
        return messages

    for msg in history:
        role = msg.get("role") if isinstance(msg, dict) else getattr(msg, "role", "")
        content = msg.get("content") if isinstance(msg, dict) else getattr(msg, "content", "")
        if role == "user":
            messages.append(HumanMessage(content=content))
        elif role == "assistant":
            messages.append(AIMessage(content=content))
    return messages

def extract_sources(context_docs: List[Any]) -> List[Dict[str, Any]]:
    """
    Extracts deduplicated citations with 1-indexed page numbers and snippets.
    """
    sources = []
    seen = set()
    for doc in context_docs:
        meta = getattr(doc, "metadata", {}) or {}
        src = meta.get("source", "")
        fname = os.path.basename(src) if src else "Document"
        page = meta.get("page", None)
        page_num = (page + 1) if isinstance(page, int) else None
        snippet = doc.page_content.strip()
        key = (fname, page_num, snippet[:100])
        if key in seen:
            continue
        seen.add(key)
        sources.append({
            "source": fname,
            "page": page_num,
            "snippet": snippet[:260] + ("..." if len(snippet) > 260 else "")
        })
    return sources

def get_conversational_rag_chain(
    model: str = "llama3",
    effort: str = "medium",
    target_filename: Optional[str] = None,
    document_manifest: Optional[str] = None,
):
    """
    Constructs a conversational RAG chain configured with the chosen model, reasoning effort,
    and optional target document filter.
    """
    temp = 0.3
    depth_prompt = "Keep your answer concise and helpful."
    if effort == "low":
        temp = 0.1
        depth_prompt = "Provide a direct, high-speed answer with minimal preamble."
    elif effort == "high":
        temp = 0.7
        depth_prompt = "Think step-by-step, provide thorough analysis, and explain nuances from the context in depth."

    manifest = document_manifest or get_document_manifest_text()
    retriever = get_retriever(target_filename=target_filename)
    llm = ChatOllama(model=model or "llama3", temperature=temp)

    # 1. Contextualize question prompt (reformulates questions based on chat history & catalog)
    contextualize_q_system_prompt = (
        "Given a chat history, the uploaded document catalog, and the latest user question "
        "which might reference context in the chat history or uploaded files, "
        "formulate a standalone question which can be understood without the chat history. "
        "If the user asks about 'the doc I just uploaded', 'the latest doc', 'the recent file', "
        "or references a specific document, identify the document from the catalog. "
        "Do NOT answer the question, just reformulate it if needed and otherwise return it as is.\n\n"
        f"{manifest}"
    )
    contextualize_q_prompt = ChatPromptTemplate.from_messages([
        ("system", contextualize_q_system_prompt),
        MessagesPlaceholder("chat_history"),
        ("human", "{input}"),
    ])
    history_aware_retriever = create_history_aware_retriever(
        llm, retriever, contextualize_q_prompt
    )

    # 2. Answer question prompt with manifest awareness
    qa_system_prompt = (
        "You are an expert Q&A intelligence assistant with full access to the uploaded document catalog and retrieved context.\n\n"
        f"{manifest}\n\n"
        "Guidelines:\n"
        "- The document catalog above displays all uploaded documents sorted by modification time (most recent first).\n"
        "- If the user asks what was the last doc, newest doc, or most recently uploaded file, refer directly to the document marked [MOST RECENT UPLOAD].\n"
        "- If the user asks to summarize or query the latest document, use the retrieved context from that document.\n"
        "- Use the following pieces of retrieved context to answer the user's question.\n"
        "- If the context doesn't contain the answer, you can use your general knowledge to answer.\n"
        "- If you don't know the answer, just say that you don't know.\n"
        "- Provide a direct, succinct answer. Do NOT output a separate 'Sources' list, raw file paths, or URL lists in your answer. Citations are displayed automatically in the UI Sources panel.\n"
        "- If multiple perspectives or definitions exist, list them cleanly with compact bullet points.\n"
        f"{depth_prompt}\n\n"
        "Context:\n{context}"
    )
    qa_prompt = ChatPromptTemplate.from_messages([
        ("system", qa_system_prompt),
        MessagesPlaceholder("chat_history"),
        ("human", "{input}"),
    ])
    question_answer_chain = create_stuff_documents_chain(llm, qa_prompt)

    # 3. Create full retrieval chain
    rag_chain = create_retrieval_chain(history_aware_retriever, question_answer_chain)
    return rag_chain

class ConversationalRAGExecutor:
    def __init__(self, model: str = "llama3", effort: str = "medium"):
        self.model = model
        self.effort = effort

    def _get_chain_for_query(self, user_input: str, chat_history: List[Any]):
        target_file = resolve_target_document(user_input, chat_history)
        manifest = get_document_manifest_text()
        chain = get_conversational_rag_chain(
            model=self.model,
            effort=self.effort,
            target_filename=target_file,
            document_manifest=manifest,
        )
        return chain, target_file

    def invoke(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        user_input = inputs.get("input", "")
        chat_history = inputs.get("chat_history", [])
        chain, target_file = self._get_chain_for_query(user_input, chat_history)
        
        result = chain.invoke({
            "input": user_input,
            "chat_history": chat_history,
        })
        sources = extract_sources(result.get("context", []))
        if not sources and target_file:
            sources = [{"source": target_file, "page": None, "snippet": f"Uploaded document: {target_file}"}]
        return {
            "output": result.get("answer", ""),
            "sources": sources,
        }

    async def astream(self, inputs: Dict[str, Any]):
        user_input = inputs.get("input", "")
        chat_history = inputs.get("chat_history", [])
        chain, target_file = self._get_chain_for_query(user_input, chat_history)
        
        async for chunk in chain.astream({
            "input": user_input,
            "chat_history": chat_history,
        }):
            yield chunk

def get_agent_executor(model: str = "llama3", effort: str = "medium"):
    """
    Factory function returning the conversational RAG executor with specified model and effort.
    """
    return ConversationalRAGExecutor(model=model, effort=effort)
