#!/usr/bin/env python3
"""
Database module voor wishlist applicatie.
SQLite database met wishlist items en logs.
"""
import json
import sqlite3
import os
from datetime import datetime
from typing import List, Optional, Dict, Any
from contextlib import contextmanager

DB_PATH = os.environ.get("DB_PATH", "/data/wishlist.db")


@contextmanager
def get_db():
    """Context manager voor database connectie."""
    import sys

    try:
        # Gebruik timeout van 30 seconden voor locked database
        conn = sqlite3.connect(DB_PATH, timeout=30.0, isolation_level=None)
        conn.row_factory = sqlite3.Row

        # Enable Write-Ahead Logging voor betere concurrency
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")

        try:
            yield conn
            conn.commit()
        except sqlite3.OperationalError as e:
            print(f"[DB ERROR] SQLite error: {e}", file=sys.stderr)
            conn.rollback()
            raise
        except Exception as e:
            print(f"[DB ERROR] {type(e).__name__}: {e}", file=sys.stderr)
            conn.rollback()
            raise
    except sqlite3.OperationalError as e:
        print(f"[DB ERROR] Cannot connect: {e}", file=sys.stderr)
        raise
    finally:
        try:
            conn.close()
        except:
            pass


def init_db() -> None:
    """Initialiseer database schema."""
    # Zorg dat data directory bestaat met juiste permissions
    data_dir = os.path.dirname(DB_PATH)
    os.makedirs(data_dir, exist_ok=True)

    # Set permissions op data directory
    try:
        os.chmod(data_dir, 0o777)
    except Exception as e:
        print(f"Waarschuwing: Kon permissions niet zetten op {data_dir}: {e}")

    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS wishlist (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                author TEXT NOT NULL,
                title TEXT NOT NULL,
                raw_line TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                added_date TEXT DEFAULT CURRENT_TIMESTAMP,
                added_via TEXT DEFAULT 'manual',
                last_search TEXT,
                nzb_url TEXT,
                error_message TEXT
            );

            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                wishlist_id INTEGER,
                timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
                level TEXT,
                message TEXT,
                FOREIGN KEY (wishlist_id) REFERENCES wishlist(id)
            );

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_wishlist_status ON wishlist(status);
            CREATE INDEX IF NOT EXISTS idx_logs_wishlist ON logs(wishlist_id);
            CREATE INDEX IF NOT EXISTS idx_logs_timestamp ON logs(timestamp);
        """)

        # Migratie: voeg shelf kolommen toe indien nog niet aanwezig
        try:
            conn.execute("SELECT shelf_name FROM wishlist LIMIT 1")
        except sqlite3.OperationalError:
            conn.execute("ALTER TABLE wishlist ADD COLUMN shelf_name TEXT")
            print("Database migratie: shelf_name kolom toegevoegd")

        # Migratie: users tabel
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                email TEXT,
                role TEXT DEFAULT 'user',
                allowed_shelves TEXT,
                created_date TEXT DEFAULT CURRENT_TIMESTAMP,
                last_login TEXT
            )
        """)

        # Migratie: voeg user_id toe aan wishlist
        try:
            conn.execute("SELECT user_id FROM wishlist LIMIT 1")
        except sqlite3.OperationalError:
            conn.execute("ALTER TABLE wishlist ADD COLUMN user_id INTEGER REFERENCES users(id)")
            print("Database migratie: user_id kolom toegevoegd")

        # Seed admin user als users tabel leeg is
        admin_username = os.environ.get('WEB_USERNAME', 'admin')
        existing_admin = conn.execute(
            "SELECT id FROM users WHERE role = 'admin' LIMIT 1"
        ).fetchone()
        if not existing_admin:
            conn.execute(
                """INSERT OR IGNORE INTO users (username, role)
                   VALUES (?, 'admin')""",
                (admin_username,)
            )
            print(f"Admin user aangemaakt: {admin_username}")

        # Migratie: oude 'importing' status hernoemd naar 'found'
        # (found is nu altijd de wachtstatus, ongeacht boekenplank)
        conn.execute("UPDATE wishlist SET status = 'found' WHERE status = 'importing'")

    # Set permissions op database file en WAL files
    try:
        if os.path.exists(DB_PATH):
            os.chmod(DB_PATH, 0o666)
        if os.path.exists(DB_PATH + "-wal"):
            os.chmod(DB_PATH + "-wal", 0o666)
        if os.path.exists(DB_PATH + "-shm"):
            os.chmod(DB_PATH + "-shm", 0o666)
    except Exception as e:
        print(f"Waarschuwing: Kon permissions niet zetten op database files: {e}")

    print(f"Database geïnitialiseerd: {DB_PATH}")


