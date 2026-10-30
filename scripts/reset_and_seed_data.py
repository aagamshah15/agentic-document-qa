import os
import sqlite3
from datetime import datetime

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
DB_PATH = os.path.join(DATA_DIR, "chat_history.db")

def reset_and_seed():
    print(f"Connecting to {DB_PATH}...")
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 1. Clear old sessions and messages
    cursor.execute("DELETE FROM messages;")
    cursor.execute("DELETE FROM sessions;")
    conn.commit()
    print("Deleted all legacy document Q&A conversations.")

    # 2. Seed 3 Showcase Conversations
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Thread 1: E-Commerce Revenue Analysis
    s1_id = "session_ecommerce_revenue"
    cursor.execute(
        "INSERT INTO sessions (id, title, model, effort, pinned, archived, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (s1_id, "E-Commerce Revenue Analysis", "llama3", "medium", 1, 0, now, now)
    )
    cursor.execute(
        "INSERT INTO messages (session_id, role, content, sources, route, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (
            s1_id,
            "user",
            "Show me total revenue grouped by product category with order count",
            None,
            "local_context",
            now
        )
    )
    cursor.execute(
        "INSERT INTO messages (session_id, role, content, sources, route, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (
            s1_id,
            "assistant",
            """### Query Analysis (SQLITE)
Aggregates gross revenue and unique order count by product category across `products`, `order_items`, and `orders`.

```sql:executable
SELECT 
    p.category,
    COUNT(DISTINCT o.id) AS total_orders,
    ROUND(SUM(oi.quantity * oi.unit_price), 2) AS total_revenue
FROM products p
JOIN order_items oi ON p.id = oi.product_id
JOIN orders o ON oi.order_id = o.id
GROUP BY p.category
ORDER BY total_revenue DESC
LIMIT 5;
```

**Optimization Notes:**
- Target engine: `sqlite`.
- Bounded by `LIMIT 5` to avoid unnecessary memory overhead on large tables.
- Schema context utilized: `products`, `order_items`, `orders`.

<!-- suggestions: ["Filter by status = 'completed'", "Break down revenue by country", "Find top 10 customers by lifetime spend"] -->""",
            None,
            "local_context",
            now
        )
    )

    # Thread 2: Stock Price & Dimensions
    s2_id = "session_stock_dimensions"
    cursor.execute(
        "INSERT INTO sessions (id, title, model, effort, pinned, archived, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (s2_id, "Stock Volatility & Shape", "llama3", "medium", 0, 0, now, now)
    )
    cursor.execute(
        "INSERT INTO messages (session_id, role, content, sources, route, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (
            s2_id,
            "user",
            "Show me the shape of stock_market and the 5 days with highest closing price for AAPL",
            None,
            "local_context",
            now
        )
    )
    cursor.execute(
        "INSERT INTO messages (session_id, role, content, sources, route, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (
            s2_id,
            "assistant",
            """### Query Analysis (DUCKDB)
Dataset `stock_market` has a shape of **180 rows × 8 columns**.

```sql:executable
SELECT ticker, date, close, volume, balance
FROM stock_market
WHERE ticker = 'AAPL'
ORDER BY close DESC
LIMIT 5;
```

**Optimization Notes:**
- Target engine: `duckdb`.
- Bounded by `LIMIT 5` to avoid unnecessary memory overhead on large tables.
- Schema context utilized: `stock_market`.

<!-- suggestions: ["Show 30-day moving average volume for AAPL", "Compare MSFT vs GOOGL closing prices", "Find all negative balance records"] -->""",
            None,
            "local_context",
            now
        )
    )

    # Thread 3: Data Quality & PII Audit
    s3_id = "session_dirty_leads_audit"
    cursor.execute(
        "INSERT INTO sessions (id, title, model, effort, pinned, archived, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (s3_id, "Data Quality & PII Audit", "llama3", "medium", 0, 0, now, now)
    )
    cursor.execute(
        "INSERT INTO messages (session_id, role, content, sources, route, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (
            s3_id,
            "user",
            "Profile dirty_leads table for data quality anomalies and PII risks",
            None,
            "local_context",
            now
        )
    )
    cursor.execute(
        "INSERT INTO messages (session_id, role, content, sources, route, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (
            s3_id,
            "assistant",
            """### Table Hygiene & Anomaly Audit: `dirty_leads`

**Summary Metrics:**
- Total Rows: 50 | Total Columns: 7
- Overall Missing Value Rate: 16.2%

**Detected Anomalies (4):**
- 🚨 **CRITICAL (PII Risk)**: Column `credit_card` contains 50 live records matching Visa/Mastercard format with verified Luhn checksum. Masking required.
- 🚨 **CRITICAL (PII Risk)**: Column `ssn` contains 50 records matching Social Security Number formatting (`XXX-XX-XXXX`).
- ⚠️ **WARNING (Null Burst)**: Column `phone` has an **80.0% null rate** (40 missing records). Exceeds the 50% data completeness threshold.
- ⚠️ **WARNING (Duplicate Key)**: Detected 8 duplicate entries in candidate identifier `email` (`"ACME INC"`, `"acme inc"`).

<!-- suggestions: ["Generate safe deduplication recipe for email", "Mask credit card column with hashes", "Export cleaned records without PII"] -->""",
            None,
            "local_context",
            now
        )
    )

    conn.commit()
    conn.close()
    print("Successfully seeded 3 clean showcase conversations!")

if __name__ == "__main__":
    reset_and_seed()
