"""
Autonomous Data Agent & Intelligence Orchestrator (Squad C - Agentic Intelligence).

Orchestrates:
1. services/nl_sql.py (Natural Language to SQL translator)
2. services/data_cleaner.py (Automated data cleanup, deduplication, imputation)
3. services/migration_architect.py (Schema migration DDL, Alembic, rollback logic)

Exposes:
stream_data_agent_response(payload: AgentPromptRequest) -> AsyncGenerator[str, None]
Streaming tokens via Server-Sent Events (SSE). Supports Cloud LLMs (Gemini/OpenAI)
with seamless fallback to Ollama or a deterministic rule-based generator when offline.
"""

import os
import json
import asyncio
import re
from typing import AsyncGenerator, Optional, List, Dict, Any

import httpx
from core.db_models import AgentPromptRequest
from services.nl_sql import translate_nl_to_sql, parse_schema_context
from services.data_cleaner import clean_table_data
from services.migration_architect import generate_migration_plan
from services.output_refiner import OutputRefiner


def classify_user_intent(prompt: str) -> str:
    """
    Classifies user intent into one of three specialized sub-engines:
    - 'cleaner': Data quality, deduplication, whitespace, casing, imputation
    - 'migration': Schema evolution, ALTER TABLE, Alembic, column additions/deletions
    - 'nl_sql': General analytical questions, data exploration, SQL generation
    """
    p_lower = prompt.lower()

    # Migration Intent Keywords
    migration_keywords = [
        "migrate", "migration", "alter table", "add column", "drop column",
        "rename column", "alembic", "modify column", "change type", "add index",
        "create index", "schema evolution", "ddl", "drop index", "foreign key"
    ]
    if any(k in p_lower for k in migration_keywords):
        return "migration"

    # Cleaner Intent Keywords
    cleaner_keywords = [
        "clean", "cleaning", "dedup", "duplicate", "duplicates", "trim",
        "whitespace", "casing", "lowercase", "uppercase", "impute", "imputation",
        "null values", "fix nulls", "standardize", "normalize", "hygiene"
    ]
    if any(k in p_lower for k in cleaner_keywords):
        return "cleaner"

    # Default to NL-to-SQL
    return "nl_sql"


def generate_deterministic_response(payload: AgentPromptRequest) -> str:
    """
    Generates a deterministic, rule-based response using the appropriate
    Squad C specialized engine based on intent classification, refined
    through OutputRefiner.
    """
    intent = classify_user_intent(payload.prompt)

    if intent == "migration":
        raw_output = generate_migration_plan(
            prompt=payload.prompt,
            table_context=payload.table_context,
            dialect="postgresql",
            safety_mode=payload.safety_mode
        )
    elif intent == "cleaner":
        raw_output = clean_table_data(
            prompt=payload.prompt,
            table_context=payload.table_context,
            dialect="duckdb",
            safety_mode=payload.safety_mode
        )
    else:
        raw_output = translate_nl_to_sql(
            prompt=payload.prompt,
            table_context=payload.table_context,
            dialect="duckdb",
            safety_mode=payload.safety_mode
        )

    return OutputRefiner.refine(
        raw_text=raw_output,
        schema=payload.table_context,
        prompt=payload.prompt,
        safety_mode=payload.safety_mode,
    )