def migrate_from_txt(txt_path: str) -> int:
    """Migreer items van wishlist.txt naar database."""
    if not os.path.exists(txt_path):
        print(f"Geen {txt_path} gevonden, skip migratie")
        return 0

    with open(txt_path, "r", encoding="utf-8") as f:
        lines = [
            line.strip()
            for line in f
            if line.strip() and not line.strip().startswith("#")
        ]

    if not lines:
        print("Wishlist.txt is leeg, skip migratie")
        return 0

    migrated = 0
    with get_db() as conn:
        for line in lines:
            # Parse: auteur - "titel"
            import re
            m = re.match(r'^(.*?)\s*-\s*"(.+)"\s*$', line)
            if not m:
                print(f"Skip ongeldige regel: {line}")
                continue

            author = m.group(1).strip()
            title = m.group(2).strip()

            # Check of al bestaat
            existing = conn.execute(
                "SELECT id FROM wishlist WHERE author = ? AND title = ?",
                (author, title)
            ).fetchone()

            if existing:
                print(f"Item al in database: {line}")
                continue

            conn.execute(
                """INSERT INTO wishlist (author, title, raw_line, added_via)
                   VALUES (?, ?, ?, 'migration')""",
                (author, title, line)
            )
            migrated += 1
            print(f"Gemigreerd: {line}")

    print(f"✓ {migrated} items gemigreerd van {txt_path}")
    return migrated


# ===== WISHLIST CRUD =====

def add_wishlist_item(author: str, title: str, added_via: str = "web",
                     shelf_name: Optional[str] = None,
                     user_id: Optional[int] = None) -> int:
    """Voeg nieuw item toe aan wishlist."""
    raw_line = f'{author} - "{title}"'

    with get_db() as conn:
        # Check duplicaat
        existing = conn.execute(
            "SELECT id FROM wishlist WHERE author = ? AND title = ?",
            (author, title)
        ).fetchone()

        if existing:
            raise ValueError(f"Item bestaat al: {raw_line}")

        cursor = conn.execute(
            """INSERT INTO wishlist (author, title, raw_line, added_via, shelf_name, user_id)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (author, title, raw_line, added_via, shelf_name, user_id)
        )
        item_id = cursor.lastrowid

        if is_logging_enabled():
            conn.execute(
                """INSERT INTO logs (wishlist_id, level, message)
                   VALUES (?, ?, ?)""",
                (item_id, "info", f"Item toegevoegd via {added_via}")
            )

        return item_id


def get_wishlist_items(status: Optional[str] = None,
                      user_id: Optional[int] = None) -> List[Dict[str, Any]]:
    """Haal wishlist items op, optioneel gefilterd op status en/of user_id."""
    with get_db() as conn:
        conditions = []
        params = []

        if status:
            conditions.append("w.status = ?")
            params.append(status)
        if user_id is not None:
            conditions.append("w.user_id = ?")
            params.append(user_id)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        rows = conn.execute(
            f"""SELECT w.*, u.username AS added_by
                FROM wishlist w
                LEFT JOIN users u ON w.user_id = u.id
                {where}
                ORDER BY w.added_date DESC""",
            params
        ).fetchall()

        return [dict(row) for row in rows]


def get_wishlist_item(item_id: int) -> Optional[Dict[str, Any]]:
    """Haal enkel item op."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM wishlist WHERE id = ?",
            (item_id,)
        ).fetchone()
        return dict(row) if row else None


