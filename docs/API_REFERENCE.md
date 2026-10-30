# Dimension — Autonomous Data & Schema Studio: API Reference (v2)

This document provides production-grade technical specifications for the Dimension Autonomous Data & Schema Studio REST and Server-Sent Events (SSE) v2 APIs (`/api/v2/*`).

---

## Table of Contents
1. [General Information & Base URL](#1-general-information--base-url)
2. [Data Formats & Error Codes](#2-data-formats--error-codes)
3. [Connection Management Endpoints](#3-connection-management-endpoints)
4. [Snapshots & Schema Drift Diffing Endpoints](#4-snapshots--schema-drift-diffing-endpoints)
5. [Schema Graph & Inferred Relationships Endpoints](#5-schema-graph--inferred-relationships-endpoints)
6. [Data Hygiene & Findings Inbox Endpoints](#6-data-hygiene--findings-inbox-endpoints)
7. [Guarded SQL Check & Authorized Execution Endpoints](#7-guarded-sql-check--authorized-execution-endpoints)
8. [Proposals & Shadow Migrations Endpoints](#8-proposals--shadow-migrations-endpoints)
9. [Semantic Glossary & Data Dictionary Export Endpoints](#9-semantic-glossary--data-dictionary-export-endpoints)
10. [Synthetic Test Data (Seeds) Endpoints](#10-synthetic-test-data-seeds-endpoints)
11. [Autonomous Studio Agent Runs & SSE Streaming](#11-autonomous-studio-agent-runs--sse-streaming)
12. [Model Capabilities & Cryptographic Audit Trail](#12-model-capabilities--cryptographic-audit-trail)
13. [Client Integration Examples](#13-client-integration-examples)

---

## 1. General Information & Base URL

- **Base URL**: `http://localhost:8001/api/v2`
- **Interactive OpenAPI / Swagger**: Available at `http://localhost:8001/docs` (JSON schema: `http://localhost:8001/openapi.json`)
- **Protocol**: HTTP/1.1 and HTTP/2 supported
- **Streaming**: Server-Sent Events (SSE) with MIME type `text/event-stream` for agent run telemetry.

---

## 2. Data Formats & Error Codes

- All JSON requests must supply `Content-Type: application/json`.
- All JSON responses return standard HTTP status codes:
  - `200 OK`: Request succeeded.
  - `400 Bad Request`: Validation failure, syntax error, or AST safety guard abort.
  - `403 Forbidden`: Token authorization failure, HMAC expiry, or Decision D5 production write violation.
  - `404 Not Found`: Resource (connection, snapshot, proposal, run) not found.
  - `500 Internal Server Error`: Server exception.

Standard error responses follow FastAPI format:
```json
{
  "detail": {
    "code": "SQL_MUTATION_BLOCKED",
    "message": "Mutating statement 'DROP' blocked in read-only mode."
  }
}
```

---

## 3. Connection Management Endpoints

### 1. `POST /api/v2/connections`
Registers a new database connection, tests connectivity, assigns a privilege grade, saves passwords to the OS keychain (`keyring`), and captures an initial schema snapshot.

**Request Body (`ConnectionCreateRequest`):**
```json
{
  "name": "Local Analytics Store",
  "engine": "postgresql",
  "dsn_template": "postgresql://analyst@localhost:5432/analytics",
  "tier": "dev",
  "password": "secure_password_123",
  "cloud_models_allowed": false,
  "masking_enabled": true
}
```

**Response (`200 OK`):**
```json
{
  "status": "success",
  "connection_id": "conn_9a41b2c8",
  "privilege_grade": "A"
}
```

---

### 2. `GET /api/v2/connections`
Returns all registered connections.

**Response (`200 OK`):**
```json
{
  "status": "success",
  "connections": [
    {
      "id": "conn_9a41b2c8",
      "name": "Local Analytics Store",
      "engine": "postgresql",
      "tier": "dev",
      "privilege_grade": "A",
      "cloud_models_allowed": 0,
      "masking_enabled": 1,
      "created_at": "2026-10-30T18:00:00Z"
    }
  ]
}
```

---

### 3. `GET /api/v2/connections/{conn_id}`
Returns details for a single connection.

---

### 4. `PATCH /api/v2/connections/{conn_id}`
Updates connection properties (e.g. tier, name, cloud model permissions). When `cloud_models_allowed` is set to `true`, `masking_enabled` is automatically locked to `true`.

**Request Body (`ConnectionUpdateRequest`):**
```json
{
  "tier": "prod",
  "cloud_models_allowed": true
}
```

---

### 5. `DELETE /api/v2/connections/{conn_id}`
Deletes a connection and removes secret keys from the OS keychain vault.

---

### 6. `POST /api/v2/connections/test`
Validates connection credentials, probes privileges, and returns the assigned letter grade without saving.

**Request Body (`ConnectionTestRequest`):**
```json
{
  "engine": "sqlite",
  "dsn_template": "data/sample_datasets/ecommerce.sqlite",
  "password": null
}
```

**Response (`200 OK`):**
```json
{
  "status": "success",
  "connected": true,
  "privilege_grade": "A",
  "grants": ["SELECT"],
  "shadow_available": true
}
```

---

### 7. `GET /api/v2/connections/{conn_id}/cloud-disclosure`
Audits the exact boundary of what leaves the machine if cloud language models are enabled.

**Response (`200 OK`):**
```json
{
  "status": "success",
  "connection_id": "conn_9a41b2c8",
  "connection_name": "Local Analytics Store",
  "tier": "dev",
  "cloud_models_allowed": true,
  "masking_locked": true,
  "data_leaving_machine": [
    "User natural language prompt",
    "Compact schema notation (table & column names, primary keys)",
    "Masked statistical aggregations (null rates, cardinality)",
    "Relevant business glossary definitions"
  ],
  "data_staying_local": [
    "Raw customer data rows (masked via Faker and deterministic anonymizers)",
    "Database passwords and keychain credentials",
    "Database dumps and full table contents",
    "Internal SQLite audit trail and cryptographic hash chains"
  ],
  "disclosure_summary": "When a cloud model is active, prompts, schema excerpts, and masked distributions leave this machine. Raw customer rows and credentials never leave."
}
```

---

### 8. `GET /api/v2/connections/{conn_id}/tables`
Returns a paginated list of tables matching an optional search query.

**Query Parameters:**
- `query` (optional string): Table or column search phrase.
- `limit` (default: 50): Max tables returned.

---

### 9. `GET /api/v2/connections/{conn_id}/tables/{table_name}`
Returns full column structural schema, keys, and glossary annotations for a specific table.

---

## 4. Snapshots & Schema Drift Diffing Endpoints

### 1. `POST /api/v2/connections/{conn_id}/snapshots`
Captures an immutable schema snapshot with a canonical SHA-256 hash.

**Response (`200 OK`):**
```json
{
  "status": "success",
  "snapshot_id": "snap_f1b4028e"
}
```

---

### 2. `GET /api/v2/connections/{conn_id}/snapshots`
Lists snapshot history for a connection.

---

### 3. `GET /api/v2/connections/{conn_id}/snapshots/latest`
Retrieves the most recent snapshot for a connection.

---

### 4. `GET /api/v2/snapshots/{snapshot_id}`
Retrieves a specific snapshot by its unique identifier.

---

### 5. `GET /api/v2/snapshots/{snap_a_id}/diff/{snap_b_id}`
Computes a point-in-time structural diff between two snapshots:
- Added / dropped tables
- Added / dropped / altered columns
- Added / dropped foreign keys and primary keys

---

### 6. `GET /api/v2/connections/{conn_a_id}/diff/{conn_b_id}`
Computes a cross-environment diff (e.g. comparing `staging` vs `prod` schemas).

---

### 7. `GET /api/v2/connections/{conn_id}/diff`
Computes structural drift by comparing the latest recorded snapshot against the live database state.

---

## 5. Schema Graph & Inferred Relationships Endpoints

### 1. `GET /api/v2/connections/{conn_id}/graph`
Returns the complete ERD topology for canvas rendering:
- `tables`: Node list with names, row counts, and column lists.
- `edges`: Declared foreign key relationships.
- `inferred_edges`: High-confidence relationships discovered by the containment engine.
- `confirmed_edges`: Inferred relationships confirmed by users.

---

### 2. `POST /api/v2/connections/{conn_id}/relationships/infer`
Executes mathematical containment analysis across unconstrained columns:
$$\text{Score} = 0.50 \times \text{Containment} + 0.25 \times \text{NameSim} + 0.15 \times \text{TypeCompat} + 0.10 \times \text{CardFit}$$

**Query Parameters:**
- `min_score` (default: 0.60): Confidence threshold.

---

### 3. `POST /api/v2/relationships/{rel_id}/confirm`
Promotes an inferred relationship to confirmed status, storing it in the semantic glossary.

---

### 4. `POST /api/v2/relationships/{rel_id}/reject`
Dismisses an inferred candidate relationship.

---

## 6. Data Hygiene & Findings Inbox Endpoints

### 1. `POST /api/v2/connections/{conn_id}/hygiene`
Executes deep data hygiene inspection across tables. Detects:
- Orphan child records
- Sentinel values (`'000-00-0000'`, `'1900-01-01'`, `999999`)
- Format skew (mixed date strings)
- PII exposure (emails, phones, SSNs, credit cards)
- Missing indexes on foreign keys

---

### 2. `GET /api/v2/connections/{conn_id}/findings`
Queries the findings inbox.

**Query Parameters:**
- `status` (`open`, `accepted`, `dismissed`)
- `category` (`orphan_records`, `sentinel_values`, `format_skew`, `pii_exposure`, `missing_index`)
- `limit` (default: 100)

---

### 3. `PATCH /api/v2/findings/{finding_id}`
Updates a finding's status during keyboard triage (`J`/`K`/`A`/`D`).

**Request Body (`FindingStatusUpdate`):**
```json
{
  "status": "dismissed",
  "dismiss_reason": "Legacy archive data; will not backfill."
}
```

---

## 7. Guarded SQL Check & Authorized Execution Endpoints

### 1. `POST /api/v2/connections/{conn_id}/sql/check`
Step 1 of guarded execution. Performs:
1. AST parsing via `sqlglot` to verify read-only safety.
2. Injects or caps `LIMIT` clause (default `500`, maximum `10,000`).
3. Runs `EXPLAIN (FORMAT JSON)` to estimate execution cost and flag sequential scans.
4. Issues an HMAC-SHA256 signed `query_token` valid for 60 seconds.

**Request Body (`SQLCheckRequest`):**
```json
{
  "sql": "SELECT c.name, SUM(o.total_amount) FROM customers c JOIN orders o ON c.id = o.customer_id GROUP BY c.name",
  "enforce_limit": true
}
```

**Response (`200 OK`):**
```json
{
  "status": "success",
  "sanitized_sql": "SELECT c.name, SUM(o.total_amount) FROM customers AS c JOIN orders AS o ON c.id = o.customer_id GROUP BY c.name LIMIT 500",
  "query_token": "ey...signed_hmac_token",
  "cost_evaluation": {
    "total_cost": 142.5,
    "sequential_scans": [],
    "requires_confirmation": false,
    "warnings": []
  },
  "metadata": {
    "tables": ["customers", "orders"],
    "final_limit": 500,
    "limit_rewritten": true
  }
}
```

---

### 2. `POST /api/v2/connections/{conn_id}/sql/run`
Step 2 of guarded execution. Verifies the cryptographic HMAC `query_token` and executes query against a managed read-only session.

**Request Body (`SQLRunRequest`):**
```json
{
  "query_token": "ey...signed_hmac_token",
  "page": 1,
  "page_size": 50
}
```

**Response (`200 OK`):**
```json
{
  "status": "success",
  "columns": ["name", "SUM(o.total_amount)"],
  "rows": [
    ["Alice Smith", 482.50],
    ["Bob Johnson", 310.00]
  ],
  "row_count": 2,
  "execution_time_ms": 4.8,
  "truncated": false
}
```

---

## 8. Proposals & Shadow Migrations Endpoints

### 1. `POST /api/v2/proposals`
Submits a schema migration proposal. Scans DDL for lock risks (`ACCESS EXCLUSIVE`) and runs two-way verification on an isolated shadow clone.

**Request Body (`ProposalCreateRequest`):**
```json
{
  "title": "Add loyalty points to customers",
  "description": "Introduces indexed integer loyalty_points with default 0",
  "connection_id": "conn_9a41b2c8",
  "up_sql": "ALTER TABLE customers ADD COLUMN loyalty_points INTEGER DEFAULT 0 NOT NULL; CREATE INDEX ix_customers_loyalty_points ON customers (loyalty_points);",
  "down_sql": "DROP INDEX IF EXISTS ix_customers_loyalty_points; ALTER TABLE customers DROP COLUMN IF EXISTS loyalty_points;",
  "affected_tables": ["customers"]
}
```

**Response (`200 OK`):**
```json
{
  "status": "success",
  "proposal_id": "prop_8c12a7d4",
  "lock_warnings": [],
  "shadow_verified": true,
  "status": "verified"
}
```

---

### 2. `GET /api/v2/connections/{conn_id}/proposals`
Lists proposals for a connection.

---

### 3. `GET /api/v2/proposals/{prop_id}`
Retrieves proposal details, lock-risk audit, and shadow verification proof.

---

### 4. `POST /api/v2/proposals/{prop_id}/decision`
Records user approval or rejection.

**Request Body (`DecisionRequest`):**
```json
{
  "decision": "approved",
  "reason": "Reviewed and verified on staging shadow copy.",
  "decided_by": "lead_engineer"
}
```

---

### 5. `POST /api/v2/proposals/{prop_id}/apply`
Applies an approved proposal to the database.

> [!CAUTION]
> **Production Guardrail (Decision D5)**:
> If the target connection is marked `tier: "prod"`, this endpoint aborts with HTTP `403 Forbidden`:
> `"Direct migration execution is disabled on PROD connections in v1 (Decision D5). Please use /export to generate a migration script."`

---

### 6. `GET /api/v2/proposals/{prop_id}/export`
Exports proposal to external migration tool formats.

**Query Parameters:**
- `format`: `alembic` (Python SQLAlchemy), `flyway` (numbered SQL pair), or `sql` (raw UP/DOWN).

---

## 9. Semantic Glossary & Data Dictionary Export Endpoints

### 1. `GET /api/v2/connections/{conn_id}/glossary`
Lists semantic definitions, enum mappings, join conventions, and caveat filters.

---

### 2. `POST /api/v2/connections/{conn_id}/glossary`
Creates a new glossary term or business rule.

**Request Body (`GlossaryEntryCreate`):**
```json
{
  "target_kind": "column",
  "target": "orders.status_code",
  "kind": "enum_map",
  "body": "{1: 'new', 2: 'processing', 3: 'shipped', 4: 'refunded'}"
}
```

---

### 3. `PATCH /api/v2/glossary/{entry_id}`
Updates term status (`confirmed`, `suggested`, `rejected`).

---

### 4. `GET /api/v2/connections/{conn_id}/export/docs`
Exports verified schema data dictionary.

**Query Parameters:**
- `format`: `markdown` (formatted markdown documentation) or `dbt_sources` (production `sources.yml` with tests).

---

## 10. Synthetic Test Data (Seeds) Endpoints

### 1. `POST /api/v2/connections/{conn_id}/seed-plans`
Computes Kahn's topological DAG dependency ordering and builds an executable seed plan.

**Request Body (`SeedPlanRequest`):**
```json
{
  "row_counts": {
    "customers": 50,
    "orders": 200,
    "order_items": 500
  }
}
```

**Response (`200 OK`):**
```json
{
  "status": "success",
  "plan": {
    "execution_order": ["customers", "products", "orders", "order_items"],
    "row_counts": {
      "customers": 50,
      "products": 20,
      "orders": 200,
      "order_items": 500
    },
    "cycle_breaks": []
  }
}
```

---

### 2. `POST /api/v2/connections/{conn_id}/seed-plans/generate`
Generates deterministic synthetic SQL statements with Faker PII replacement.

**Request Body (`SeedGenerateRequest`):**
```json
{
  "target": "sql",
  "row_counts": {
    "customers": 10,
    "orders": 25
  }
}
```

---

## 11. Autonomous Studio Agent Runs & SSE Streaming

### 1. `POST /api/v2/runs`
Initializes an autonomous studio agent run.

**Request Body (`RunCreateRequest`):**
```json
{
  "session_id": "sess_default",
  "connection_id": "conn_9a41b2c8",
  "mode": "ask",
  "effort": "medium",
  "message": "Which products generated the highest revenue?",
  "model_name": "llama3"
}
```

**Response (`200 OK`):**
```json
{
  "status": "success",
  "run_id": "run_e47b91a2",
  "mode": "ask",
  "tier": "dev"
}
```

---

### 2. `GET /api/v2/runs/{run_id}/events`
Streams typed, monotonic Server-Sent Events (SSE) representing the execution lifecycle.

**MIME Type:** `text/event-stream`

#### Stream Event Protocol:
```http
id: 1
event: run.started
data: {"run_id": "run_e47b91a2", "mode": "ask", "models": {"tool": "llama3"}, "budget": {"max_tool_calls": 25, "max_rows_read": 10000000, "time_budget_sec": 30}}

id: 2
event: step.started
data: {"step": 1, "node": "discovery"}

id: 3
event: tool.called
data: {"tool": "search_schema", "args": {"query": "revenue", "limit": 6}}

id: 4
event: tool.result
data: {"tool": "search_schema", "status": "success", "summary": "Found 2 matching tables: products, order_items", "duration_ms": 15}

id: 5
event: budget.updated
data: {"used": {"tool_calls": 2, "rows_read": 50}, "limits": {"max_tool_calls": 25}}

id: 6
event: run.completed
data: {"run_id": "run_e47b91a2", "status": "completed", "duration_ms": 284.5}
```

---

### 3. `GET /api/v2/runs/{run_id}`
Returns run status, metadata, and complete event history.

---

### 4. `POST /api/v2/runs/{run_id}/cancel`
Immediately interrupts and terminates an active agent run.

---

## 12. Model Capabilities & Cryptographic Audit Trail

### 1. `GET /api/v2/models/probe`
Probes candidate models for native tool-calling capabilities.

**Query Parameters:**
- `model`: Model name (e.g. `qwen3:4b`, `llama3`, `gpt-4o`).

---

### 2. `GET /api/v2/connections/{conn_id}/audit`
Retrieves the append-only SHA-256 hash-chained audit log and verifies cryptographic integrity.

**Response (`200 OK`):**
```json
{
  "status": "success",
  "audit_chain_valid": true,
  "verification_message": "Chain verified intact across 48 entries.",
  "entries": [
    {
      "seq": 48,
      "actor": "user",
      "action": "sql_execution",
      "prev_hash": "a4b1c2...",
      "entry_hash": "f89d3e...",
      "created_at": "2026-10-30T18:42:01Z",
      "detail": {"tables": ["orders"], "limit": 500}
    }
  ]
}
```

---

## 13. Client Integration Examples

### Python (`httpx`)
```python
import httpx

BASE_URL = "http://localhost:8001/api/v2"

# 1. Check SQL and acquire HMAC query token
check_res = httpx.post(f"{BASE_URL}/connections/conn_default/sql/check", json={
    "sql": "SELECT * FROM customers LIMIT 10",
    "enforce_limit": True
})
data = check_res.json()
token = data["query_token"]

# 2. Execute with token
run_res = httpx.post(f"{BASE_URL}/connections/conn_default/sql/run", json={
    "query_token": token,
    "page": 1,
    "page_size": 10
})
print(run_res.json()["rows"])
```

### JavaScript (`EventSource` SSE Stream)
```javascript
const eventSource = new EventSource('/api/v2/runs/run_e47b91a2/events');

eventSource.addEventListener('tool.called', (e) => {
  const data = JSON.parse(e.data);
  console.log(`Tool invoked: ${data.tool}`, data.args);
});

eventSource.addEventListener('run.completed', (e) => {
  console.log('Run finished successfully.');
  eventSource.close();
});
```
