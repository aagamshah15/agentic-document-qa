# Local Document Q&A System

A completely local, free, and private Document Q&A system built with FastAPI, LangChain, and a stunning Glassmorphism UI.

## Features
- **100% Local & Private:** Uses local HuggingFace embeddings (`all-MiniLM-L6-v2`) and local LLMs (like `llama3`) via Ollama. No data is ever sent to OpenAI or third-party servers.
- **Retrieval-Augmented Generation (RAG):** Intelligently chunks your PDFs, stores them in a local ChromaDB vector database, and uses them as context to answer your questions.
- **Premium Glassmorphism UI:** A beautiful, responsive frontend with a drag-and-drop PDF upload zone and an animated chat interface.
- **FastAPI Backend:** A lightweight and lightning-fast Python API serving both the RAG pipeline and the frontend application.

## Architecture
- **Backend:** FastAPI, LangChain, Pydantic
- **Vector Store:** ChromaDB
- **Embeddings:** HuggingFace `sentence-transformers`
- **LLM:** Ollama (default: `llama3`)
- **Frontend:** Vanilla JS, HTML, CSS (Dark Mode Glassmorphism)

## Prerequisites
1. **Python 3.9+** installed on your machine.
2. **Ollama** installed on your machine (download from [ollama.com](https://ollama.com/)).

## Quick Start

### 1. Download Local LLM
First, pull the LLaMA 3 model using Ollama. Open your terminal and run:
```bash
ollama run llama3
```
*(Leave Ollama running in the background).*

### 2. Set Up Python Environment
Clone this repository and set up a virtual environment:

```bash
git clone https://github.com/aagamshah15/agentic-document-qa.git
cd agentic-document-qa

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Run the Server
Start the FastAPI server (which automatically serves the frontend):

```bash
uvicorn main:app --reload --port 8001
```

### 4. Explore
Navigate to **http://127.0.0.1:8001/** in your browser. 
Upload a PDF using the left sidebar, and then use the chat interface to ask questions about your document!

## Project Structure
- `api/`: FastAPI models and API endpoints (`/upload`, `/query`).
- `core/`: Environment and configuration management.
- `frontend/`: HTML, CSS, and JS for the UI.
- `services/`: LangChain logic (PDF parsing, RAG chain, ChromaDB integration).
- `data/`: Local storage for uploaded PDFs and the ChromaDB vector store (gitignored).
