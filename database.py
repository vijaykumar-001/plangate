import sqlite3
import hashlib
from datetime import datetime, timezone

DB_FILE = "plangate.db"

def hash_api_key(raw_key: str) -> str:
    """Hash API keys using SHA-256 so plain-text keys are never stored."""
    return hashlib.sha256(raw_key.strip().encode("utf-8")).hexdigest()

def get_connection():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_connection()
    cur = conn.cursor()

    # Customers table (stores hashed API keys only)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS customers (
            customer_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            plan_name TEXT NOT NULL,
            api_key_hash TEXT UNIQUE NOT NULL
        )
    """)

    # Monthly usage counters per customer and endpoint
    cur.execute("""
        CREATE TABLE IF NOT EXISTS usage_counters (
            customer_id TEXT NOT NULL,
            endpoint TEXT NOT NULL,
            period TEXT NOT NULL,
            usage_count INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (customer_id, endpoint, period)
        )
    """)

    # Audit log for every gateway decision
    cur.execute("""
        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            customer_id TEXT NOT NULL,
            plan_name TEXT NOT NULL,
            endpoint TEXT NOT NULL,
            decision TEXT NOT NULL,
            reason TEXT NOT NULL,
            current_usage INTEGER NOT NULL,
            limit_value INTEGER NOT NULL
        )
    """)

    # Seed two demo customers:
    # Free Customer Key: pg_free_key_123
    # Pro Customer Key:  pg_pro_key_999
    seed_customers = [
        ("cust_free_01", "Acme Startup (Free)", "Free", hash_api_key("pg_free_key_123")),
        ("cust_pro_02", "Enterprise Corp (Pro)", "Pro", hash_api_key("pg_pro_key_999")),
    ]
    cur.executemany("""
        INSERT OR IGNORE INTO customers (customer_id, name, plan_name, api_key_hash)
        VALUES (?, ?, ?, ?)
    """, seed_customers)

    conn.commit()
    conn.close()

def get_current_period() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")

def get_customer_by_api_key(raw_key: str):
    if not raw_key:
        return None
    key_hash = hash_api_key(raw_key)
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM customers WHERE api_key_hash = ?", (key_hash,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None

def get_usage(customer_id: str, endpoint: str) -> int:
    period = get_current_period()
    conn = get_connection()
    row = conn.execute(
        "SELECT usage_count FROM usage_counters WHERE customer_id = ? AND endpoint = ? AND period = ?",
        (customer_id, endpoint, period)
    ).fetchone()
    conn.close()
    return row["usage_count"] if row else 0

def increment_usage(customer_id: str, endpoint: str) -> int:
    period = get_current_period()
    conn = get_connection()
    conn.execute("""
        INSERT INTO usage_counters (customer_id, endpoint, period, usage_count)
        VALUES (?, ?, ?, 1)
        ON CONFLICT(customer_id, endpoint, period)
        DO UPDATE SET usage_count = usage_count + 1
    """, (customer_id, endpoint, period))
    conn.commit()
    new_count = get_usage(customer_id, endpoint)
    conn.close()
    return new_count

def log_decision(customer_id: str, plan_name: str, endpoint: str, decision: str, reason: str, current_usage: int, limit_value: int):
    conn = get_connection()
    conn.execute("""
        INSERT INTO audit_logs (timestamp, customer_id, plan_name, endpoint, decision, reason, current_usage, limit_value)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        datetime.now(timezone.utc).isoformat(),
        customer_id,
        plan_name,
        endpoint,
        decision,
        reason,
        current_usage,
        limit_value
    ))
    conn.commit()
    conn.close()

def get_recent_logs(limit: int = 25):
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM audit_logs ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def reset_all_usage():
    """Helper to reset counters during live jury demo."""
    conn = get_connection()
    conn.execute("DELETE FROM usage_counters")
    conn.execute("DELETE FROM audit_logs")
    conn.commit()
    conn.close()