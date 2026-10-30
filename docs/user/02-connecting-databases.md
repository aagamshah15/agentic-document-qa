# 02. Connecting Databases & Environment Tiers

Dimension isolates credentials, audits connection privileges, and strictly enforces environment safety policies to protect sensitive environments from unauthorized writes or data leaks.

---

## 1. Connecting a Database

Click **"Connect Database"** in the sidebar to open the connection modal, or invoke `POST /api/v2/connections`.

### Supported Dialects & Connection Formats

| Engine | DSN Format Example | Execution Profile |
| :--- | :--- | :--- |
| **PostgreSQL** | `postgresql://user:password@localhost:5432/analytics` | Uses `psycopg3` / SQLAlchemy with read-only transaction parameters and statement timeouts. |
| **MySQL** | `mysql+pymysql://root:password@localhost:3306/production` | Uses `pymysql` with session-level read-only mode (`SET SESSION TRANSACTION READ ONLY`). |
| **SQLite** | `data/sample_datasets/ecommerce.sqlite` or `sqlite:///mydb.db` | Runs with WAL journal mode, busy timeouts, and `PRAGMA foreign_keys=ON`. |
| **DuckDB** | `duckdb:///:memory:` or `duckdb:///data/analytics.duckdb` | High-performance in-process vectorized analytical engine. |

### Credential Vault Isolation

Passwords and secret keys are never written in plain text to disk or stored in the local SQLite metadata database:

```mermaid
flowchart TD
    User["User Enters Credentials"] --> DSN["DSN Parser"]
    DSN --> Vault["OS Secure Keychain (keyring)\nNamespace: 'dimension_studio'"]
    DSN --> AppDB["App DB (data/studio_app.db)\nStores: 'sec_7f9b1c0d' reference"]
    Vault -.->|Retrieved in-memory only on active session| Pool["SQLAlchemy Connection Pool"]
```

1. Passwords are sent to your operating system's native keychain (`keyring` on macOS Keychain, Windows Credential Manager, or Linux Secret Service) under the `dimension_studio` namespace.
2. Only an opaque, non-reversible secret reference key (e.g. `sec_7f9b1c0d`) is saved in `data/studio_app.db`.
3. Credentials are pulled into memory strictly when a database session is instantiated.

---

## 2. Environment Safety Tiers

Every registered connection belongs to an explicit **Deployment Tier** that governs agent row read limits, PII masking, and migration approval strictness:

| Tier | UI Badge | Purpose | Agent Read Row Limit | PII Masking | Migration Apply Policy |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Sandbox** | 🟢 Green | Local SQLite files, DuckDB, disposable Docker copies | 50,000,000 | On by default; can be disabled | One-click apply after shadow verification |
| **Dev / Staging** | 🟡 Amber | Shared development databases | 10,000,000 | **Locked ON** | Requires typed confirmation matching the connection name |
| **Prod** | 🔴 Red | Live customer production databases | 1,000,000 | **Locked ON** | **Strictly blocked (Decision D5)** — Export migration scripts only |

> [!IMPORTANT]
> **Production Safety Guarantee (Decision D5)**:
> Direct autonomous writes to `prod` connections are disabled by default. Proposals targeting production databases can only be exported as reviewed migration scripts (Alembic, Flyway, or raw SQL).

---

## 3. Privilege Grading

When a connection is established, Dimension inspects database privileges and assigns a letter grade:

- **Grade A (Optimal)**: The connection user has strictly `SELECT`-only privileges across all tables.
- **Grade B (Managed)**: The user has write grants, but Dimension enforces session-level read-only mode (`default_transaction_read_only = on` or `SET SESSION TRANSACTION READ ONLY`).
- **Grade C (Advisory Warning)**: The user has superuser/admin privileges. Dimension displays an advisory warning banner in the connection card.

---

## 4. Connection Management APIs

Programmatic connection management is exposed through the `/api/v2/connections` REST API:

- `POST /api/v2/connections`: Create a new connection with tier and credentials.
- `GET /api/v2/connections`: List all connections with status, tier, and engine.
- `POST /api/v2/connections/test`: Test connectivity without saving.
- `GET /api/v2/connections/{conn_id}/cloud-disclosure`: Audit the exact schema metadata disclosed to cloud LLMs.

---

## Navigation

- **Previous**: [01. Getting Started](file:///Users/aagam/Agentic%20Q%26A/docs/user/01-getting-started.md)
- **Next**: [03. Schema Cartography & ERD Navigation](file:///Users/aagam/Agentic%20Q%26A/docs/user/03-schema-cartography.md)
