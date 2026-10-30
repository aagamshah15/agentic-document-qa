# UX and UI specification

## What the current app teaches us

I reviewed the running frontend (light theme, dark theme, and a 390 px mobile
viewport) with the API stubbed, because Ollama and Chroma were not available
in the review environment. What to keep and what to change:

**Keep**

- The visual language: the frosted-glass cards, hairline borders, azure accent in
  light mode, near-black graphite in dark mode, DM Sans for text, JetBrains
  Mono for metadata. The design tokens in `styles.css` (`--graphite`,
  `--hairline-border`, `--accent-tint`, `--glass-card`, ...) are well-named and
  already themeable. Port them as CSS variables into the new frontend unchanged.
- The **bottom dock** with model and effort selectors. It is a good home for the
  connection and tier selector too.
- **Citation cards** ("Document Sources (1)"), collapsible under each answer.
  These become **evidence cards**.
- The sidebar's split between threads and a resource list (documents become
  connections).
- Keyboard shortcuts (⌘B sidebar, ⌘K new thread, focus mode).

**Change**

- **Markdown is not rendered.** Answers show raw `**bold**` and code fences.
  A database assistant answers with SQL, so it needs real code blocks with
  syntax highlighting and a "Run" / "Open in editor" action.
- **Unescaped values in `innerHTML`.** Filenames and source snippets are
  inserted unescaped (see 04). With database content, this becomes a real
  XSS risk.
- **Mobile.** At 390 px, the sidebar overlays the conversation and the dock
  slides under it. The Studio is a desktop tool first. Below 900 px, show
  read-only views (findings, glossary, answers) and say that editing and
  approvals need a wider screen, rather than squeezing in an ERD.
- **Hardcoded status.** The footer says "Port 8001 · ChromaDB" regardless of
  reality. Replace it with live status: connection health, model provider
  (local/cloud), and tracing on/off.
- **A chat transcript is the wrong main surface.** Most Studio outputs are
  tables, graphs, plans, and diffs. Chat becomes a side panel that drives them.

## Frontend stack recommendation (decision D2)

| Need | Library | Why |
| --- | --- | --- |
| App framework | React 18 + TypeScript + Vite | The components below exist for React and are mature; types matter with typed SSE events. |
| SQL editor | Monaco (`@monaco-editor/react`) | Same editor as VS Code; custom completion from the catalog; diff editor built in. CodeMirror 6 is a lighter alternative. |
| Data grid | TanStack Table + TanStack Virtual | Headless, so it can use the existing tokens; virtualized for 10k rows. |
| ERD canvas | React Flow (`@xyflow/react`) + ELK (`elkjs`) for layout | React Flow handles pan, zoom, selection, and custom nodes; ELK produces readable layered layouts for graphs with hundreds of nodes. |
| Plan visualizer | Custom tree on React Flow, or a simple nested flame view | Postgres JSON plans are trees; no maintained React component fits the visual style. |
| Charts (profile histograms) | A small chart library (e.g. Recharts or visx) | Histograms, bar charts of top-k values, sparkline null rates. |
| Server state | TanStack Query | Caching and invalidation for catalog and profile data. |
| Markdown | `react-markdown` with raw HTML disabled | Safe rendering of model output. |

Tradeoff: this replaces ~1,400 lines of working vanilla JS and adds a build
step. The alternative, extending the vanilla app, means hand-writing a
virtualized grid, an ERD canvas with layout, and a diff editor. That would be
the bulk of the project, with worse results. The migration can be gradual:
serve the new app at `/studio` while the current app stays at `/`.

## Information architecture

```text
┌───────────────────────────────────────────────────────────────────────────────┐
│ Top bar: ◧  Dimension Studio   [● prod-orders ▾  PROD]   ⌘K search   ☀/🌙  ⚙   │
├──────────────┬──────────────────────────────────────────────┬─────────────────┤
│ Sidebar      │ Main canvas (tabs)                            │ Agent panel     │
│              │                                               │                 │
│ CONNECTIONS  │  [Map] [Tables] [Query] [Findings] [Changes]  │ Mode: Ask ▾     │
│ ● prod-orders│  [Glossary] [Seeds] [Activity]                │                 │
│ ● staging    │                                               │ Plan checklist  │
│ ● local.duck │  ...content of the active tab...              │ Tool steps      │
│              │                                               │ Answer +        │
│ THREADS      │                                               │ evidence cards  │
│ ...          │                                               │                 │
│              │                                               │ [Ask anything…] │
│ status: model│                                               │ model · effort  │
│ local · trace│                                               │ budget meter    │
│ off          │                                               │                 │
└──────────────┴──────────────────────────────────────────────┴─────────────────┘
```