async def _stream_openai(payload: AgentPromptRequest, api_key: str) -> AsyncGenerator[str, None]:
    """Streams response from OpenAI API."""
    import openai
    client = openai.AsyncOpenAI(api_key=api_key)

    schema_map = parse_schema_context(payload.table_context)
    schema_summary = json.dumps(schema_map, indent=2) if schema_map else "No explicit schema provided."

    system_prompt = (
        "You are Dimension Studio's Autonomous Data Intelligence Agent.\n"
        f"Database Dialect: DuckDB / PostgreSQL\n"
        f"Safety Mode: {payload.safety_mode}\n"
        f"Active Schema Context:\n{schema_summary}\n\n"
        "Guidelines:\n"
        "1. For query/analytics requests, formulate optimized SQL and wrap executable queries in ```sql:executable ... ```.\n"
        "2. For cleaning/hygiene requests, generate safe non-destructive CTE/View recipes wrapped in ```sql:executable ... ```.\n"
        "3. For schema migrations, output SQL UP DDL (in ```sql:executable``` if safe, else ```sql```), SQL DOWN DDL, and Alembic Python code.\n"
        "4. If safety_mode is 'read_only', never generate mutating statements in executable blocks.\n"
        "5. Keep explanations concise, professional, and well-structured."
    )

    model_name = "gpt-4o-mini"
    if "gpt" in payload.model.lower():
        model_name = payload.model

    response = await client.chat.completions.create(
        model=model_name,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": payload.prompt}
        ],
        temperature=0.1,
        stream=True,
        timeout=20.0
    )

    async for chunk in response:
        delta = chunk.choices[0].delta.content if chunk.choices else None
        if delta:
            yield f"data: {json.dumps({'token': delta})}\n\n"


async def _stream_gemini(payload: AgentPromptRequest, api_key: str) -> AsyncGenerator[str, None]:
    """Streams response from Google Gemini API via REST SSE."""
    model_name = payload.model if "gemini" in payload.model.lower() else "gemini-1.5-flash"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:streamGenerateContent?alt=sse&key={api_key}"

    schema_map = parse_schema_context(payload.table_context)
    schema_summary = json.dumps(schema_map, indent=2) if schema_map else "No explicit schema provided."

    prompt_body = {
        "contents": [{
            "parts": [{
                "text": (
                    f"System: You are Dimension Studio's Autonomous Data Agent. Safety mode: {payload.safety_mode}.\n"
                    f"Schema: {schema_summary}\n"
                    "Wrap executable SQL queries in ```sql:executable ... ```.\n\n"
                    f"User request: {payload.prompt}"
                )
            }]
        }],
        "generationConfig": {
            "temperature": 0.1,
            "maxOutputTokens": 1000
        }
    }

    async with httpx.AsyncClient(timeout=20.0) as client:
        async with client.stream("POST", url, json=prompt_body) as resp:
            if resp.status_code != 200:
                raise RuntimeError(f"Gemini API returned status {resp.status_code}")
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    data_str = line[6:].strip()
                    if not data_str or data_str == "[DONE]":
                        continue
                    try:
                        data_json = json.loads(data_str)
                        candidates = data_json.get("candidates", [])
                        if candidates:
                            parts = candidates[0].get("content", {}).get("parts", [])
                            for p in parts:
                                text_token = p.get("text", "")
                                if text_token:
                                    yield f"data: {json.dumps({'token': text_token})}\n\n"
                    except Exception:
                        continue


