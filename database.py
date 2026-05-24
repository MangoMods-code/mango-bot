# database.py — All database logic for Mango Bot.

import aiosqlite
import config as cfg

DB_PATH = cfg.DB_PATH
VALID_TYPES = ("stock", "api", "aegis")


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA journal_mode = WAL")
        await db.execute("PRAGMA foreign_keys = OFF")

        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                discord_id   TEXT PRIMARY KEY,
                username     TEXT NOT NULL DEFAULT 'unknown',
                balance      INTEGER NOT NULL DEFAULT 0,
                is_seller    INTEGER NOT NULL DEFAULT 0,
                smb_balance  REAL NOT NULL DEFAULT 0.0,
                created_at   TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                name         TEXT NOT NULL UNIQUE,
                display_name TEXT NOT NULL,
                enabled      INTEGER NOT NULL DEFAULT 1,
                created_at   TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS variants (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id       INTEGER NOT NULL,
                name             TEXT NOT NULL,
                price            INTEGER NOT NULL DEFAULT 1,
                type             TEXT NOT NULL DEFAULT 'stock',
                api_url          TEXT,
                api_method       TEXT DEFAULT 'GET',
                api_headers      TEXT DEFAULT '{}',
                api_body         TEXT DEFAULT '{}',
                api_key_path     TEXT DEFAULT 'key',
                api_balance_url  TEXT,
                api_balance_path TEXT DEFAULT 'balance',
                aegis_category   INTEGER,
                aegis_service    INTEGER,
                enabled          INTEGER NOT NULL DEFAULT 1,
                created_at       TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
            )
        """)

        # Migrate variants table if it has an old CHECK constraint
        cursor = await db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='variants'")
        row = await cursor.fetchone()
        if row and "CHECK" in (row[0] or ""):
            await db.execute("""
                CREATE TABLE variants_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, product_id INTEGER NOT NULL,
                    name TEXT NOT NULL, price INTEGER NOT NULL DEFAULT 1, type TEXT NOT NULL DEFAULT 'stock',
                    api_url TEXT, api_method TEXT DEFAULT 'GET', api_headers TEXT DEFAULT '{}',
                    api_body TEXT DEFAULT '{}', api_key_path TEXT DEFAULT 'key',
                    api_balance_url TEXT, api_balance_path TEXT DEFAULT 'balance',
                    aegis_category INTEGER, aegis_service INTEGER, enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
                )
            """)
            await db.execute("""
                INSERT INTO variants_new (id, product_id, name, price, type, api_url, api_method,
                    api_headers, api_body, api_key_path, enabled, created_at)
                SELECT id, product_id, name, price, type, api_url, api_method,
                    api_headers, api_body, api_key_path, enabled, created_at FROM variants
            """)
            await db.execute("DROP TABLE variants")
            await db.execute("ALTER TABLE variants_new RENAME TO variants")
            print("  ✅ Migrated variants table")

        await db.execute("""
            CREATE TABLE IF NOT EXISTS stock (
                id INTEGER PRIMARY KEY AUTOINCREMENT, variant_id INTEGER NOT NULL,
                key_value TEXT NOT NULL, is_used INTEGER NOT NULL DEFAULT 0,
                added_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (variant_id) REFERENCES variants(id) ON DELETE CASCADE
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS keys (
                id INTEGER PRIMARY KEY AUTOINCREMENT, variant_id INTEGER NOT NULL,
                key_value TEXT NOT NULL, generated_by TEXT NOT NULL,
                generated_at TEXT NOT NULL DEFAULT (datetime('now')), is_banned INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (variant_id) REFERENCES variants(id) ON DELETE CASCADE,
                FOREIGN KEY (generated_by) REFERENCES users(discord_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY, value TEXT NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS smb_services (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                platform TEXT NOT NULL, category TEXT NOT NULL,
                service_id INTEGER NOT NULL UNIQUE, name TEXT NOT NULL,
                min_qty INTEGER NOT NULL DEFAULT 1, max_qty INTEGER NOT NULL DEFAULT 10000,
                rate TEXT NOT NULL DEFAULT '0.00', buyer_rate TEXT NOT NULL DEFAULT '',
                link_hint TEXT NOT NULL DEFAULT '', enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS smb_orders (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id      TEXT NOT NULL,
                smb_order_id TEXT NOT NULL,
                service_id   INTEGER NOT NULL,
                service_name TEXT NOT NULL,
                platform     TEXT NOT NULL,
                link         TEXT NOT NULL,
                quantity     INTEGER NOT NULL,
                buyer_cost   REAL NOT NULL DEFAULT 0.0,
                actual_cost  REAL NOT NULL DEFAULT 0.0,
                status       TEXT NOT NULL DEFAULT 'Processing',
                created_at   TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (user_id) REFERENCES users(discord_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS smb_platform_notes (
                platform TEXT PRIMARY KEY,
                notes    TEXT NOT NULL DEFAULT ''
            )
        """)

        # Column migrations
        for col, definition in [
            ("api_balance_url",  "TEXT"),
            ("api_balance_path", "TEXT DEFAULT 'balance'"),
            ("aegis_category",   "INTEGER"),
            ("aegis_service",    "INTEGER"),
        ]:
            try:
                await db.execute(f"ALTER TABLE variants ADD COLUMN {col} {definition}")
            except Exception:
                pass

        for col, definition in [
            ("link_hint",  "TEXT NOT NULL DEFAULT ''"),
            ("buyer_rate", "TEXT NOT NULL DEFAULT ''"),
        ]:
            try:
                await db.execute(f"ALTER TABLE smb_services ADD COLUMN {col} {definition}")
            except Exception:
                pass

        # Add smb_balance to users if not present
        try:
            await db.execute("ALTER TABLE users ADD COLUMN smb_balance REAL NOT NULL DEFAULT 0.0")
        except Exception:
            pass

        await db.execute("PRAGMA foreign_keys = ON")
        await db.commit()


# ═══════════════════════════════════════════════════════════════════════════════
# SETTINGS
# ═══════════════════════════════════════════════════════════════════════════════

async def get_setting(key, default="0"):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = await cursor.fetchone()
        return row[0] if row else default

async def set_setting(key, value):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = ?", (key, value, value))
        await db.commit()

async def is_maintenance():
    return (await get_setting("maintenance", "0")) == "1"

async def set_maintenance(enabled):
    await set_setting("maintenance", "1" if enabled else "0")

async def get_all_buyer_groups():
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT key, value FROM settings WHERE key LIKE 'buyergroup_%' AND value != '' ORDER BY key")
        rows = await cursor.fetchall()
    return [{"name": k[len("buyergroup_"):].title(), "link": v} for k, v in rows]


# ═══════════════════════════════════════════════════════════════════════════════
# USER HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

async def ensure_user(discord_id, username="unknown"):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM users WHERE discord_id = ?", (discord_id,))
        row = await cursor.fetchone()
        if row:
            if username and dict(row)["username"] != username:
                await db.execute("UPDATE users SET username = ? WHERE discord_id = ?", (username, discord_id))
                await db.commit()
            cursor = await db.execute("SELECT * FROM users WHERE discord_id = ?", (discord_id,))
            return dict(await cursor.fetchone())
        await db.execute("INSERT INTO users (discord_id, username) VALUES (?, ?)", (discord_id, username))
        await db.commit()
        cursor = await db.execute("SELECT * FROM users WHERE discord_id = ?", (discord_id,))
        return dict(await cursor.fetchone())

async def get_user(discord_id):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM users WHERE discord_id = ?", (discord_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None

async def get_all_users():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM users ORDER BY created_at DESC")
        return [dict(r) for r in await cursor.fetchall()]

async def get_all_sellers():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM users WHERE is_seller = 1 ORDER BY username")
        return [dict(r) for r in await cursor.fetchall()]

async def set_seller_status(discord_id, is_seller):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET is_seller = ? WHERE discord_id = ?", (1 if is_seller else 0, discord_id))
        await db.commit()

async def set_balance(discord_id, amount):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET balance = ? WHERE discord_id = ?", (amount, discord_id))
        await db.commit()

async def add_balance(discord_id, amount):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET balance = balance + ? WHERE discord_id = ?", (amount, discord_id))
        await db.commit()

async def subtract_balance(discord_id, amount):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET balance = balance - ? WHERE discord_id = ?", (amount, discord_id))
        await db.commit()

async def reset_balance(discord_id):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET balance = 0 WHERE discord_id = ?", (discord_id,))
        await db.commit()

# SMB balance helpers
async def smb_get_user_balance(discord_id: str) -> float:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT smb_balance FROM users WHERE discord_id = ?", (discord_id,))
        row = await cursor.fetchone()
        return float(row[0]) if row else 0.0

async def smb_add_user_balance(discord_id: str, amount: float):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET smb_balance = smb_balance + ? WHERE discord_id = ?", (amount, discord_id))
        await db.commit()

async def smb_set_user_balance(discord_id: str, amount: float):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET smb_balance = ? WHERE discord_id = ?", (amount, discord_id))
        await db.commit()

async def smb_subtract_user_balance(discord_id: str, amount: float):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET smb_balance = smb_balance - ? WHERE discord_id = ?", (amount, discord_id))
        await db.commit()


# ═══════════════════════════════════════════════════════════════════════════════
# PRODUCT / VARIANT / STOCK / KEY HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

async def add_product(display_name):
    slug = display_name.lower().replace(" ", "-")
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("INSERT INTO products (name, display_name) VALUES (?, ?)", (slug, display_name))
        await db.commit()
        cursor = await db.execute("SELECT * FROM products WHERE name = ?", (slug,))
        return dict(await cursor.fetchone())

async def remove_product(product_id):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM products WHERE id = ?", (product_id,))
        await db.commit()

async def get_product(product_id):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM products WHERE id = ?", (product_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None

async def get_product_by_name(name):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM products WHERE name = ? OR display_name = ?", (name, name))
        row = await cursor.fetchone()
        return dict(row) if row else None

async def get_all_products():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM products ORDER BY display_name")
        return [dict(r) for r in await cursor.fetchall()]

async def set_product_enabled(product_id, enabled):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE products SET enabled = ? WHERE id = ?", (1 if enabled else 0, product_id))
        await db.commit()

async def add_variant(product_id, name, price, vtype):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("INSERT INTO variants (product_id, name, price, type) VALUES (?, ?, ?, ?)", (product_id, name, price, vtype))
        await db.commit()
        cursor = await db.execute("SELECT * FROM variants WHERE rowid = last_insert_rowid()")
        return dict(await cursor.fetchone())

async def remove_variant(variant_id):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM variants WHERE id = ?", (variant_id,))
        await db.commit()

async def get_variant(variant_id):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT v.*, p.display_name as product_name FROM variants v
            JOIN products p ON v.product_id = p.id WHERE v.id = ?
        """, (variant_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None

async def get_variants_for_product(product_id):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM variants WHERE product_id = ? ORDER BY price ASC", (product_id,))
        return [dict(r) for r in await cursor.fetchall()]

async def get_all_enabled_variants():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT v.*, p.display_name as product_name FROM variants v
            JOIN products p ON v.product_id = p.id
            WHERE v.enabled = 1 AND p.enabled = 1 ORDER BY p.display_name, v.price ASC
        """)
        return [dict(r) for r in await cursor.fetchall()]

async def get_all_api_variants():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT v.*, p.display_name as product_name FROM variants v
            JOIN products p ON v.product_id = p.id
            WHERE v.type = 'api' AND v.api_balance_url IS NOT NULL AND v.api_balance_url != ''
            ORDER BY p.display_name, v.name
        """)
        return [dict(r) for r in await cursor.fetchall()]

async def set_variant_price(variant_id, price):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE variants SET price = ? WHERE id = ?", (price, variant_id))
        await db.commit()

async def set_variant_enabled(variant_id, enabled):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE variants SET enabled = ? WHERE id = ?", (1 if enabled else 0, variant_id))
        await db.commit()

async def update_variant_api(variant_id, api_url, api_method, api_headers, api_body, api_key_path):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE variants SET api_url=?, api_method=?, api_headers=?, api_body=?, api_key_path=? WHERE id=?",
                         (api_url, api_method, api_headers, api_body, api_key_path, variant_id))
        await db.commit()

async def update_variant_balance_check(variant_id, balance_url, balance_path):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE variants SET api_balance_url=?, api_balance_path=? WHERE id=?", (balance_url, balance_path, variant_id))
        await db.commit()

async def update_variant_aegis(variant_id, category, service):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE variants SET aegis_category=?, aegis_service=? WHERE id=?", (category, service, variant_id))
        await db.commit()

async def add_stock_keys(variant_id, keys):
    async with aiosqlite.connect(DB_PATH) as db:
        for key in keys:
            await db.execute("INSERT INTO stock (variant_id, key_value) VALUES (?, ?)", (variant_id, key.strip()))
        await db.commit()
    return len(keys)

async def get_next_stock_key(variant_id):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM stock WHERE variant_id = ? AND is_used = 0 ORDER BY id ASC LIMIT 1", (variant_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None

async def mark_stock_used(stock_id):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE stock SET is_used = 1 WHERE id = ?", (stock_id,))
        await db.commit()

async def get_stock_count(variant_id):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT COUNT(*) FROM stock WHERE variant_id = ? AND is_used = 0", (variant_id,))
        row = await cursor.fetchone()
        return row[0] if row else 0

async def get_all_stock_counts():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT v.id, v.name as variant_name, v.type, v.price, v.enabled,
                   p.display_name as product_name, p.id as product_id,
                   (SELECT COUNT(*) FROM stock s WHERE s.variant_id = v.id AND s.is_used = 0) as remaining
            FROM variants v JOIN products p ON v.product_id = p.id
            WHERE p.enabled = 1 ORDER BY p.display_name, v.price ASC
        """)
        return [dict(r) for r in await cursor.fetchall()]

async def record_key(variant_id, key_value, generated_by):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("INSERT INTO keys (variant_id, key_value, generated_by) VALUES (?, ?, ?)", (variant_id, key_value, generated_by))
        await db.commit()
        cursor = await db.execute("SELECT * FROM keys WHERE rowid = last_insert_rowid()")
        return dict(await cursor.fetchone())

async def get_keys_by_user(discord_id):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT k.*, v.name as variant_name, p.display_name as product_name
            FROM keys k JOIN variants v ON k.variant_id = v.id JOIN products p ON v.product_id = p.id
            WHERE k.generated_by = ? ORDER BY k.generated_at DESC
        """, (discord_id,))
        return [dict(r) for r in await cursor.fetchall()]

async def get_key_by_id(key_id):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT k.*, v.name as variant_name, p.display_name as product_name
            FROM keys k JOIN variants v ON k.variant_id = v.id JOIN products p ON v.product_id = p.id
            WHERE k.id = ?
        """, (key_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None

async def get_key_by_value(key_value):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT k.*, v.name as variant_name, p.display_name as product_name
            FROM keys k JOIN variants v ON k.variant_id = v.id JOIN products p ON v.product_id = p.id
            WHERE k.key_value = ?
        """, (key_value,))
        row = await cursor.fetchone()
        return dict(row) if row else None

async def ban_key(key_id):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE keys SET is_banned = 1 WHERE id = ?", (key_id,))
        await db.commit()

async def unban_key(key_id):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE keys SET is_banned = 0 WHERE id = ?", (key_id,))
        await db.commit()

async def remove_key(key_id):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM keys WHERE id = ?", (key_id,))
        await db.commit()

async def clear_all_keys():
    async with aiosqlite.connect(DB_PATH) as db:
        count_cursor = await db.execute("SELECT COUNT(*) FROM keys")
        count = (await count_cursor.fetchone())[0]
        await db.execute("DELETE FROM keys")
        await db.commit()
        return count


# ═══════════════════════════════════════════════════════════════════════════════
# SMB SERVICES
# ═══════════════════════════════════════════════════════════════════════════════

async def smb_add_service(platform, category, service_id, name, min_qty, max_qty, rate, link_hint="", buyer_rate=""):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("""
            INSERT INTO smb_services (platform, category, service_id, name, min_qty, max_qty, rate, link_hint, buyer_rate)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(service_id) DO UPDATE SET
                platform=excluded.platform, category=excluded.category, name=excluded.name,
                min_qty=excluded.min_qty, max_qty=excluded.max_qty, rate=excluded.rate,
                link_hint=excluded.link_hint, buyer_rate=excluded.buyer_rate
        """, (platform, category, service_id, name, min_qty, max_qty, rate, link_hint, buyer_rate))
        await db.commit()
        cursor = await db.execute("SELECT * FROM smb_services WHERE service_id = ?", (service_id,))
        return dict(await cursor.fetchone())

async def smb_edit_service(service_id: int, **kwargs):
    """Edit any fields on a service. Only updates fields that are passed."""
    allowed = {"platform", "category", "name", "min_qty", "max_qty", "rate", "buyer_rate", "link_hint", "enabled"}
    updates = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
    if not updates:
        return
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [service_id]
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(f"UPDATE smb_services SET {set_clause} WHERE service_id = ?", values)
        await db.commit()

async def smb_remove_service(service_id):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM smb_services WHERE service_id = ?", (service_id,))
        await db.commit()

async def smb_get_service(service_id):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM smb_services WHERE service_id = ?", (service_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None

async def smb_get_platforms():
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT DISTINCT platform FROM smb_services WHERE enabled = 1 ORDER BY platform")
        return [r[0] for r in await cursor.fetchall()]

async def smb_get_all_categories():
    """Return all distinct categories across all platforms."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT DISTINCT platform, category FROM smb_services ORDER BY platform, category")
        return [{"platform": r[0], "category": r[1]} for r in await cursor.fetchall()]

async def smb_get_categories_for_platform(platform: str):
    """Return distinct categories for a given platform (for autocomplete)."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT DISTINCT category FROM smb_services WHERE platform = ? ORDER BY category", (platform,))
        return [r[0] for r in await cursor.fetchall()]

async def smb_get_categories(platform):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT DISTINCT category FROM smb_services WHERE platform = ? AND enabled = 1 ORDER BY category", (platform,))
        return [r[0] for r in await cursor.fetchall()]

async def smb_get_services(platform, category):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM smb_services WHERE platform = ? AND category = ? AND enabled = 1 ORDER BY name", (platform, category))
        return [dict(r) for r in await cursor.fetchall()]

async def smb_get_all_services():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM smb_services ORDER BY platform, category, name")
        return [dict(r) for r in await cursor.fetchall()]

async def smb_set_enabled(service_id, enabled):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE smb_services SET enabled = ? WHERE service_id = ?", (1 if enabled else 0, service_id))
        await db.commit()


# ═══════════════════════════════════════════════════════════════════════════════
# SMB ORDERS
# ═══════════════════════════════════════════════════════════════════════════════

async def smb_record_order(user_id: str, smb_order_id: str, service_id: int, service_name: str,
                           platform: str, link: str, quantity: int, buyer_cost: float, actual_cost: float):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("""
            INSERT INTO smb_orders (user_id, smb_order_id, service_id, service_name, platform, link, quantity, buyer_cost, actual_cost)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (user_id, smb_order_id, service_id, service_name, platform, link, quantity, buyer_cost, actual_cost))
        await db.commit()

async def smb_get_user_orders(discord_id: str) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM smb_orders WHERE user_id = ? ORDER BY created_at DESC LIMIT 50", (discord_id,)
        )
        return [dict(r) for r in await cursor.fetchall()]

async def smb_get_all_orders() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM smb_orders ORDER BY created_at DESC LIMIT 100")
        return [dict(r) for r in await cursor.fetchall()]

async def smb_update_order_status(smb_order_id: str, status: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE smb_orders SET status = ? WHERE smb_order_id = ?", (status, smb_order_id))
        await db.commit()


# ═══════════════════════════════════════════════════════════════════════════════
# SMB PLATFORM NOTES
# ═══════════════════════════════════════════════════════════════════════════════

async def smb_set_platform_notes(platform: str, notes: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO smb_platform_notes (platform, notes) VALUES (?, ?) ON CONFLICT(platform) DO UPDATE SET notes = excluded.notes",
            (platform, notes)
        )
        await db.commit()

async def smb_get_platform_notes(platform: str) -> str:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("SELECT notes FROM smb_platform_notes WHERE platform = ?", (platform,))
        row = await cursor.fetchone()
        return row[0] if row else ""