- **Tier banner.** For a Prod connection, a red strip runs under the top bar on
  every tab. It cannot be dismissed.
- **Agent panel** is resizable and collapsible (⌘J). It drives the canvas: when
  the agent describes `orders`, the Map tab can focus on it; when it drafts SQL,
  the Query tab opens with that SQL. The panel always shows what the agent is
  doing (tool steps) and how much budget remains.
- **⌘K command palette**: jump to a table, column, glossary term, finding, or
  saved query; run actions ("Profile orders", "New migration").

## Screens

### 1. Connect

A form with engine, host/port/database or file path, credential method,
SSH/TLS, and **tier** (with the heuristic suggestion from 04). After
"Test connection", show:

- The privilege grade (A/B/C) with an explanation, plus a copyable SQL
  script that creates a read-only role.
- Server version, extensions found (`pg_stat_statements`, `pg_trgm`), and the
  size estimate.
- Whether shadow verification is available (Docker found, version match).

Then "Map this database" starts the first metadata run.

### 2. Map (ERD canvas)

- Nodes are tables: name, row-count badge, PII badge, findings badge, and the
  key columns. Expand a node to see all columns.
- Edges by kind: **solid** = declared FK; **dashed** = inferred, labeled with a
  score; **solid with a check** = confirmed by a person. Clicking a dashed edge
  opens its evidence (containment %, orphan count, name score, the query) with
  Confirm and Reject buttons.
- Large schemas: never render 1,000 nodes at once. The default view groups
  tables by schema and by detected clusters (connected components of the FK
  graph), shown as collapsed group nodes. Search and focus ("orders + 2 hops")
  are the main navigation tools.
- Layout: ELK layered left-to-right for focus views, and grouped for the
  overview. Manual node positions are saved per user per connection.
- Overlays (toggle): data-quality heat (null rates, findings), PII, size, and
  "changed since last snapshot".
- Export: PNG/SVG, Mermaid, and DBML.

### 3. Tables (catalog browser)

A two-pane view: a table list (filterable by schema, size, findings, and
glossary status), and the table detail:

- **Columns** grid: name, type, nullable, key, PII class, null %, distinct %,
  top values (masked), pattern, and the glossary description. Each statistic is
  labeled "exact" or "sampled 1%", and as stale if computed against an older
  snapshot.
- **Profile** tab: a histogram or top-k bar chart per column. Click a bar to
  open a Query tab filtered to that value.
- **Relationships**, **Indexes**, **Dependents** (from `analyze_impact`),
  **DDL**, and **Sample** (masked, 5 rows, with "show more" in Query).

### 4. Query (SQL workbench)

- Monaco editor with catalog-aware completion and hover docs from the glossary.
- Above the editor: the active connection and tier, a "read-only" lock icon,
  and the cost guard's last verdict.
