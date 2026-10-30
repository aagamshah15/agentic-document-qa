# Autonomous Data & Schema Studio: planning documents

These documents plan how to turn Dimension, the agentic Document Q&A app in this
repository, into a database workbench with an agent built in. The short pitch:
DBeaver or DataGrip, plus a data engineering agent that maps, profiles, queries,
and changes a database. The agent shows its evidence, and every write needs an
approval gate.

Nothing here is implemented yet. These are design notes, written in the same
style as `docs/document-agent-walkthrough.md`. Each one says what we would build,
why, and what the choice costs us. Where a number appears (a row limit, a time
budget), treat it as a starting default to tune with evaluations, not a measured
fact.

## Reading order

| Doc | Question it answers |
| --- | --- |
| [01-product-vision](01-product-vision.md) | Who is this for, what jobs does it do, and what is deliberately out of scope? |
| [02-architecture](02-architecture.md) | Which components exist, how they talk, and how we reach databases safely. |
| [03-agent-and-tools](03-agent-and-tools.md) | The contract for each agent tool: inputs, outputs, limits, failure modes. |
| [04-safety-and-environments](04-safety-and-environments.md) | Environment tiers, approvals, credentials, audit, prompt injection through data. |
| [05-ux-ui-spec](05-ux-ui-spec.md) | Screens, layout, interactions, and the frontend stack. |
| [06-models-and-limits](06-models-and-limits.md) | Which model does which job, context budgeting, per-run budgets, plan quotas. |
| [07-data-model-and-api](07-data-model-and-api.md) | Internal tables, REST endpoints, and the streaming event protocol. |
| [08-roadmap](08-roadmap.md) | Milestones, each with acceptance criteria and tests. |
| [09-evaluation](09-evaluation.md) | Messy fixture databases, scenarios, and how we measure the agent. |

Open decisions that need the owner's input are collected at the end of this
file.

## Current state of the repository

The table below sorts what exists today by how much of it carries over to the
Studio.

| Area | Today | Reuse for the Studio |
| --- | --- | --- |
| Backend | FastAPI (`main.py`, `api/routes.py`), routes for sessions, documents, and streaming queries | **Keep.** Add routers for connections, catalog, runs, and approvals. |
| Streaming | SSE token stream for `/query/stream` and summaries | **Keep the transport**, replace the payload with typed events (see 07). |
| Sessions | SQLite `sessions` and `messages` tables (`services/session_store.py`) | **Keep the pattern.** Becomes the "app database" with new tables for connections, snapshots, runs, and the audit log. |
| Agent loop | Bounded LangGraph loop in `services/document_graph.py`, `document_agent_runtime.py` | **Core asset.** Call budgets, sanitized tool errors, strict argument schemas, and explicit stop reasons are exactly what a database agent needs. Generalize it from one tool to a tool registry. |
| Tool wrappers | `services/document_tools.py`: `extra="forbid"`, explicit validation, `ToolException` with sanitized messages | **Copy the pattern** for every Studio tool. |
| Tests | Scripted-model graph tests (`tests_agent/`), real-model evals (`experiments/evaluate_document_agent.py`) | **Keep both layers.** 09-evaluation extends the eval harness to fixture databases. |
| Router | Keyword list plus vector similarity (`services/router.py`) | **Replace.** Tool choice comes from the agent; intent routing for the UI comes from explicit modes (see 05). |
| Retrieval | ChromaDB plus MiniLM embeddings | **Reuse for schema retrieval.** Embed table and column descriptions so large schemas fit the context window (06). |
| LLM access | Ollama local models; qwen3:4b default for tool use; `langchain-openai` and `OPENAI_API_KEY` present | **Keep local-first.** Add task-based routing and optional bring-your-own-key cloud models (06). |
| Frontend | Vanilla JS (`frontend/app.js`, ~1,400 lines), design tokens in `styles.css`, light/dark themes, sidebar, model and effort selectors, citation cards | **Keep the tokens and visual language**; recommend migrating to React + TypeScript (05). Citation cards become evidence cards. |
| Web search | DuckDuckGo route | **Drop from the Studio surface.** It does not help with a private database, and it is another channel for untrusted text. |
| Config | `core/` settings, `.env` | **Keep**, but flip `LANGCHAIN_TRACING_V2` to off by default (see below). |

