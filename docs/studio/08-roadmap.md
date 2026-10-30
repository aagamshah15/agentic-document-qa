# Roadmap

Each milestone ends with something a person can use, and with tests that keep
it working. The order follows risk: read-only features first, then writes on
throwaway databases, then writes on shared ones. The durations are rough
estimates for one experienced developer, useful for sequencing, not as
commitments.

## M0: Foundations (≈1–2 weeks)

Make the repository ready for database work without changing what users see.

Scope:
- Single Python 3.12 environment; port what the old app needs from `venv/`.
- `LANGCHAIN_TRACING_V2` defaults to off; status indicator when it is on.
- Fix the unescaped `innerHTML` insertions in `frontend/app.js` (filenames,
  source snippets).
- App-DB migration runner (versioned SQL files) replacing `CREATE TABLE IF NOT EXISTS`.
- Generalize the graph: a tool registry with `ToolSpec` (03), per-resource
  budgets, typed run events written to `run_events`.
- Fixture databases v0: `shop_clean` and `shop_messy` (09) as SQLite files and
  Postgres init scripts.

Acceptance criteria:
- All existing tests pass in the single environment.
- The existing document agent runs on the generalized graph with unchanged behavior
  (its scripted-model tests pass unmodified).
- A test proves tracing is off by default.

## M1: Connect and map (≈3 weeks)

The first user-facing Studio feature: connect read-only and see the map.

Scope:
- Connector layer: Postgres, SQLite, DuckDB files. Read-only sessions,
  timeouts, application name, small pool.
- Connection form with tier, keychain storage, privilege grading.
- Catalog: structure + engine statistics; schema snapshots; snapshot diff.
- React app at `/studio` with the existing design tokens: sidebar, top bar,
  Tables view, ERD (React Flow + ELK) with declared FKs only.
- Agent in Explore mode with `search_schema`, `describe_tables`,
  `get_relationships`. Schema retrieval with Chroma.

Acceptance criteria:
- Connecting to `shop_messy` (Postgres) renders a map in under 60 s.
- A 1,000-table synthetic schema renders the grouped overview without freezing
  the browser (interaction under 100 ms per frame on a mid-range laptop).
- "What tables hold customer data?" returns the right tables on the fixture with
  evidence, using a local model.
- Credentials never appear in the app DB, logs, or model messages (tests).

## M2: Profile and infer (≈3 weeks)

Scope:
- `profile_table` (pushdown aggregates + DuckDB sampling), PII detection and
  masking.
- `infer_foreign_keys` with evidence; confirm/reject UI on dashed edges.
- `find_hygiene_issues`; Findings inbox with dismiss memory.
- Glossary v1: suggestions from the agent, confirmation UI, use in retrieval.
- Data dictionary export (Markdown, dbt `sources.yml`).

Acceptance criteria:
- On `shop_messy`, FK inference finds ≥ 90% of the planted undeclared FKs with
  ≤ 2 false positives in the top 20, including the lookup-table trap (09).
- Hygiene finds ≥ 80% of the planted issues; dismissed findings do not reappear.
- No planted PII value appears in any model message (full-history scan).
- Profiling a 10M-row table stays within its time budget and labels results
  as sampled.

## M3: Ask (NL→SQL) (≈3 weeks)

Scope:
- SQL guard (sqlglot): parse, classify, allow-list, LIMIT rewrite, name checks.
- `draft_sql` with EXPLAIN and the cost guard; `run_query` with tokens.
- Query workbench: Monaco with catalog completion, results grid, plan
  visualizer.
- Ask mode in the agent panel with evidence cards and SQL suggestions.
- Markdown rendering for answers (sanitized).
- Glossary rules (enum maps, filter rules) used in SQL generation.

Acceptance criteria:
- Execution accuracy ≥ 70% on the `shop_messy` question set with the default
  local model, and recorded for each candidate model (09).
- The guard rejects 100% of the write/side-effect corpus (04) in tests.
- A query estimated above the tier threshold is never executed without a user
  confirmation (test with a planted large table and mocked plan).