- **Run** executes through the same guard as the agent. **Explain** renders
  the plan:
  - A tree of plan nodes, with width proportional to estimated cost and colour
    for scan type (sequential scan on a big table = warning colour).
  - Estimated vs. actual rows when `EXPLAIN ANALYZE` was used. ANALYZE executes
    the query, so it is only available on Sandbox/Dev, and it requires a click.
  - Plain-language callouts ("Sequential scan on `events` (≈180M rows). An
    index on `events(user_id)` would let this filter use an index scan.").
- Results: a virtualized grid, paging, column statistics in the header, copy as
  CSV/Markdown/INSERT, and "chart this" for simple bar/line charts.
- When the agent writes SQL, it appears here as a **suggestion** in a
  diff-style overlay, which the user accepts into the editor.

### 5. Findings inbox

A triage queue for hygiene issues, inferred FKs awaiting confirmation, and
glossary suggestions. Each row: severity, the object, a one-line summary, and
its evidence. Actions: **Accept** (creates a glossary entry or a migration
draft), **Dismiss with reason** (remembered), **Snooze**. Filters by kind,
table, and severity. Keyboard-driven (J/K to move, A/D to act), because
triaging 200 findings with a mouse is tiring.

### 6. Changes (migration review)

The approval screen. It is the most important screen in the product, and it
must be impossible to approve something without seeing what it does.

```text
┌ Migration #14: Add index for orders.cust and declare the FK ──────── DEV ┐
│ Goal (from the request): "Speed up order lookups by customer"            │
│                                                                          │
│ [Up SQL] [Down SQL]   side-by-side Monaco diff of schema before/after    │
│                                                                          │
│ Shadow verification ✓ applied in 0.8 s ✓ rolled back ✓ invariants (6/6) │
│   shadow: postgres 16.4 (matches target), sample 1% of rows              │
│                                                                          │
│ Lock risk  ⚠ ADD CONSTRAINT FOREIGN KEY locks orders (≈42M rows)         │
│            → suggestion applied: NOT VALID + separate VALIDATE           │
│                                                                          │
│ Impact     certain: 2 views (order_summary, cust_ltv)                    │
│            likely: 3 saved queries   unknown: application code           │
│                                                                          │
│ Evidence   [ev_3 inferred FK 99.2% containment] [ev_7 EXPLAIN before]    │
│                                                                          │
│ Type the table name to apply: [ orders        ]  [Apply to DEV]          │
│ [Export as Alembic] [Export SQL] [Request changes from agent]            │
└──────────────────────────────────────────────────────────────────────────┘
```

On Prod (v1), the apply button is replaced by the export buttons, with a note
explaining why.

### 7. Glossary

A searchable list of entries by object. It shows status (suggested, confirmed,
or needs review because the schema changed), the author, and the evidence. Inline
editing. Bulk confirm is allowed only per table, with a visible count.
Shows "used in N answers this week", so people can see the value of
maintaining it.

### 8. Seeds

The plan table from `plan_seed`: table order, row counts, and a generator per
column, each editable. Preview 20 rows. Then generate to a file or the shadow,
or (Sandbox/Dev with approval) the connection. Afterwards, show the fidelity
report: per-column distribution comparison against the profile.

### 9. Activity

The audit log for this connection, filterable by run, tool, and user. Each run
opens its full trace: plan, tool calls, SQL, and budget use.

## The agent panel in detail

- **Mode selector:** Explore, Ask, Change, Seed (03). The mode changes the
  input's placeholder and the available tools, and is shown on every message.
- **Plan checklist:** for multi-step runs, the agent's plan appears as a
  checklist that ticks off as steps finish.
- **Tool steps:** collapsed lines, such as `▸ describe_tables(orders, customers) · 120 ms`.
  Expanding one shows arguments and the result summary. This is the equivalent
  of the CLI transcript in the document agent walkthrough, and it is what lets
  a user tell an answer based on a lookup from a guess.
- **Evidence cards:** each cites a query, profile, or plan; clicking one opens it
  on the canvas. Answers reference them inline as `[1]`, `[2]`.
- **Budget meter:** a thin bar for model calls, tool calls, rows, and time.
  When it fills, the run stops with the reason, and offers "continue with a
  larger budget".
- **Approval prompts** appear inline ("The agent proposes migration #14 ·
  Review"), and link to the Changes tab. Approval is never possible from the
  chat panel itself.
- **Stop** cancels the run, including in-flight queries (02).

## States worth designing explicitly

| State | What to show |
| --- | --- |
| First connection, nothing profiled | Map with structure only; a banner offering "Profile the 20 largest tables (≈2 min, read-only)". |
| Huge schema (1,000+ tables) | Grouped map; search-first; the agent uses retrieval. Say "showing 40 of 1,184 tables". |
| No declared FKs at all | Map shows islands; the empty state offers "Infer relationships". |
| Shadow unavailable | Changes tab shows "Not verified: no shadow available" in amber, and explains how to enable it. Apply is disabled on Dev. |
| Local model too small for the task | After repeated repair failures: "This question may need a larger model" with a model switch, rather than silent failure. |
| Stale statistics | Grey stale badge; one-click refresh. |
| Run interrupted by restart | Thread shows "interrupted" with a re-run button. |

## Accessibility

- Every canvas action has a non-canvas equivalent: the ERD's information is
  also in the Tables view, so screen-reader users are not locked out of it.
- Edge kinds are distinguishable by line style and label, not only by colour.
- Tier is shown by text ("PROD") as well as colour.
- Focus order through the Changes screen ends on the apply control, and the
  typed confirmation field is labeled.
- Check contrast of the existing light theme's `--text-subtle` on glass
  surfaces. Azure-on-light-azure is close to the limit for small text.
