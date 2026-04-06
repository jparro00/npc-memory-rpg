"""SQLite database schema and connection management for NPC memory system."""

import sqlite3
import os
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "game.db"


def get_connection() -> sqlite3.Connection:
    os.makedirs(DB_PATH.parent, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Create all tables if they don't exist."""
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            npc_id TEXT NOT NULL,
            timestamp INTEGER NOT NULL,
            category TEXT NOT NULL CHECK(category IN (
                'episodic', 'semantic', 'social'
            )),
            content TEXT NOT NULL,
            source TEXT,             -- who/what created this memory
            importance INTEGER DEFAULT 5 CHECK(importance BETWEEN 1 AND 10),
            tags TEXT DEFAULT '',    -- comma-separated tags for filtering
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_memories_npc
            ON memories(npc_id, timestamp DESC);
        CREATE INDEX IF NOT EXISTS idx_memories_category
            ON memories(npc_id, category);

        CREATE TABLE IF NOT EXISTS relationships (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            npc_id TEXT NOT NULL,
            target TEXT NOT NULL,        -- another NPC id or 'player'
            disposition INTEGER DEFAULT 50 CHECK(disposition BETWEEN 0 AND 100),
            trust INTEGER DEFAULT 50 CHECK(trust BETWEEN 0 AND 100),
            notes TEXT DEFAULT '',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(npc_id, target)
        );

        CREATE TABLE IF NOT EXISTS npc_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            from_npc TEXT NOT NULL,
            to_npc TEXT NOT NULL,
            content TEXT NOT NULL,
            delivered INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_messages_to
            ON npc_messages(to_npc, delivered);

        CREATE TABLE IF NOT EXISTS world_state (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()
    conn.close()


def reset_db():
    """Delete and recreate the database."""
    if DB_PATH.exists():
        DB_PATH.unlink()
    init_db()
