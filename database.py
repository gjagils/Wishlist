#!/usr/bin/env python3
"""
Database module voor wishlist applicatie.
SQLite database met wishlist items en logs.
"""
import sqlite3
import os
from datetime import datetime
from typing import List, Optional, Dict, Any
from contextlib import contextmanager

DB_PATH = os.environ.get("DB_PATH", "/data/wishlist.db")


@contextmanager
def get_db():
    """Context manager voor database connectie."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """Initialiseer database schema."""
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

def add_wishlist_item(author: str, title: str, added_via: str = "web") -> int:
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
            """INSERT INTO wishlist (author, title, raw_line, added_via)
               VALUES (?, ?, ?, ?)""",
            (author, title, raw_line, added_via)
        )
        item_id = cursor.lastrowid

        add_log(item_id, "info", f"Item toegevoegd via {added_via}")
        return item_id


def get_wishlist_items(status: Optional[str] = None) -> List[Dict[str, Any]]:
    """Haal wishlist items op, optioneel gefilterd op status."""
    with get_db() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM wishlist WHERE status = ? ORDER BY added_date DESC",
                (status,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM wishlist ORDER BY added_date DESC"
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

        log_msg = f"Status: {status}"
        if error_message:
            log_msg += f" - {error_message}"
        add_log(item_id, "info", log_msg)


def delete_wishlist_item(item_id: int) -> bool:
    """Verwijder item uit wishlist."""
    with get_db() as conn:
        cursor = conn.execute("DELETE FROM wishlist WHERE id = ?", (item_id,))
        deleted = cursor.rowcount > 0

        if deleted:
            # Ook logs verwijderen
            conn.execute("DELETE FROM logs WHERE wishlist_id = ?", (item_id,))

        return deleted


# ===== LOGS =====

def add_log(
    wishlist_id: Optional[int],
    level: str,
    message: str
) -> None:
    """Voeg log entry toe."""
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


def set_setting(key: str, value: str) -> None:
    """Sla setting op."""
    with get_db() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO settings (key, value)
               VALUES (?, ?)""",
            (key, value)
        )


if __name__ == "__main__":
    # Test database
    init_db()
    print("Database test OK")