def update_wishlist_status(
    item_id: int,
    status: str,
    nzb_url: Optional[str] = None,
    error_message: Optional[str] = None
) -> None:
    """Update status van wishlist item."""
    with get_db() as conn:
        now = datetime.now().isoformat()

        conn.execute(
            """UPDATE wishlist
               SET status = ?, last_search = ?, nzb_url = ?, error_message = ?
               WHERE id = ?""",
            (status, now, nzb_url, error_message, item_id)
        )

        if is_logging_enabled():
            log_msg = f"Status: {status}"
            if error_message:
                log_msg += f" - {error_message}"

            conn.execute(
                """INSERT INTO logs (wishlist_id, level, message)
                   VALUES (?, ?, ?)""",
                (item_id, "info", log_msg)
            )


def update_wishlist_item(item_id: int, author: Optional[str] = None,
                        title: Optional[str] = None,
                        shelf_name: Optional[str] = None) -> bool:
    """Update auteur, titel en/of plank van een wishlist item."""
    with get_db() as conn:
        updates = []
        params = []

        if author is not None:
            updates.append("author = ?")
            params.append(author)
        if title is not None:
            updates.append("title = ?")
            params.append(title)
        if shelf_name is not None:
            updates.append("shelf_name = ?")
            params.append(shelf_name if shelf_name else None)

        if not updates:
            return False

        # Update ook raw_line
        if author is not None or title is not None:
            # Haal huidige waarden op voor raw_line
            item = get_wishlist_item(item_id)
            if item:
                new_author = author if author is not None else item['author']
                new_title = title if title is not None else item['title']
                updates.append("raw_line = ?")
                params.append(f'{new_author} - "{new_title}"')

        params.append(item_id)
        cursor = conn.execute(
            f"UPDATE wishlist SET {', '.join(updates)} WHERE id = ?",
            params
        )

        if cursor.rowcount > 0 and is_logging_enabled():
            conn.execute(
                """INSERT INTO logs (wishlist_id, level, message)
                   VALUES (?, ?, ?)""",
                (item_id, "info", "Item bewerkt")
            )

        return cursor.rowcount > 0


def delete_wishlist_item(item_id: int) -> bool:
    """Verwijder item uit wishlist."""
    with get_db() as conn:
        cursor = conn.execute("DELETE FROM wishlist WHERE id = ?", (item_id,))
        deleted = cursor.rowcount > 0

        if deleted:
            # Ook logs verwijderen
            conn.execute("DELETE FROM logs WHERE wishlist_id = ?", (item_id,))

        return deleted


def bulk_delete_by_status(status: str) -> int:
    """Verwijder alle items met een specifieke status."""
    with get_db() as conn:
        # Haal eerst alle IDs op
        cursor = conn.execute("SELECT id FROM wishlist WHERE status = ?", (status,))
        item_ids = [row[0] for row in cursor.fetchall()]

        if not item_ids:
            return 0

        # Verwijder logs voor deze items
        placeholders = ','.join('?' * len(item_ids))
        conn.execute(f"DELETE FROM logs WHERE wishlist_id IN ({placeholders})", item_ids)

        # Verwijder de items zelf
        cursor = conn.execute("DELETE FROM wishlist WHERE status = ?", (status,))
        return cursor.rowcount


# ===== LOGS =====

def is_logging_enabled() -> bool:
    """Check of logging is ingeschakeld."""
    return get_setting('logging_enabled', 'true') == 'true'


def add_log(
    wishlist_id: Optional[int],
    level: str,
    message: str
) -> None:
    """Voeg log entry toe. Respecteert logging instelling (errors altijd)."""
    if level != 'error' and not is_logging_enabled():
        return

    with get_db() as conn:
        conn.execute(
            """INSERT INTO logs (wishlist_id, level, message)
               VALUES (?, ?, ?)""",
            (wishlist_id, level, message)
        )


