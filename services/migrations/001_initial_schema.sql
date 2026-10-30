-- Migration 001: Autonomous Data & Schema Studio Initial App Database Schema
-- Standard SQLite 3 DDL with workspace isolation and monotonic sequencing.

CREATE TABLE IF NOT EXISTS schema_versions (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    applied_at TEXT NOT NULL DEFAULT (datetime('now', 'utc'))
);

-- Connections: registered databases and files
CREATE TABLE IF NOT EXISTS connections (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL DEFAULT 'default',
    name TEXT NOT NULL,
    engine TEXT NOT NULL,                    -- postgresql, sqlite, duckdb, mysql
    tier TEXT NOT NULL DEFAULT 'sandbox',    -- sandbox, dev, prod
    dsn_template TEXT NOT NULL,              -- host/db without secret credentials
    secret_ref TEXT,                         -- keyring reference or env var key
    options_json TEXT DEFAULT '{}',
    privilege_grade TEXT DEFAULT 'B',        -- A (SELECT only), B (session read-only), C (superuser)
    cloud_models_allowed INTEGER NOT NULL DEFAULT 0,
    masking_enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'utc')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now', 'utc'))
);

-- Schema Snapshots: versioned snapshots of database schemas
CREATE TABLE IF NOT EXISTS schema_snapshots (
    id TEXT PRIMARY KEY,
    connection_id TEXT NOT NULL,
    content_hash TEXT NOT NULL,              -- SHA-256 of normalized schema JSON
    server_version TEXT,
    structure_json TEXT NOT NULL,
    table_count INTEGER NOT NULL DEFAULT 0,
    column_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'utc')),
    source TEXT NOT NULL DEFAULT 'refresh',  -- connect, refresh, post_migration, shadow
    FOREIGN KEY (connection_id) REFERENCES connections(id) ON DELETE CASCADE
);

-- Column Profiles: statistical analysis and PII metadata
CREATE TABLE IF NOT EXISTS column_profiles (
    id TEXT PRIMARY KEY,
    snapshot_id TEXT NOT NULL,
    table_name TEXT NOT NULL,
    column_name TEXT NOT NULL,
    stats_json TEXT NOT NULL,
    sample_fraction REAL NOT NULL DEFAULT 1.0,
    exact INTEGER NOT NULL DEFAULT 1,
    computed_at TEXT NOT NULL DEFAULT (datetime('now', 'utc')),
    FOREIGN KEY (snapshot_id) REFERENCES schema_snapshots(id) ON DELETE CASCADE
);

-- Relationship Inferences: heuristic foreign key links
CREATE TABLE IF NOT EXISTS relationship_inferences (
    id TEXT PRIMARY KEY,
    snapshot_id TEXT NOT NULL,
    child_table TEXT NOT NULL,
    child_column TEXT NOT NULL,
    parent_table TEXT NOT NULL,
    parent_column TEXT NOT NULL,
    score REAL NOT NULL,
    containment REAL NOT NULL,
    name_score REAL NOT NULL,
    type_score REAL NOT NULL,
    cardinality REAL NOT NULL,
    evidence_query TEXT,
    status TEXT NOT NULL DEFAULT 'proposed', -- proposed, confirmed, rejected
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'utc')),
    FOREIGN KEY (snapshot_id) REFERENCES schema_snapshots(id) ON DELETE CASCADE
);

-- Glossary Entries: schema memory flywheel (confirmed terms, rules, enum meanings)
CREATE TABLE IF NOT EXISTS glossary_entries (
    id TEXT PRIMARY KEY,
    connection_id TEXT NOT NULL,
    target_kind TEXT NOT NULL,               -- table, column, relationship
    target TEXT NOT NULL,                    -- qualified object name e.g. orders.status
    kind TEXT NOT NULL,                      -- description, enum_map, join_rule, filter_rule, caveat, synonym
    body TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'suggested',-- suggested, confirmed, rejected, needs_review
    author_kind TEXT NOT NULL DEFAULT 'agent', -- user, agent
    author_ref TEXT,
    snapshot_id TEXT,
    evidence_json TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'utc')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now', 'utc')),
    FOREIGN KEY (connection_id) REFERENCES connections(id) ON DELETE CASCADE
);

