# Agentic Document Q&A System

An autonomous, private Document Q&A and Knowledge Assistant built with FastAPI, LangChain, ChromaDB, and a high-density Technical Document Intelligence Console (grounded in Refero Design craft standards).

## Features
- **100% Local & Private:** Uses local HuggingFace embeddings (`all-MiniLM-L6-v2`) and local LLMs (like `llama3`) via Ollama. No private data is sent to external cloud APIs for document processing.
- **Multi-Format Document Ingestion:** Supports `.pdf`, `.docx`, `.txt`, and `.md` files with automated chunking and vector indexing.
- **Autonomous Query Routing & Live Web Search Fallback:** Automatically evaluates query relevance. If an answer cannot be found in your local documents (or if external web information is requested), the agent autonomously falls back to live web search via DuckDuckGo and explicitly labels the source as live web search.
- **Real-Time Token Streaming:** Server-Sent Events (SSE) stream responses token-by-token directly into the UI with a typewriter effect.
- **Multi-Chat Support & Persistent Memory:** Manage multiple independent conversation threads in the sidebar with automatic topic titling, thread switching, deletion, and persistent SQLite database storage (`data/chat_history.db`) that survives server restarts.
- **Dynamic Model & Effort Selection:** Dynamically interrogates local Ollama (`/api/models`) to let users select installed models (`llama3:latest`, `llama3.1:8b`, `qwen3:4b`, etc.) and calibrate reasoning effort (`Low`, `Medium`, `High`) with temperature and prompt adjustments.
- **Real-Time Stream Interruption (Stop Button):** Instant client-side stream cancellation (`AbortController`) via a dedicated Stop button (`■`) or the `Escape` key, gracefully persisting partial responses into conversation memory.
- **Interactive Source Citations:** Expandable citation cards under every response showing exact matching document names, 1-indexed page numbers, or clickable web URLs.
- **1-Click Executive Document Summarizer:** Generate a structured executive summary (Overview, Key Points, Details/Metrics, Conclusions) for any document directly from the sidebar.
- **Document Management:** Live sidebar file tracker with vector chunk counts, file size badges, and individual or full deletion controls.

## Architecture
- **Backend:** FastAPI, LangChain, SQLite (`data/chat_history.db`), Pydantic
- **Vector Store:** ChromaDB
- **Embeddings:** HuggingFace `sentence-transformers` (`all-MiniLM-L6-v2`)
- **LLM:** Ollama (default: `llama3`)
- **Web Search Fallback:** `ddgs` (DuckDuckGo Search)
- **Frontend:** Vanilla JS, HTML5, CSS3 (Obsidian & Carbon Technical Console, JetBrains Mono & Inter typography, Lucide SVG micro-icons, SSE streaming)

## Prerequisites
1. **Python 3.9+** installed on your machine.
2. **Ollama** installed on your machine (download from [ollama.com](https://ollama.com/)).

## Quick Start

### 1. Run Local LLM
Pull and run the LLaMA 3 model using Ollama:
```bash
ollama run llama3
```
*(Leave Ollama running in the background).*

### 2. Set Up Python Environment
Clone this repository and set up your virtual environment:

```bash
git clone https://github.com/aagamshah15/agentic-document-qa.git
cd agentic-document-qa

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Run the Server
Start the FastAPI server:

```bash
uvicorn main:app --reload --port 8001
```

### 4. Open the Application
Navigate to **http://127.0.0.1:8001/** in your browser. 

## Project Structure
- `api/`: FastAPI routes (`/upload`, `/query`, `/query/stream`, `/documents`, `/chat/clear`).
- `core/`: Environment and configuration management.
- `frontend/`: Technical Console UI (HTML, CSS tokens, JS with SSE reader, SVG icon system).
- `services/`: 
  - `agent.py`: Conversational RAG chain & session memory.
  - `document_processor.py`: Multi-format loader (.pdf, .docx, .txt, .md).
  - `vector_store.py`: ChromaDB integration & collection management.
  - `summarizer.py`: 1-click executive document summarizer.
  - `router.py`: Autonomous query router (Local RAG vs. Web Search).
  - `web_search.py`: Live web search fallback engine.
- `data/`: Local uploads and ChromaDB persistent storage (gitignored).
- `tests/`: Integration test suites (`test_step1.py`, `test_step2.py`, `test_step3.py`, `test_step4.py`).

## Running Tests
Run all test suites using unittest:

```bash
python -m unittest discover tests
```

## Tests

Run the catalog and search unit tests from the project root:

```bash
python3 -m unittest discover -s tests -v
```

The suite uses Python's built-in `unittest` and temporary directories. It does
not require application dependencies, Ollama, embeddings, or a database, and
does not read or modify your uploaded documents.

Tests cover inventory metadata, filename filtering and ordering, symlinks,
special files, missing directories, permission and I/O errors, files changing
during enumeration, JSON serialization, and read-only behavior. Filesystem
faults and races are simulated where necessary to keep tests reproducible.

The catalog lists saved files with a `.pdf` extension; it does not validate PDF
contents or establish indexing readiness. `indexing_status` remains `unknown`.
Listing is not an atomic snapshot: a file can change after its metadata is read.

## Document agent experiment

The first agent is available as a separate command-line experiment. It can
choose a document-listing tool, inspect the result, and answer the user. The
existing web application still uses its original RAG chain.

Use Python 3.12 and a separate environment for this experiment:

```bash
python3.12 -m venv .venv-agent
.venv-agent/bin/python -m pip install -r requirements-agent.txt
ollama pull qwen3:4b
```

With Ollama running, observe the manual model/tool exchange, then the same
interaction orchestrated by LangGraph:

```bash
.venv-agent/bin/python -m experiments.document_agent --mode manual "Which documents have I uploaded?"
.venv-agent/bin/python -m experiments.document_agent --mode graph "Which documents have I uploaded?"
.venv-agent/bin/python -m experiments.document_agent --mode graph "Hello!"
```

Both modes print tool requests, tool results, and the final answer. Model
thinking is kept separate from the printed answer. The default is `qwen3:4b`;
use `--model` to evaluate a different installed model. Downloads need internet
access; model inference uses the local Ollama endpoint. These experiment CLIs
disable external tracing.

```bash
# Catalog, search, and agent unit tests; no running model needed.
.venv-agent/bin/python -m unittest discover -v

# Six real-model evaluations using synthetic temporary files, not user uploads.
.venv-agent/bin/python -m experiments.evaluate_document_agent --mode graph
```

The evaluation writes transcripts and results to `data/agent_evaluation.json`.
Its answer checks are heuristics, so review the transcripts as well as the pass
count. The graph limits model/tool calls and reports malformed or truncated
responses. It does not yet persist chat history or read PDF contents.

Read [the design walkthrough](docs/document-agent-walkthrough.md) for the code
reading order, environment tradeoffs, execution flow, and testing strategy.

## Document search function

`services/document_search.py` adds `search_documents(query, filename=None,
limit=4)` (filename and limit are keyword-only). It searches the existing Chroma
index and returns excerpts, filenames, one-based PDF page numbers, and distances.
It is not yet connected to the listing agent. Use the original `venv/` for live
retrieval because it contains the embedding and Chroma dependencies.

```bash
venv/bin/python -m unittest integration_tests.chroma_search -v
```

These integration tests use temporary databases and synthetic embeddings. See
[the search design notes](docs/document-search-design.md) for the function's
contract, examples, tradeoffs, and the distinction between retrieval correctness
and semantic-search quality.
