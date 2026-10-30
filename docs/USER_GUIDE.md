# Dimension — Autonomous Data & Schema Studio: User Guide

Welcome to the **Dimension Autonomous Data & Schema Studio**, an intelligent, privacy-first database workbench combining high-speed in-memory analytics (DuckDB), production database connectivity (PostgreSQL, MySQL, SQLite), automated schema cartography, data hygiene auditing, guarded natural-language-to-SQL execution, shadow-verified migrations, and topological synthetic test data synthesis.

---

## Table of Contents
1. [System Architecture & Core Philosophy](#1-system-architecture--core-philosophy)
2. [Environment Safety Tiers & Decision D5](#2-environment-safety-tiers--decision-d5)
3. [Connecting Databases & Local Files](#3-connecting-databases--local-files)
4. [The 6-View Studio Architecture](#4-the-6-view-studio-architecture)
   - [View 1: `[Chat]` (⌘1) — Guarded NL→SQL & Interactive Data Grid](#view-1-chat-1--guarded-nlsql--interactive-data-grid)
   - [View 2: `[Map]` (⌘2) — Schema Cartography & ERD Drift Diffing](#view-2-map-2--schema-cartography--erd-drift-diffing)
   - [View 3: `[Findings]` (⌘3) — Data Hygiene Inbox & Keyboard Triage (J/K/A/D)](#view-3-findings-3--data-hygiene-inbox--keyboard-triage-jkad)
   - [View 4: `[Changes]` (⌘4) — Shadow Migrations & Lock-Risk Linter](#view-4-changes-4--shadow-migrations--lock-risk-linter)
   - [View 5: `[Glossary]` (⌘5) — Semantic Schema Memory & dbt Export](#view-5-glossary-5--semantic-schema-memory--dbt-export)
   - [View 6: `[Seeds]` (⌘6) — Kahn's DAG Synthetic Data Synthesizer](#view-6-seeds-6--kahns-dag-synthetic-data-synthesizer)
5. [AST Safety Choke Point & HMAC Query Tokens](#5-ast-safety-choke-point--hmac-query-tokens)
6. [EXPLAIN Cost Guard & Budget Limits](#6-explain-cost-guard--budget-limits)
7. [Global Keyboard Shortcuts & Triage Reference](#7-global-keyboard-shortcuts--triage-reference)
8. [Local-First Security, Keyring Vault & Cryptographic Audit Trail](#8-local-first-security-keyring-vault--cryptographic-audit-trail)
9. [Next Steps & Cross-References](#9-next-steps--cross-references)

---

## 1. System Architecture & Core Philosophy

Dimension transforms how engineers, analysts, and developers interact with tabular datasets and production databases. Rather than manually crafting complex SQL joins, writing one-off pandas scripts, or risking accidental production mutations, Dimension provides:

- **Local-First by Default**: Runs entirely on your workstation via Ollama (`qwen3:4b`, `qwen2.5-coder`, `llama3`). Telemetry is disabled (`LANGCHAIN_TRACING_V2=false`).
- **Zero-Latency In-Memory Ingestion**: Drop CSV, Parquet, or SQLite files into the UI. An embedded DuckDB engine parses files instantly with vectorized execution.
- **Unified Engine Abstraction**: Run queries across DuckDB or live SQLAlchemy-supported engines (PostgreSQL, MySQL, SQLite) using the same UI and API.
- **Autonomous Multi-Tier Agent**: Translates English prompts into dialect-optimized SQL, cleaning pipelines, and Alembic migrations.
- **Built-in Safety Firewall**: Token-level AST inspection guarantees that mutating statements cannot run while in Read-Only mode, backed by cryptographic HMAC query authorization.

```
                      +---------------------------------------+
                      | Dimension UI (Carbon / Frosted Glass) |
                      +-------------------+-------------------+
                                          |
                        HTTP / SSE Stream | (Port 8001)
                                          v
                      +---------------------------------------+
                      |       FastAPI Backend Orchestrator    |
                      +---------+-------------------+---------+
                                |                   |
             +------------------+                   +------------------+
             v                                                         v
+--------------------------+                               +--------------------------+
|  DuckDB In-Memory Engine |                               |  SQLAlchemy Engine Pool  |
|  (CSV, Parquet, SQLite)  |                               |  (PostgreSQL, MySQL)     |
+--------------------------+                               +--------------------------+
             |                                                         |
             +--------------------------+------------------------------+
                                        |
                                        v
                      +---------------------------------------+
                      | 6-View Autonomous Intelligence Studio |
                      | [Chat]     [Map]      [Findings]      |
                      | [Changes]  [Glossary] [Seeds]         |
                      +---------------------------------------+
```

---

## 2. Environment Safety Tiers & Decision D5

Every saved database connection belongs to an explicit **Deployment Tier** that governs agent row read bounds, PII masking, and migration approval strictness:

| Tier | UI Badge | Purpose | Agent Read Row Limit | PII Masking | Migration Apply Policy |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Sandbox** | 🟢 Green | Local SQLite files, DuckDB, disposable Docker copies | 50,000,000 | On by default; can be disabled | One-click apply after shadow verification |
| **Dev / Staging** | 🟡 Amber | Shared development databases | 10,000,000 | **Locked ON** | Requires typed confirmation matching the connection name |
| **Prod** | 🔴 Red | Live customer production databases | 1,000,000 | **Locked ON** | **Strictly blocked (Decision D5)** — Export migration scripts only |

> [!IMPORTANT]
> **Production Safety Guarantee (Decision D5)**:
> Direct autonomous writes to `prod` connections are disabled by default. Proposals targeting production databases can only be exported as reviewed migration scripts (Alembic, Flyway, or raw SQL).

### Privilege Grading

When a connection is established, Dimension inspects database privileges and assigns a letter grade:
- **Grade A (Optimal)**: The connection user has strictly `SELECT`-only privileges across all tables.
- **Grade B (Managed)**: The user has write grants, but Dimension enforces session-level read-only mode (`default_transaction_read_only = on` or `SET SESSION TRANSACTION READ ONLY`).
- **Grade C (Advisory Warning)**: The user has superuser/admin privileges. Dimension displays an advisory warning banner.

---

## 3. Connecting Databases & Local Files

Dimension supports two ingestion paths: drag-and-drop local file ingestion and direct connection to live databases.

### Zero-Setup Local Files (DuckDB In-Memory)
1. Locate the **Drop datasets or browse files** dropzone in the left sidebar.
2. Drag and drop any supported structured file:
   - **CSV / TSV** (`.csv`, `.tsv`): Automatically parsed with type inference and header detection.
   - **Apache Parquet** (`.parquet`, `.pq`): Loaded with high-speed column-level metadata.
   - **SQLite Database** (`.sqlite`, `.sqlite3`, `.db`): Introspected via SQLite PRAGMA catalog; tables and foreign key constraints copied to DuckDB.
3. The active table name is derived from the filename (e.g. `ecommerce.sqlite` loads all tables).

### Live Production Databases (PostgreSQL, MySQL, SQLite)
1. Click **Connect Database** in the left sidebar.
2. Provide connection URI:
   - **PostgreSQL**: `postgresql://username:password@localhost:5432/dbname`
   - **MySQL**: `mysql+pymysql://username:password@localhost:3306/dbname`
   - **SQLite**: `sqlite:///absolute/path/to/database.db`
3. Select the environment tier (`sandbox`, `dev`, `prod`).
4. Click **Connect & Introspect**. Credentials are automatically routed to your OS keychain (`keyring`).

---

## 4. The 6-View Studio Architecture

Dimension organizes the engineering workflow into 6 cohesive views accessible via top header tabs or keyboard shortcuts:

```mermaid
flowchart LR
    V1["1. Chat & SQL (⌘1)"] --> V2["2. ERD Map (⌘2)"]
    V2 --> V3["3. Hygiene Findings (⌘3)"]
    V3 --> V4["4. Changes & Migrations (⌘4)"]
    V4 --> V5["5. Schema Glossary (⌘5)"]
    V5 --> V6["6. Synthetic Seeds (⌘6)"]
```

---

### View 1: `[Chat]` (⌘1) — Guarded NL→SQL & Interactive Data Grid

The **Chat & SQL Workbench** provides an autonomous conversational copilot for data exploration, SQL drafting, and guarded execution.

#### 1. The Prompt Dock & Reasoning Controls
- **Natural Language Input**: Type analytical questions (e.g. *"Which customer generated the highest total order revenue?"*).
- **Model Selector**: Switch between local Ollama models (`qwen3:4b`, `llama3`) and cloud LLMs (`gpt-4o-mini`, `gemini-1.5-flash`).
- **Reasoning Effort**:
  - `Low (Fast)`: Quick, direct query generation (budget: 10 tool calls).
  - `Medium`: Balanced analytical synthesis (budget: 25 tool calls).
  - `Deep (High)`: Detailed schema exploration with comprehensive CTE logic (budget: 50 tool calls).
- **Safety Mode**: Default is strictly `Read-Only [Safe]`.

#### 2. 1-Click SQL Runner Card
When the agent generates an executable SQL statement, it mounts an interactive runner card:

```
+--------------------------------------------------------------------------+
|  [>] SQL Query  (PostgreSQL)                  [Run on DB] [Copy] [Explain] |
+--------------------------------------------------------------------------+
|  SELECT                                                                  |
|      c.name AS customer_name,                                            |
|      COUNT(o.id) AS total_orders,                                        |
|      ROUND(SUM(o.total_amount), 2) AS total_spent                        |
|  FROM customers c                                                        |
|  JOIN orders o ON c.id = o.customer_id                                   |
|  GROUP BY c.name                                                         |
|  ORDER BY total_spent DESC                                               |
|  LIMIT 10;                                                               |
+--------------------------------------------------------------------------+
```

- **Run on DB**: Dispatches query through AST Guard and EXPLAIN cost guard, requesting an HMAC `query_token` before executing against a read-only session.
- **Copy**: Copies exact SQL query string to system clipboard with animated confirmation.
- **Explain**: Asks agent for a line-by-line query plan, index recommendations, and performance notes.

#### 3. High-Density Interactive Data Grid
Query results mount in the high-performance Data Grid:
- **Smart Sorting**: Click column headers to sort mathematically for numbers, chronologically for dates, and case-insensitively for strings.
- **Real-Time Global Search**: Filter rows across all columns simultaneously as you type.
- **Pagination**: Select `10`, `25`, `50`, or `100` rows per page.
- **Instant Export**: 1-click export to sanitized **CSV** or structured **JSON**.

---

### View 2: `[Map]` (⌘2) — Schema Cartography & ERD Drift Diffing

The **Map View** renders an interactive Entity-Relationship Diagram (ERD) canvas visualizing table structures, declared constraints, and inferred semantic links.

```mermaid
flowchart LR
    A["orders"] -->|"Solid Blue (Declared FK: 1.00)"| B["customers"]
    A -.->|"Dashed Amber (Inferred FK: 0.94)"| C["accounts"]
    A ==>|"Double Green (Confirmed Join)"| D["promotions"]
```

#### Relationship Edge Types:
1. **Solid Blue Line**: **Declared Foreign Key** defined in the database DDL.
2. **Dashed Amber Line**: **Inferred Foreign Key** discovered by containment analysis ($\ge 0.85$ confidence score). Click edge to review score details and confirm or reject.
3. **Double Green Line**: **Confirmed Semantic Join** approved by the engineer. Permanently saved in the schema memory glossary and used in subsequent NL→SQL join paths.

#### Containment Scoring Formula:
$$\text{Score} = 0.50 \times \text{Containment} + 0.25 \times \text{NameSimilarity} + 0.15 \times \text{TypeCompatibility} + 0.10 \times \text{CardinalityFit}$$

#### Anti-Trap Heuristics:
- **Lookup Table Trap Suppression**: Low-cardinality status codes (`1..7`) matching unrelated region/state IDs are filtered out.
- **Shared Sequence Trap Suppression**: Unrelated auto-increment surrogate IDs (`1, 2, 3...`) are rejected.

#### Snapshot & Schema Drift Diffing:
- **Point-in-Time Diff**: Compare any two recorded snapshots (`GET /api/v2/snapshots/{id_a}/diff/{id_b}`) to detect added/dropped tables, column type alterations, and changed nullabilities.
- **Cross-Connection Drift**: Compare staging vs production (`GET /api/v2/connections/{conn_a}/diff/{conn_b}`) to verify migrations before promotion.

---

### View 3: `[Findings]` (⌘3) — Data Hygiene Inbox & Keyboard Triage (J/K/A/D)

The **Findings View** provides a data hygiene inbox that scans for anomalies degrading query performance or exposing sensitive information.

#### 5 Major Anomaly Classes:
1. **Orphan Rows (⚠️)**: Child foreign keys referencing non-existent parent primary keys (e.g. `0.7% orders.cust reference non-existent tbl_cx.cx_id`).
2. **Sentinel Values (🚫)**: Magic placeholder strings masking missing data (e.g. `'000-00-0000'`, `'1900-01-01'`, `999999`).
3. **Format Skew (🔄)**: Mixed date/timestamp formats in a single column (e.g. `2024-01-15` mixed with `01/15/2024`).
4. **PII Exposure (🔒)**: Unmasked personal data detected in non-compliant columns (SSNs, credit cards with Luhn checksum verification, emails, phone numbers).
5. **Missing Indexes (⚡)**: High-cardinality foreign keys lacking database index support, causing sequential scans on joins.

#### Superhuman Keyboard Triage:
Engineers can triage findings entirely via keyboard:

| Shortcut | Action | Description |
| :--- | :--- | :--- |
| **`J`** | **Next Finding** | Moves active selection down to the next finding card. |
| **`K`** | **Previous Finding** | Moves active selection up to the previous finding card. |
| **`A`** | **Accept Finding** | Converts finding into a migration proposal or glossary rule. |
| **`D`** | **Dismiss Finding** | Records finding as dismissed in connection memory. |

Each finding is tracked by a stable SHA-256 fingerprint: $\text{hash}(\text{table}, \text{column}, \text{rule})$. Dismissed findings are permanently suppressed from future scans unless anomalous rates jump significantly.

---

### View 4: `[Changes]` (⌘4) — Shadow Migrations & Lock-Risk Linter

The **Changes View** implements a verify-before-write migration pipeline. Every schema modification is proven on an isolated shadow clone before touching real environments.

```mermaid
sequenceDiagram
    autonumber
    actor Engineer
    participant Changes as Changes View
    participant Linter as Lock-Risk Linter
    participant Shadow as Shadow DB Manager
    participant Gate as Approval Gate
    participant Target as Target DB (Dev)

    Engineer->>Changes: Propose DDL (UP & DOWN scripts)
    Changes->>Linter: Scan DDL for concurrency and lock hazards
    Linter-->>Changes: Lock report (e.g., ACCESS EXCLUSIVE alert)
    Changes->>Shadow: Run UP migration on isolated clone
    Shadow-->>Changes: UP verified
    Changes->>Shadow: Run DOWN migration
    Shadow-->>Changes: DOWN verified (clean rollback, 0 residue)
    Changes->>Gate: Display diff, shadow proof, and lock report
    Engineer->>Gate: Review & Approve (Type target connection name)
    Gate->>Target: Apply verified DDL
```

#### Lock-Risk & Impact Linter Rules:
- `CREATE INDEX`: Flags unindexed concurrent locks; recommends `CREATE INDEX CONCURRENTLY`.
- `ALTER TABLE ADD COLUMN NOT NULL`: Flags full-table lock rewrite; recommends nullable addition, batched backfill, then `NOT NULL`.
- `DROP TABLE / COLUMN`: Flags permanent data loss; checks view dependencies via `pg_depend`.

#### Two-Way Shadow Verification:
- Applies `UP` script on a disposable database copy (SQLite temp file, DuckDB in-memory, or Postgres scratch replica).
- Applies `DOWN` script and verifies that resulting schema matches original snapshot byte-for-byte with zero residual artifacts.

#### Production Protection (Decision D5):
On `prod` connections, the **Apply** button is permanently disabled. Proposals export directly to:
- **Alembic**: Full Python `upgrade()` / `downgrade()` script.
- **Flyway**: Numbered `V{N}__...sql` and `U{N}__...sql` scripts.
- **Raw SQL**: Forward and rollback scripts with dependency analysis.

---

### View 5: `[Glossary]` (⌘5) — Semantic Schema Memory & dbt Export

The **Glossary View** serves as persistent semantic schema memory across sessions:
- **Business Terms**: Define metrics and formulas (e.g. *"Active Customer"* = `status = 'active' AND last_login >= NOW() - INTERVAL '90 days'`).
- **Enum Mappings**: Clarify integer status codes (e.g. `status_code`: `{1: 'new', 2: 'processing', 3: 'shipped', 4: 'refunded'}`).
- **Join Conventions**: Document undeclared join paths between tables.
- **Caveat Rules**: Register filters for internal test data (e.g. `WHERE is_test = 0`).

#### Automatic Prompt Injection:
When relevant tables are referenced, confirmed glossary definitions are automatically injected into agent reasoning, preventing hallucinations.

#### 1-Click Export:
- Export verified schema data dictionary in **Markdown** format.
- Export production-ready **dbt `sources.yml`** with column tests (`not_null`, `unique`, `relationships`).

---

### View 6: `[Seeds]` (⌘6) — Kahn's DAG Synthetic Data Synthesizer

The **Seeds View** generates synthetic test data satisfying relational constraints with zero foreign key violations.

```mermaid
flowchart TD
    customers["1. customers (Root Parent)"] --> orders["2. orders (Child)"]
    products["1. products (Root Parent)"] --> order_items["3. order_items (Leaf Child)"]
    orders --> order_items
```

#### Kahn's Topological Sorting:
Sorts database tables by dependency depth, guaranteeing parent rows are inserted before child rows reference them.

#### 3-Pass Cycle Resolution:
For self-referencing tables (`employees.manager_id -> employees.id`):
1. **Pass 1**: Insert parent rows with self-reference set to `NULL`.
2. **Pass 2**: Insert remaining child records referencing active parent IDs.
3. **Pass 3**: Backfill self-referencing foreign keys to point to valid records within the generated batch.

#### Faker PII Replacement:
Real customer emails, phone numbers, and names are never copied. Synthetic values are deterministically synthesized using Python `Faker`.

#### Export Options:
- **Direct Insertion**: Injects records directly into `sandbox` or `dev` connections within a transaction.
- **SQL INSERT Script**: Generates ordered `.sql` insert script.
- **Parquet Files**: Generates columnar `.parquet` files for data lake loading.

---

## 5. AST Safety Choke Point & HMAC Query Tokens

Every SQL statement—whether generated by an LLM or typed by a user—passes through the AST SQL Guard powered by `sqlglot`:

```mermaid
flowchart TD
    NL["User / Agent SQL Query"] --> AST["AST Parser (sqlglot)"]
    AST -->|Multi-statement, CTE write, DROP/ALTER| REJECT["Strict 400 Abort"]
    AST -->|Valid Read-Only SELECT| REWRITE["LIMIT Rewrite & Cap"]
    REWRITE --> COST["EXPLAIN Plan & Cost Guard"]
    COST -->|Estimated cost > budget| MODAL["Approval / Heavy Warning"]
    COST -->|Safe within budget| TOKEN["HMAC Query Token Issued (TTL: 60s)"]
    TOKEN --> EXEC["POST /sql/run (Execute on Managed Connection)"]
```

### Safety Rules Enforced:
1. **Strict Read-Only Enforcement**: Rejects any statement containing `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `CREATE`, `TRUNCATE`, `GRANT`, `REVOKE`, `COPY`, or `SELECT INTO`.
2. **CTE Injection Defense**: Analyzes Common Table Expressions (`WITH ... AS (...)`) to prevent masked DDL/DML execution (e.g. `WITH del AS (DELETE FROM orders RETURNING *) SELECT * FROM del;`).
3. **Multi-Statement Rejection**: Aborts queries containing semicolons followed by secondary commands.
4. **Mandatory Row Fetch Capping**:
   - Injects `LIMIT 500` by default if no `LIMIT` is specified.
   - Enforces a maximum cap of `10,000` rows for UI grid rendering.
   - Restricts LLM agent context retrieval to `50` rows.
5. **Cryptographic `query_token`**: Once validated, the engine generates an HMAC signature:
   $$\text{token} = \text{HMAC-SHA256}(\text{secret}, \text{query} \parallel \text{conn\_id} \parallel \text{timestamp})$$
   The execution runner (`POST /api/v2/connections/{conn_id}/sql/run`) strictly refuses to execute any query that lacks a valid token issued within the last 60 seconds.

---

## 6. EXPLAIN Cost Guard & Budget Limits

Before dispatching queries to target databases, Dimension executes an `EXPLAIN (FORMAT JSON)` query plan inspection:

- **Sequential Scan Threshold**: Flags sequential scans on tables exceeding tier thresholds (> 1,000,000 rows on dev, > 500,000 rows on prod).
- **Nested Loop Warnings**: Detects unindexed cartesian joins that would lock connection threads or saturate memory.
- **Estimated Row Cost**: Calculates total cost units against the connection budget. If estimated execution time exceeds 5 seconds, an interactive confirmation dialog appears before execution.

---

## 7. Global Keyboard Shortcuts & Triage Reference

| Shortcut | Scope | Action | Description |
| :--- | :--- | :--- | :--- |
| **`⌘1`** / `Ctrl+1` | Global | Switch to **`[Chat]`** | Opens the conversational guarded SQL interface. |
| **`⌘2`** / `Ctrl+2` | Global | Switch to **`[Map]`** | Opens the interactive ERD schema canvas. |
| **`⌘3`** / `Ctrl+3` | Global | Switch to **`[Findings]`** | Opens the data hygiene and quality triage inbox. |
| **`⌘4`** / `Ctrl+4` | Global | Switch to **`[Changes]`** | Opens the shadow migration and DDL workbench. |
| **`⌘5`** / `Ctrl+5` | Global | Switch to **`[Glossary]`** | Opens semantic schema memory and dbt exports. |
| **`⌘6`** / `Ctrl+6` | Global | Switch to **`[Seeds]`** | Opens Kahn's DAG synthetic data generator. |
| **`⌘B`** / `Ctrl+B` | Global | Toggle Sidebar | Expands or collapses the left navigation panel. |
| **`⌘K`** / `Ctrl+K` | Global | New Session | Starts a fresh conversational agent thread. |
| **`⌘+Shift+F`** | Global | Focus Mode | Toggles full-width canvas view for deep data inspection. |
| **`Enter`** | Chat Input | Send Prompt | Submits prompt to autonomous agent. |
| **`Esc`** | Global | Dismiss / Cancel | Closes open modals or halts active agent streaming. |
| **`J`** | Findings View | Next Finding | Moves selection cursor down to the next finding card. |
| **`K`** | Findings View | Previous Finding | Moves selection cursor up to the previous finding card. |
| **`A`** | Findings View | Accept Finding | Converts finding into a migration or glossary rule. |
| **`D`** | Findings View | Dismiss Finding | Dismisses finding and stores decision in connection memory. |
| **`☀️ / 🌙`** | Global | Toggle Theme | Switches between Obsidian Dark and Clean Light themes. |

---

## 8. Local-First Security, Keyring Vault & Cryptographic Audit Trail

### 1. Zero Cloud Leakage
By default, Dimension runs entirely on your local workstation with Ollama (`qwen3:4b`, `llama3`). No query text or schema metadata leaves your device. External telemetry flags (`LANGCHAIN_TRACING_V2 = "false"`) are hard-coded in configuration to prevent LangSmith or third-party log ingestion.

### 2. Operating System Credential Vault
Passwords are never written in plain text to disk or stored in the local SQLite metadata database:
- Stored in your OS keychain (`keyring` on macOS Keychain, Windows Credential Manager, or Linux Secret Service) under the `dimension_studio` namespace.
- The application database stores only an opaque, non-reversible secret reference key (e.g. `sec_7f9b1c0d`).
- Retrieved into memory only at the moment a database session is opened.

### 3. PII Masking & Cloud Disclosure Guarantee
When cloud language models (e.g. OpenAI, Anthropic) are enabled for a connection:
- The PII masking engine is **permanently locked on** and cannot be toggled off.
- Raw customer data rows never leave your machine.
- Engineers can audit the exact boundary of what leaves the machine at any time via:
  `GET /api/v2/connections/{connection_id}/cloud-disclosure`

### 4. Cryptographic Hash-Chained Audit Trail
Every statement execution, migration proposal, and schema change is recorded in an append-only `audit_entries` table.

Each entry is cryptographically linked to the previous entry via SHA-256:
$$\text{Hash}_i = \text{SHA256}(\text{Hash}_{i-1} \parallel \text{Actor} \parallel \text{Action} \parallel \text{TargetConnection} \parallel \text{Timestamp})$$

You can verify the tamper-proof audit chain at any time via:
`GET /api/v2/connections/{conn_id}/audit`

---

## 9. Next Steps & Cross-References

- **[Detailed User Guides (01 to 08)](file:///Users/aagam/Agentic%20Q%26A/docs/user/)**: Step-by-step guides for all features.
- **[API Reference](file:///Users/aagam/Agentic%20Q%26A/docs/API_REFERENCE.md)**: Complete technical specification for all v2 REST and SSE endpoints.
- **[Sample Datasets Testing Guide](file:///Users/aagam/Agentic%20Q%26A/docs/SAMPLE_DATASETS_GUIDE.md)**: Testing recipes for `shop_messy.db`, `wide_schema.db`, and `ecommerce.sqlite`.
- **[Architecture Contract](file:///Users/aagam/Agentic%20Q%26A/docs/ARCHITECTURE_CONTRACT.md)**: Formal specifications for the 13 `ToolSpec` definitions and the agent streaming model.
