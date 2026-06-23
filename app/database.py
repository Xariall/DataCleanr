import hashlib
import os
import secrets
import sqlite3

DATABASE_PATH = os.getenv("DATABASE_PATH", "/data/datacleanr.db")


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    os.makedirs(os.path.dirname(os.path.abspath(DATABASE_PATH)), exist_ok=True)
    with _conn() as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id                    INTEGER PRIMARY KEY AUTOINCREMENT,
                email                 TEXT    UNIQUE NOT NULL,
                api_key_hash          TEXT    NOT NULL,
                tier                  TEXT    NOT NULL DEFAULT 'FREE',
                stripe_customer_id    TEXT,
                stripe_subscription_id TEXT,
                payment_failing       INTEGER NOT NULL DEFAULT 0,
                created_at            TEXT    NOT NULL DEFAULT (datetime('now'))
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS stripe_events (
                event_id     TEXT PRIMARY KEY,
                processed_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_users_key_hash ON users(api_key_hash)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_users_email    ON users(email)")
        conn.commit()


def hash_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode()).hexdigest()


def generate_api_key() -> str:
    return "dc_" + secrets.token_urlsafe(32)


def create_user(email: str) -> str:
    """Create a new free-tier user. Returns plaintext API key (shown once)."""
    api_key = generate_api_key()
    with _conn() as conn:
        try:
            conn.execute(
                "INSERT INTO users (email, api_key_hash) VALUES (?, ?)",
                (email, hash_key(api_key)),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            raise ValueError("Email already registered")
    return api_key


def rotate_api_key(user_id: int) -> str:
    """Generate a new API key for an existing user. Old key is immediately invalidated."""
    new_key = generate_api_key()
    with _conn() as conn:
        conn.execute(
            "UPDATE users SET api_key_hash = ? WHERE id = ?",
            (hash_key(new_key), user_id),
        )
        conn.commit()
    return new_key


def get_user_by_key_hash(key_hash: str) -> sqlite3.Row | None:
    with _conn() as conn:
        return conn.execute(
            "SELECT * FROM users WHERE api_key_hash = ?", (key_hash,)
        ).fetchone()


def get_user_by_email(email: str) -> sqlite3.Row | None:
    with _conn() as conn:
        return conn.execute(
            "SELECT * FROM users WHERE email = ?", (email,)
        ).fetchone()


def upgrade_to_paid(customer_id: str, subscription_id: str, email: str) -> None:
    with _conn() as conn:
        conn.execute(
            """UPDATE users
               SET tier = 'PAID',
                   stripe_customer_id     = ?,
                   stripe_subscription_id = ?,
                   payment_failing        = 0
               WHERE email = ?""",
            (customer_id, subscription_id, email),
        )
        conn.commit()


def set_payment_failing(subscription_id: str, failing: bool) -> None:
    """Set payment_failing flag; does NOT downgrade tier."""
    with _conn() as conn:
        conn.execute(
            "UPDATE users SET payment_failing = ? WHERE stripe_subscription_id = ?",
            (1 if failing else 0, subscription_id),
        )
        conn.commit()


def downgrade_to_free(subscription_id: str) -> None:
    """Called only on customer.subscription.deleted — hard downgrade to FREE."""
    with _conn() as conn:
        conn.execute(
            """UPDATE users
               SET tier = 'FREE',
                   stripe_subscription_id = NULL,
                   payment_failing        = 0
               WHERE stripe_subscription_id = ?""",
            (subscription_id,),
        )
        conn.commit()


def record_stripe_event(event_id: str) -> bool:
    """Idempotency guard. Returns True if the event is new, False if duplicate."""
    with _conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO stripe_events (event_id) VALUES (?)", (event_id,)
        )
        changed = conn.execute("SELECT changes()").fetchone()[0]
        conn.commit()
        return changed > 0
