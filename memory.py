"""Durable facts and notes in SQLite; recent conversation stays in RAM only."""
import sqlite3
import time
from collections import deque
from contextlib import contextmanager

from config import MEMORY_DB

# Short-term context helps follow a conversation but disappears on restart.
_session_history = deque(maxlen=40)


@contextmanager
def _conn():
    conn = sqlite3.connect(MEMORY_DB)
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS facts (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute("CREATE TABLE IF NOT EXISTS notes (id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT, created REAL)")
        # Remove legacy transcripts: ordinary conversation is no longer durable memory.
        conn.execute("DROP TABLE IF EXISTS history")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def remember(key, value):
    """Store a fact, e.g. remember('sat date', 'December 5')."""
    with _conn() as c:
        c.execute(
            "INSERT INTO facts(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key.lower().strip(), value),
        )
    return f"Got it. I'll remember that {key} is {value}."


def recall(key):
    with _conn() as c:
        row = c.execute("SELECT value FROM facts WHERE key=?", (key.lower().strip(),)).fetchone()
    return row[0] if row else None


def list_facts():
    with _conn() as c:
        return c.execute("SELECT key, value FROM facts").fetchall()


def add_note(text):
    with _conn() as c:
        c.execute("INSERT INTO notes(text, created) VALUES(?, ?)", (text, time.time()))
    return "Noted."


def log(role, text):
    """Keep temporary conversational context in memory, never in the database."""
    _session_history.append((role, text))


def recent_history(n=10):
    """Return recent in-session context, oldest first. Nothing is persisted."""
    return list(_session_history)[-n:]