-- Findings: data hygiene and structural issues
CREATE TABLE IF NOT EXISTS findings (
    id TEXT PRIMARY KEY,
    connection_id TEXT NOT NULL,
    kind TEXT NOT NULL,                      -- mixed_dates, sentinels, orphans, unindexed_fk, pii
    severity TEXT NOT NULL DEFAULT 'warning',-- info, warning, error, critical
    target TEXT NOT NULL,                    -- table or column name
    summary TEXT NOT NULL,
    evidence_json TEXT,
    fix_json TEXT,
    status TEXT NOT NULL DEFAULT 'open',     -- open, accepted, dismissed, snoozed
    dismiss_reason TEXT,
    fingerprint TEXT NOT NULL,               -- stable hash to avoid duplicate findings
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'utc')),
    FOREIGN KEY (connection_id) REFERENCES connections(id) ON DELETE CASCADE
);

-- Runs: agent task lifecycle records
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    connection_id TEXT,
    mode TEXT NOT NULL DEFAULT 'ask',        -- explore, ask, change, seed
    effort TEXT NOT NULL DEFAULT 'medium',   -- low, medium, high
    tier_at_start TEXT NOT NULL DEFAULT 'sandbox',
    models_json TEXT DEFAULT '{}',
    budget_json TEXT DEFAULT '{}',
    usage_json TEXT DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'running',  -- running, awaiting_approval, completed, failed, cancelled, interrupted
    stop_reason TEXT,
    prompt_version TEXT DEFAULT 'v2.0',
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'utc')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now', 'utc'))
);

-- Run Events: typed SSE event sequence
CREATE TABLE IF NOT EXISTS run_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'utc')),
    FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_run_events_run_seq ON run_events(run_id, seq);

-- Tool Calls: bounded audit of individual tool invocations
CREATE TABLE IF NOT EXISTS tool_calls (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    tool TEXT NOT NULL,
    args_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'ok',       -- ok, error, cancelled
    result_summary TEXT,
    rows_read INTEGER DEFAULT 0,
    bytes_to_model INTEGER DEFAULT 0,
    duration_ms INTEGER DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'utc')),
    FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE
);

-- Migration Proposals: proposed schema modifications
CREATE TABLE IF NOT EXISTS migration_proposals (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    connection_id TEXT NOT NULL,
    goal TEXT NOT NULL,
    up_sql TEXT NOT NULL,
    down_sql TEXT NOT NULL,
    base_snapshot_id TEXT,
    lint_json TEXT DEFAULT '{}',
    impact_json TEXT DEFAULT '{}',
    shadow_json TEXT DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'draft',    -- draft, verified, failed, approved, applied, exported, rejected
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'utc')),
    FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE,
    FOREIGN KEY (connection_id) REFERENCES connections(id) ON DELETE CASCADE
);

-- Approvals: human approval decisions for write operations
CREATE TABLE IF NOT EXISTS approvals (
    id TEXT PRIMARY KEY,
    proposal_id TEXT NOT NULL,
    decision TEXT NOT NULL,                  -- approved, rejected, changes_requested
    approver TEXT NOT NULL DEFAULT 'local_user',
    typed_confirmation TEXT,
    comment TEXT,
    decided_at TEXT NOT NULL DEFAULT (datetime('now', 'utc')),
    FOREIGN KEY (proposal_id) REFERENCES migration_proposals(id) ON DELETE CASCADE
);

-- Audit Entries: cryptographic hash-chained immutable audit log
CREATE TABLE IF NOT EXISTS audit_entries (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    prev_hash TEXT NOT NULL,
    hash TEXT NOT NULL,
    workspace_id TEXT NOT NULL DEFAULT 'default',
    connection_id TEXT,
    run_id TEXT,
    actor TEXT NOT NULL DEFAULT 'user',
    action TEXT NOT NULL,
    detail_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'utc'))
);

CREATE INDEX IF NOT EXISTS idx_audit_conn ON audit_entries(connection_id);
