# Searching indexed document contents

This step adds `search_documents` in `services/document_search.py`, plus unit
and Chroma integration tests. It is not yet registered as an agent tool. The
existing listing agent and web Q&A chain keep their current behavior.

## The function's contract

```python
search_documents(
    query="What are the eligibility requirements?",
    filename="scholarships.pdf",  # Optional: exact uploaded filename.
    limit=4,                     # Optional: 1 to 8 passages.
)
```

This returns a list of passages, not a generated answer. For example, a
synthetic test document produces:

```json
[
  {
    "filename": "scholarships.pdf",
    "page": 1,
    "excerpt": "Scholarship eligibility requires enrollment.",
    "truncated": false,
    "distance": 0.0
  }
]
```

`page` is the physical PDF page, counting from one. It may differ from the
printed page label, such as a Roman numeral in a preface. Missing or invalid
source/page metadata remains null instead of producing an invented citation.

`distance` is the Chroma distance, with lower values meaning closer vectors.
It is not a confidence percentage and does not establish that a passage answers
the question. The value of zero above comes from controlled synthetic vectors
used in the tests, not a measured real-world search-quality score.

## Decisions and tradeoffs

| Decision | Reason | Tradeoff |
| --- | --- | --- |
| Reuse Chroma and `all-MiniLM-L6-v2` | Query embeddings must match the existing index. | We inherit the current chunking and retrieval limitations. |
| Return evidence, not an LLM answer | Retrieval can be inspected and tested independently of generation. | The caller must assess whether the excerpts actually support an answer. |
| Apply filename scope inside the database query | Ranking is performed among eligible chunks. | Exact source-path matching depends on the current ingestion convention. |
| Bound query length, result count, and excerpt length | Keep work and eventual tool output manageable. | A long passage may be clipped; its `truncated` field makes that visible. |
| Keep the backend injectable | Most tests need no model or database; callers can reuse an opened store. | Application code must manage backend lifetime when performance matters. |
| Avoid a hardcoded relevance threshold | Distances are not calibrated probabilities. | Unrelated nearest neighbors may still be returned. |

The core flow is:

```text
Validate arguments
    → open the existing index (or use an injected backend)
    → apply optional source filter and request nearest chunks
    → format bounded excerpts with source/page metadata
```

The default result limit is four, matching the existing retriever. Queries are
limited to 2,000 characters after trimming surrounding whitespace. Each excerpt
is limited to 1,200 characters. These are initial application limits, not model
context guarantees; agent integration will still need to budget accumulated
messages and repeated searches.

Blank chunks are skipped and may result in fewer passages than requested.
Repeated indexed chunks are not deduplicated in this first version, so multiple
results may refer to the same page. The count is a count of passages, not files.

## Why filtering must happen before ranking

Suppose the closest passage globally is in `scholarships.pdf`, but the user
asks to search `campus.pdf` and requests one result. Searching globally for one
result and then discarding other filenames would incorrectly return nothing.
The function passes the filename filter into Chroma so it selects the closest
passage within `campus.pdf`. A real database integration test checks this case.

The current upload route stores the absolute PDF path in each chunk's `source`
metadata. The function constructs that exact path from a validated filename and
the application's upload directory. It does not open a user-supplied path.
Spelling and case are preserved, with no fuzzy filename matching.

If the project is moved, or chunks were indexed with a different source-path
convention, filename-scoped searches may return no matches. A document registry
with stable IDs would remove this coupling; that is a future ingestion change,
not something this search function can safely infer or repair.

## Empty results and failures

- An empty existing collection or an unmatched filename returns `[]`.
- A missing index raises `FileNotFoundError`.
- A database missing the expected collection raises Chroma's error.
- Invalid arguments are rejected before opening the default store.
- Backend errors propagate; they are not converted into an empty result.

The store factory now accepts `create_if_missing=False`. Search uses this mode
to avoid silently creating an empty index. Its default remains `True`, preserving
the existing upload path. Opening an index may involve database housekeeping;
the search function itself does not add, delete, or reindex chunks.

An empty search result does not prove that an answer is absent from every PDF.
Saved files may not have been indexed, and indexed text can outlive a removed
file. This function searches the index as it stands.

## Environments and testing

The original `venv/` contains the Chroma and embedding packages. Use it for
searches against the existing index. No new packages were installed for this
step. The agent environment does not yet include retrieval dependencies.

For repeated searches, reuse a backend to avoid repeatedly initializing the
embedding model:

```python
from services.document_search import search_documents
from services.vector_store import get_vector_store

store = get_vector_store(create_if_missing=False)
matches = search_documents("eligibility requirements", backend=store)
```

Run the dependency-free catalog/search unit tests:

```bash
venv/bin/python -m unittest discover -s tests -v
```

Run the explicit Chroma integration suite with temporary collections:

```bash
venv/bin/python -m unittest integration_tests.chroma_search -v
```

Run all catalog, search, and existing agent unit tests in the agent environment:

```bash
.venv-agent/bin/python -m unittest discover -v
```

There are 28 new search unit tests and nine new Chroma integration tests. The
integration tests use fixed synthetic embedding vectors: they verify ranking,
metadata filters, persistence, and failure behavior without downloading a model
or touching user uploads. They do not measure the quality of real semantic
embeddings. That needs a separate evaluation set of questions and expected
supporting passages when this function is connected to the agent.