### Things to fix before any database data flows through the app

1. **Tracing defaults to on.** `core/` sets `LANGCHAIN_TRACING_V2 = "true"`. With a
   LangSmith key in the environment, prompts and tool results would be sent to
   an external service. That is acceptable for PDF experiments; it is not
   acceptable when tool results contain customer rows. Default it to off, and
   show a visible indicator when it is on. The experiment CLIs already force it
   off; the web app does not.
2. **No authentication.** The app assumes a single local user. That is fine for
   a local-first desktop tool, but it rules out a hosted deployment until auth
   exists (see the open decisions).
3. **Two Python environments.** The original `venv/` (Python 3.9, LangChain 0.3)
   and `.venv-agent/` (Python 3.12) exist side by side. The Studio should run in
   one environment. Settle on 3.12 and the agent dependency set, then port
   whatever the old app still needs.

### What the Studio adds that does not exist at all

- A connector layer for real databases (SQLAlchemy, drivers, DuckDB for files).
- A SQL parser and safety analyzer (sqlglot).
- A metadata catalog with versioned schema snapshots.
- A disposable "shadow" database for testing migrations.
- An approval workflow and an append-only audit log.
- A UI built around tables, graphs, and diffs rather than a chat transcript.

## Guiding principles

These recur across every document:

1. **Evidence over assertion.** Every claim the agent makes ("`cust_id` is
   probably a foreign key to `customers.id`") links to the query, sample, or
   statistic that supports it. This is the database version of the citation
   cards the app already has.
2. **Reads are cheap, writes are ceremonies.** Reading metadata is automatic.
   Reading data is bounded. Writing anything goes through a proposal, a dry run,
   and a human approval, and the strictness depends on the environment tier.
3. **The application enforces limits, not the prompt.** A system prompt saying
   "never run DELETE" is a hint. The parser, the read-only connection, and the
   statement timeout are the actual controls. The existing document tools
   already work this way: the model cannot name a directory, because the schema
   has no directory argument.
4. **Local-first by default.** Database contents are sensitive. The default path
   keeps the model, the catalog, and query results on the user's machine.
   Cloud models are opt-in, per connection.
5. **Tests that need no model, evals that need a real one.** Keep the separation
   from the document agent: deterministic tests for orchestration and safety,
   live-model evaluations for judgment.

## Open decisions for the owner

These change the plan materially. Each doc notes where it depends on them.

| # | Decision | Options | Recommendation |
| --- | --- | --- | --- |
| D1 | Deployment model | (a) Local-first desktop/server app; (b) hosted multi-tenant SaaS; (c) local-first now, team server later | **(c).** Local-first matches the existing Ollama stack and avoids holding customers' credentials. Design the data model with `workspace_id` from day one, so a team server does not need a rewrite. |
| D2 | Frontend migration | (a) Keep vanilla JS; (b) React + Vite + TypeScript, keeping the design tokens; (c) another framework | **(b).** An ERD canvas, a data grid, a SQL editor, and diff views are all mature React components. Writing them by hand in vanilla JS would take most of the effort. See 05. |
| D3 | Cloud model use | (a) Local only; (b) BYOK cloud as an opt-in per connection; (c) cloud by default | **(b).** Small local models are adequate for routing, summarizing, and simple SQL. Complex migrations and large schemas benefit from stronger models. The user should choose this per connection, and the UI should show which data left the machine. See 06. |
| D4 | First supported engines | Postgres, MySQL, SQLite, SQL Server, Snowflake, BigQuery... | **Postgres + SQLite + DuckDB files first.** Postgres covers most "messy production database" cases. SQLite and DuckDB make fixtures and demos trivial. Add MySQL next. |
| D5 | Writes to production at all? | (a) Never, export scripts only; (b) with two-person approval | **(a) for v1.** Production gets read-only access plus exported, reviewed migration scripts. Revisit once the audit and approval features have proven themselves on staging. |
| D6 | Name | "Dimension Studio", a new name... | Product decision; it does not block engineering. |
