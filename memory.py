"""Long-term memory: facts, notes, and conversation history in SQLite.

Nothing leaves the laptop. This is the layer that makes JARVIS remember
you across restarts instead of starting from zero every time.
"""
import sqlite3
import time

from config import MEMORY_DB


def _conn():
    conn = sqlite3.connect(MEMORY_DB)
    conn.execute("CREATE TABLE IF NOT EXISTS facts (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS notes (id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT, created REAL)")
    conn.execute("CREATE TABLE IF NOT EXISTS history (id INTEGER PRIMARY KEY AUTOINCREMENT, role TEXT, text TEXT, created REAL)")
    return conn


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
    with _conn() as c:
        c.execute("INSERT INTO history(role, text, created) VALUES(?, ?, ?)", (role, text, time.time()))


def recent_history(n=10):
    """Last n turns as (role, text) tuples, oldest first."""
    with _conn() as c:
        rows = c.execute("SELECT role, text FROM history ORDER BY id DESC LIMIT ?", (n,)).fetchall()
    return list(reversed(rows))