async def _stream_ollama(payload: AgentPromptRequest, base_url: str) -> AsyncGenerator[str, None]:
    """Streams response from local Ollama instance."""
    url = f"{base_url.rstrip('/')}/api/generate"
    req_body = {
        "model": payload.model if payload.model and "gpt" not in payload.model and "gemini" not in payload.model else "llama3",
        "prompt": payload.prompt,
        "stream": True,
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        async with client.stream("POST", url, json=req_body) as resp:
            if resp.status_code != 200:
                raise RuntimeError(f"Ollama returned status {resp.status_code}")
            async for line in resp.aiter_lines():
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                    response_token = data.get("response", "")
                    if response_token:
                        yield f"data: {json.dumps({'token': response_token})}\n\n"
                    if data.get("done"):
                        break
                except Exception:
                    continue


async def _stream_deterministic_tokens(text: str) -> AsyncGenerator[str, None]:
    """
    Simulates token-by-token streaming for deterministic generation,
    ensuring exact byte-for-byte fidelity without corrupting code fences or newlines.
    """
    # Tokenize while preserving exact original text without adding/removing spaces
    tokens = re.findall(r"[^\s\r\n]+[^\S\r\n]*|\r?\n+|[^\S\r\n]+", text)
    for i, tok in enumerate(tokens):
        yield f"data: {json.dumps({'token': tok})}\n\n"
        if i % 4 == 0:
            await asyncio.sleep(0.005)


async def _collect_stream_text(generator: AsyncGenerator[str, None]) -> str:
    """Helper to collect streamed text tokens from an LLM SSE generator."""
    tokens = []
    async for sse_chunk in generator:
        if sse_chunk.startswith("data: "):
            payload_str = sse_chunk[6:].strip()
            if payload_str and payload_str != "[DONE]":
                try:
                    data = json.loads(payload_str)
                    if "token" in data:
                        tokens.append(data["token"])
                except Exception:
                    pass
    return "".join(tokens)


async def stream_data_agent_response(payload: AgentPromptRequest) -> AsyncGenerator[str, None]:
    """
    Primary endpoint streaming orchestrator for Autonomous Data Agent.
    
    1. Attempts Cloud LLM streaming (Gemini or OpenAI) if API keys are configured in environment.
    2. Attempts Local LLM streaming (Ollama) if available.
    3. Seamlessly falls back to deterministic rule-based generation if offline or on network error.
    4. Routes all generations through OutputRefiner.refine() for schema grounding, typo correction,
       executive polish, and suggestion chip synthesis.
    5. Concludes stream with SSE termination signals (`{done: True}` and `[DONE]`).
    """
    streamed_successfully = False

    openai_key = os.getenv("OPENAI_API_KEY", "").strip()
    gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
    ollama_url = os.getenv("OLLAMA_BASE_URL", "").strip()

    # Tier 1: Cloud LLM (Gemini)
    if not streamed_successfully and gemini_key and not gemini_key.startswith("your_"):
        try:
            raw_text = await _collect_stream_text(_stream_gemini(payload, gemini_key))
            if raw_text.strip():
                refined_text = OutputRefiner.refine(
                    raw_text=raw_text,
                    schema=payload.table_context,
                    prompt=payload.prompt,
                    safety_mode=payload.safety_mode,
                )
                async for sse_chunk in _stream_deterministic_tokens(refined_text):
                    yield sse_chunk
                streamed_successfully = True
        except Exception:
            streamed_successfully = False

    # Tier 2: Cloud LLM (OpenAI)
    if not streamed_successfully and openai_key and not openai_key.startswith("sk-placeholder") and not openai_key.startswith("your_"):
        try:
            raw_text = await _collect_stream_text(_stream_openai(payload, openai_key))
            if raw_text.strip():
                refined_text = OutputRefiner.refine(
                    raw_text=raw_text,
                    schema=payload.table_context,
                    prompt=payload.prompt,
                    safety_mode=payload.safety_mode,
                )
                async for sse_chunk in _stream_deterministic_tokens(refined_text):
                    yield sse_chunk
                streamed_successfully = True
        except Exception:
            streamed_successfully = False

    # Tier 3: Local LLM (Ollama)
    if not streamed_successfully and ollama_url:
        try:
            raw_text = await _collect_stream_text(_stream_ollama(payload, ollama_url))
            if raw_text.strip():
                refined_text = OutputRefiner.refine(
                    raw_text=raw_text,
                    schema=payload.table_context,
                    prompt=payload.prompt,
                    safety_mode=payload.safety_mode,
                )
                async for sse_chunk in _stream_deterministic_tokens(refined_text):
                    yield sse_chunk
                streamed_successfully = True
        except Exception:
            streamed_successfully = False

    # Tier 4: Deterministic Rule-Based Generator (Offline Fallback)
    if not streamed_successfully:
        refined_text = generate_deterministic_response(payload)
        async for sse_chunk in _stream_deterministic_tokens(refined_text):
            yield sse_chunk

    # Standard SSE completion signals
    yield f"data: {json.dumps({'done': True})}\n\n"
    yield "data: [DONE]\n\n"