- Cancel stops the backend query (`pg_stat_activity` check).

## M4: Change on throwaway databases (≈4 weeks)

Scope:
- Shadow manager (SQLite copy, DuckDB, Docker Postgres with version check).
- `propose_migration` with shadow verification, the lock-risk linter, and
  `analyze_impact`.
- Changes screen with diff, verification, lint, impact, and typed confirmation.
- LangGraph checkpointing for approval pauses; resumable SSE.
- Apply on Sandbox and Dev; export to Alembic/Flyway/SQL for every tier.
- Audit log with hash chain; Activity view.

Acceptance criteria:
- For the migration scenario set (09), ≥ 80% of proposals pass shadow
  verification without manual editing, and 100% of the planted risky patterns
  are flagged by the linter.
- No write reaches a Dev connection without an approval record (tests that try
  every path: agent, API, editor).
- A run waiting for approval survives a server restart and resumes.
- Prod connections offer only export, never apply.

## M5: Seed (≈2 weeks)

Scope:
- `plan_seed` with topological ordering and cycle handling; editable plan.
- `generate_seed` to file and shadow, and to Sandbox/Dev with approval.
- Fidelity report.

Acceptance criteria:
- Seeds for `shop_messy` load into a shadow with zero constraint violations,
  including the self-referencing `employees.manager_id` and a two-table cycle.
- No real value from a PII column appears in generated output (test).
- Per-column distribution distance against the profile is reported, and stays
  below a set threshold for categorical columns.
- Same seed number → byte-identical output.

## M6: Hardening and polish (≈2–3 weeks)

Scope:
- MySQL connector; drift report between two connections.
- BYOK cloud models with per-connection opt-in and the disclosure screen.
- Model role routing (Fast/Tool/Reasoning) and capability probes.
- Prompt-injection fixture suite in CI.
- Accessibility pass; keyboard triage in the Findings inbox.
- Performance pass on large schemas.

Acceptance criteria:
- The full evaluation suite (09) runs in CI against the scripted model, and
  nightly against the default local model, with results tracked per prompt
  version.
- Zero injection-suite failures that result in a write proposal.

## Release checklist: documentation

The planning documents in `docs/studio/` are internal. Before any public
release:

- [ ] The planning docs live only in a private location (a private repository,
      or this repository made private). Deleting them in a later commit is not
      enough: anything ever pushed to a public repository stays in its git
      history and in any existing clones or forks.
- [ ] Public user documentation exists in `docs/user/`: installing, connecting
      a database, choosing a tier, the Map, asking questions, reviewing
      findings, approving or exporting migrations, generating seed data, and
      privacy (what stays local and what a cloud model receives).
- [ ] The README points users to `docs/user/` and does not link to
      `docs/studio/`.
- [ ] Nothing in the shipped app or package includes `docs/studio/`.

## Later (not scheduled)

- Team server: auth, shared glossary with reviewer roles, two-person approval,
  external audit sinks (D1).
- Prod apply with two-person approval (D5).
- Snowflake, BigQuery, and SQL Server, each with its own cost model.
- dbt project awareness: parse `manifest.json` for impact analysis and model
  generation.
- Query history mining from `pg_stat_statements` to suggest indexes and detect
  unused tables.
- Scheduled drift and hygiene checks with notifications.

## Testing strategy per milestone

The existing split stays:

| Layer | Runs | Needs |
| --- | --- | --- |
| Unit | Every commit | Nothing external. Guard corpus, masking, linter rules, topological sort, scoring. |
| Graph/orchestration | Every commit | Scripted model (as `tests_agent/` does today), SQLite fixtures. |
| Integration | Every commit in CI | Postgres in a container; fixtures loaded fresh per test module. |
| Live model eval | Nightly + on prompt changes | Ollama with the configured models; reports saved for review (09). |
| UI end-to-end | Every PR touching the frontend | Playwright against a stubbed API and against the fixture stack. |

A milestone is done when its acceptance tests run in CI, not when the demo
works once.