def get_logs(
    wishlist_id: Optional[int] = None,
    limit: int = 100
) -> List[Dict[str, Any]]:
    """Haal logs op, optioneel gefilterd op wishlist_id."""
    with get_db() as conn:
        if wishlist_id is not None:
            rows = conn.execute(
                """SELECT * FROM logs
                   WHERE wishlist_id = ?
                   ORDER BY timestamp DESC
                   LIMIT ?""",
                (wishlist_id, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT l.*, w.author, w.title
                   FROM logs l
                   LEFT JOIN wishlist w ON l.wishlist_id = w.id
                   ORDER BY l.timestamp DESC
                   LIMIT ?""",
                (limit,)
            ).fetchall()

        return [dict(row) for row in rows]


# ===== SETTINGS =====

def get_setting(key: str, default: Optional[str] = None) -> Optional[str]:
    """Haal setting op."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE key = ?",
            (key,)
        ).fetchone()
        return row["value"] if row else default


def delete_settings_by_prefix(prefix: str) -> int:
    """Verwijder alle settings met een bepaald prefix."""
    with get_db() as conn:
        cursor = conn.execute(
            "DELETE FROM settings WHERE key LIKE ?",
            (f"{prefix}%",)
        )
        return cursor.rowcount


def set_setting(key: str, value: str) -> None:
    """Sla setting op."""
    with get_db() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO settings (key, value)
               VALUES (?, ?)""",
            (key, value)
        )


# ===== USERS =====

def create_user(username: str, email: Optional[str] = None,
                role: str = "user",
                allowed_shelves: Optional[List[str]] = None) -> int:
    """Maak nieuwe user aan of update bestaande."""
    shelves_json = json.dumps(allowed_shelves) if allowed_shelves else None
    with get_db() as conn:
        cursor = conn.execute(
            """INSERT INTO users (username, email, role, allowed_shelves)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(username) DO UPDATE SET
                   email = COALESCE(excluded.email, users.email),
                   role = excluded.role,
                   allowed_shelves = COALESCE(excluded.allowed_shelves, users.allowed_shelves)""",
            (username, email, role, shelves_json)
        )
        # Haal id op (werkt voor zowel insert als update)
        row = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
        return row["id"]


def get_user(username: str) -> Optional[Dict[str, Any]]:
    """Haal user op via username."""
    with get_db() as conn:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        if not row:
            return None
        user = dict(row)
        user["allowed_shelves"] = json.loads(user["allowed_shelves"]) if user["allowed_shelves"] else []
        return user


def get_user_by_id(user_id: int) -> Optional[Dict[str, Any]]:
    """Haal user op via id."""
    with get_db() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row:
            return None
        user = dict(row)
        user["allowed_shelves"] = json.loads(user["allowed_shelves"]) if user["allowed_shelves"] else []
        return user


def get_all_users() -> List[Dict[str, Any]]:
    """Haal alle users op."""
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM users ORDER BY created_date").fetchall()
        users = []
        for row in rows:
            user = dict(row)
            user["allowed_shelves"] = json.loads(user["allowed_shelves"]) if user["allowed_shelves"] else []
            users.append(user)
        return users


def update_user(user_id: int, email: Optional[str] = None,
                role: Optional[str] = None,
                allowed_shelves: Optional[List[str]] = None) -> bool:
    """Update user gegevens."""
    with get_db() as conn:
        updates = []
        params = []

        if email is not None:
            updates.append("email = ?")
            params.append(email)
        if role is not None:
            updates.append("role = ?")
            params.append(role)
        if allowed_shelves is not None:
            updates.append("allowed_shelves = ?")
            params.append(json.dumps(allowed_shelves))

        if not updates:
            return False

        params.append(user_id)
        cursor = conn.execute(
            f"UPDATE users SET {', '.join(updates)} WHERE id = ?",
            params
        )
        return cursor.rowcount > 0


def update_user_login(username: str) -> None:
    """Update last_login timestamp."""
    with get_db() as conn:
        conn.execute(
            "UPDATE users SET last_login = ? WHERE username = ?",
            (datetime.now().isoformat(), username)
        )


def delete_user(user_id: int) -> bool:
    """Verwijder user."""
    with get_db() as conn:
        cursor = conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        return cursor.rowcount > 0


def get_admin_users() -> List[Dict[str, Any]]:
    """Haal alle admin users op."""
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM users WHERE role = 'admin'").fetchall()
        users = []
        for row in rows:
            user = dict(row)
            user["allowed_shelves"] = json.loads(user["allowed_shelves"]) if user["allowed_shelves"] else []
            users.append(user)
        return users


if __name__ == "__main__":
    # Test database
    init_db()
    print("Database test OK")
