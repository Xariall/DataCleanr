# Database — DataCleanr

**Engine:** SQLite 3, WAL mode
**Location:** `/data/datacleanr.db` (Railway persistent volume)
**Module:** `app/database.py`

---

## Schema

### Table: `users`

```sql
CREATE TABLE IF NOT EXISTS users (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    email                  TEXT UNIQUE NOT NULL,
    api_key_hash           TEXT UNIQUE NOT NULL,
    tier                   TEXT NOT NULL DEFAULT 'FREE',
    stripe_customer_id     TEXT,
    stripe_subscription_id TEXT,
    payment_failing        INTEGER NOT NULL DEFAULT 0,
    created_at             TEXT NOT NULL DEFAULT (datetime('now'))
);
```

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER | Auto-increment primary key |
| `email` | TEXT | Unique, lowercased at write time |
| `api_key_hash` | TEXT | `sha256(plaintext_key)` — unique |
| `tier` | TEXT | `'FREE'` or `'PAID'` |
| `stripe_customer_id` | TEXT | Set on `checkout.session.completed` |
| `stripe_subscription_id` | TEXT | Set on `checkout.session.completed` |
| `payment_failing` | INTEGER | `1` = invoice failed, awaiting retry. Does NOT downgrade tier. |
| `created_at` | TEXT | ISO 8601 datetime string |

### Table: `stripe_events`

```sql
CREATE TABLE IF NOT EXISTS stripe_events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id   TEXT UNIQUE NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
```

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER | Auto-increment |
| `event_id` | TEXT | Stripe event ID (`evt_...`), `UNIQUE` |
| `created_at` | TEXT | ISO 8601 datetime |

`INSERT OR IGNORE INTO stripe_events (event_id) VALUES (?)`
— guarantees idempotency for duplicate Stripe webhook deliveries.

---

## Initialization

Called at app startup via `lifespan()` in `app/main.py`:

```python
def init_db() -> None:
    with _connect() as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""CREATE TABLE IF NOT EXISTS users ...""")
        conn.execute("""CREATE TABLE IF NOT EXISTS stripe_events ...""")
```

WAL mode is set every connection via `PRAGMA journal_mode=WAL`. SQLite persists
this setting, so it only needs to be set once — but setting it on init is idempotent.

---

## Key Operations

### `create_user(email) -> str`

Generates `api_key = "dc_" + secrets.token_urlsafe(32)`, stores `sha256(api_key)`,
returns plaintext key. Raises `ValueError("Email already registered")` on duplicate.

### `get_user_by_key(api_key) -> dict | None`

Computes `sha256(api_key)`, looks up in `users`. Returns full user row as dict, or `None`.

### `upgrade_to_paid(email, customer_id, subscription_id)`

Sets `tier='PAID'`, stores Stripe IDs. Called on `checkout.session.completed`.

### `set_payment_failing(subscription_id, failing: bool)`

Sets `payment_failing=1` (failing=True) or `payment_failing=0` (failing=False).
**Does not change `tier`.** Called on `invoice.payment_failed` / `invoice.payment_succeeded`.

### `downgrade_to_free(subscription_id)`

Sets `tier='FREE'`. Called **only** on `customer.subscription.deleted`.

### `record_stripe_event(event_id) -> bool`

`INSERT OR IGNORE` into `stripe_events`. Returns `True` if new event, `False` if duplicate.

---

## Billing State Machine

```
              /register
                  │
                  ▼
              tier=FREE
              payment_failing=0
                  │
      checkout.session.completed
                  │
                  ▼
              tier=PAID
              payment_failing=0
                  │
      invoice.payment_failed          invoice.payment_succeeded
                  │                           │
                  ▼                           │
              tier=PAID  ◄───────────────────┘
              payment_failing=1
                  │
      customer.subscription.deleted
                  │
                  ▼
              tier=FREE
              payment_failing=0
```

---

## WAL Mode

`PRAGMA journal_mode=WAL` enables:
- **Concurrent reads** while a write is in progress (no read-lock contention)
- **Better write throughput** for low-to-medium concurrency
- Creates `.db-shm` and `.db-wal` sidecar files (excluded from git via `.gitignore`)

Railway volume persists all three files across redeploys.

---

## Backup (V1 — not implemented)

No automated backup in V1. If the Railway volume is deleted or corrupted,
all user data is lost.

**V2:** Set up a daily `sqlite3 .dump` export to S3 or Railway's backup feature.
