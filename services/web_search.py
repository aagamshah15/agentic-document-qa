import os
import re
from typing import List, Dict, Any, AsyncGenerator
from ddgs import DDGS
from langchain_ollama import ChatOllama
from langchain_core.prompts import ChatPromptTemplate

# Maintained for backwards compatibility with tests
WEB_SEARCH_NOTICE = (
    "🌐 **Live Web Search**\n\n"
    "> *Information for this query was not found in your uploaded documents. "
    "The following answer was retrieved from a live web search instead of local context:*\n\n"
)


def clean_answer_text(text: str) -> str:
    """
    Strips accidental source dumps, URL lists, or disclaimers from LLM responses.
    """
    # Remove any prepended banner or disclaimer
    text = re.sub(r'^(🌐\s*)?(\*\*Live Web Search\*\*)?\s*', '', text).strip()
    text = re.sub(r'^>\s*\*Information for this query[^\n]*\n*', '', text).strip()
    
    # Remove accidental trailing "Sources:", "References:", "Source [1]: ...", "URL: ..."
    patterns = [
        r'\n+(Here are (some )?(relevant )?search results:.*)',
        r'\n+(Source \[\d+\]:.*)',
        r'\n+(URL: https?://.*)',
        r'\n+(\*\*Sources\*\*:?.*)',
        r'\n+(Sources:.*)',
        r'\n+(References:.*)',
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
        if match:
            text = text[:match.start()].strip()
            
    return text.strip()


def search_web(query: str, max_results: int = 4) -> List[Dict[str, str]]:
    """
    Execute live web search using resilient backends (bing, yahoo, wikipedia)
    and return list of {title, url, snippet}.
    """
    results = []
    # Try high-availability providers in order of reliability
    backends = ["bing", "yahoo", "auto"]
    for backend in backends:
        try:
            raw = list(DDGS().text(query, backend=backend, max_results=max_results))
            if raw:
                for item in raw:
                    results.append({
                        "title": item.get("title", "Web Source"),
                        "url": item.get("href", item.get("url", "")),
                        "snippet": item.get("body", item.get("snippet", "")),
                    })
                return results[:max_results]
        except Exception:
            continue

    # Fallback to Wikipedia engine for factual/encyclopedic lookups
    try:
        raw = list(DDGS().text(query, backend="wikipedia", max_results=max_results))
        if raw:
            for item in raw:
                results.append({
                    "title": item.get("title", "Wikipedia"),
                    "url": item.get("href", item.get("url", "")),
                    "snippet": item.get("body", item.get("snippet", "")),
                })
            return results[:max_results]
    except Exception:
        pass

    return results


def answer_with_web_search(query: str, model: str = "llama3", effort: str = "medium") -> Dict[str, Any]:
    """
    Perform live web search and synthesize a direct, succinct answer with numbered citations.
    """
    search_results = search_web(query)
    
    if not search_results:
        return {
            "answer": f"I searched the web for **'{query}'**, but could not retrieve any live results at this moment.",
            "sources": [],
            "route": "web_search",
            "notice": "No live web search results found."
        }

    items = []
    for i, r in enumerate(search_results):
        items.append(f"[{i+1}] {r['title']}: {r['snippet']}")
    web_context = "\n\n".join(items)

    temp = 0.1 if effort == "low" else (0.7 if effort == "high" else 0.3)
    llm = ChatOllama(model=model or "llama3", temperature=temp)
    prompt = ChatPromptTemplate.from_messages([
        ("system", (
            "You are a concise, expert intelligence assistant.\n"
            "Synthesize a direct, succinct answer using ONLY the provided web context.\n\n"
            "STRICT RULES:\n"
            "1. Be direct and succinct. Answer the user prompt immediately without introductory fluff or disclaimers.\n"
            "2. If multiple definitions, answers, or perspectives are found online, list them down cleanly as concise bullet points.\n"
            "3. Attribute facts or points using bracketed numbers matching the source items (e.g. [1], [2], [3]).\n"
            "4. NEVER output raw URLs, website links, snippets, or a 'Sources' / 'References' section. Citations are handled by the UI in the Sources button.\n"
            "5. Do NOT include phrases like 'Here are the search results:' or 'Based on the web search results:'."
            "\n\nWeb Search Context:\n{web_context}"
        )),
        ("human", "{query}")
    ])
    chain = prompt | llm
    res = chain.invoke({"web_context": web_context, "query": query})
    raw_answer = res.content if hasattr(res, "content") else str(res)
    answer_text = clean_answer_text(raw_answer)

    sources = [
        {
            "source": r["title"],
            "url": r["url"],
            "page": None,
            "snippet": r["snippet"][:260] + ("..." if len(r["snippet"]) > 260 else "")
        }
        for r in search_results
    ]

    return {
        "answer": answer_text,
        "sources": sources,
        "route": "web_search",
        "notice": "Information retrieved from live web search."
    }


async def stream_web_search_answer(
    query: str,
    model: str = "llama3",
    effort: str = "medium"
) -> AsyncGenerator[Dict[str, Any], None]:
    """
    Stream answer using live web search and the specified model and effort.
    Yields clean tokens without preambles, disclaimers, or raw source dumps.
    """
    search_results = search_web(query)
    sources = [
        {
            "source": r["title"],
            "url": r["url"],
            "page": None,
            "snippet": r["snippet"][:260] + ("..." if len(r["snippet"]) > 260 else "")
        }
        for r in search_results
    ]

    yield {
        "route": "web_search",
        "notice": "Information retrieved from live web search."
    }

    if not search_results:
        yield {
            "token": f"I searched the web for **'{query}'**, but could not retrieve any live results at this moment."
        }
        yield {
            "done": True,
            "sources": [],
            "route": "web_search"
        }
        return

    items = []
    for i, r in enumerate(search_results):
        items.append(f"[{i+1}] {r['title']}: {r['snippet']}")
    web_context = "\n\n".join(items)

    temp = 0.1 if effort == "low" else (0.7 if effort == "high" else 0.3)
    llm = ChatOllama(model=model or "llama3", temperature=temp)
    prompt = ChatPromptTemplate.from_messages([
        ("system", (
            "You are a concise, expert intelligence assistant.\n"
            "Synthesize a direct, succinct answer using ONLY the provided web context.\n\n"
            "STRICT RULES:\n"
            "1. Be direct and succinct. Answer the user prompt immediately without introductory fluff or disclaimers.\n"
            "2. If multiple definitions, answers, or perspectives are found online, list them down cleanly as concise bullet points.\n"
            "3. Attribute facts or points using bracketed numbers matching the source items (e.g. [1], [2], [3]).\n"
            "4. NEVER output raw URLs, website links, snippets, or a 'Sources' / 'References' section. Citations are handled by the UI in the Sources button.\n"
            "5. Do NOT include phrases like 'Here are the search results:' or 'Based on the web search results:'."
            "\n\nWeb Search Context:\n{web_context}"
        )),
        ("human", "{query}")
    ])
    chain = prompt | llm

    stop_phrases = [
        "here are some relevant search results",
        "here are relevant search results",
        "source [1]:",
        "url: http",
        "url:http",
        "\nreferences:",
        "\nsources:"
    ]
    full_text = ""
    stopped = False

    async for chunk in chain.astream({"web_context": web_context, "query": query}):
        token = chunk.content if hasattr(chunk, "content") else str(chunk)
        if not token:
            continue
        full_text += token

        lower_full = full_text.lower()
        for phrase in stop_phrases:
            if phrase in lower_full:
                stopped = True
                break
        if stopped:
            break

        yield {"token": token}

    yield {
        "done": True,
        "sources": sources,
        "route": "web_search",
        "notice": "Information retrieved from live web search."
    }
