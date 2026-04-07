"""Memory manager — read/write/query NPC memories and relationships."""

import time
from typing import Optional
from .database import get_connection


class MemoryManager:
    def __init__(self):
        self.conn = get_connection()

    def close(self):
        self.conn.close()

    # ── Memories ──────────────────────────────────────────────────────

    def save_memory(
        self,
        npc_id: str,
        content: str,
        category: str = "episodic",
        source: str = "observation",
        importance: int = 5,
        tags: str = "",
        game_time: Optional[int] = None,
    ) -> int:
        ts = game_time or int(time.time())
        cur = self.conn.execute(
            """INSERT INTO memories (npc_id, timestamp, category, content, source, importance, tags)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (npc_id, ts, category, content, source, min(max(importance, 1), 10), tags),
        )
        self.conn.commit()
        return cur.lastrowid

    def recall_memories(
        self,
        npc_id: str,
        query: Optional[str] = None,
        category: Optional[str] = None,
        limit: int = 10,
        min_importance: int = 1,
    ) -> list[dict]:
        """Retrieve memories using relevance-ranked keyword search.
        Matches keywords against both content and tags. Results are ranked by
        number of keyword hits (more matches = more relevant), then importance,
        then recency. Requires at least one keyword match (OR logic, not AND)."""
        if query:
            keywords = query.lower().split()
            # Build a relevance score: count how many keywords match in content OR tags
            match_clauses = []
            kw_params: list = []
            for kw in keywords:
                match_clauses.append(
                    "(CASE WHEN LOWER(content) LIKE ? OR LOWER(tags) LIKE ? THEN 1 ELSE 0 END)"
                )
                kw_params.extend([f"%{kw}%", f"%{kw}%"])

            relevance_expr = " + ".join(match_clauses)

            # Parameter order must match SQL: SELECT relevance, WHERE npc_id, importance, relevance
            sql = f"""SELECT *, ({relevance_expr}) AS relevance
                      FROM memories
                      WHERE npc_id = ? AND importance >= ? AND ({relevance_expr}) > 0"""
            params: list = list(kw_params)  # for SELECT relevance
            params.extend([npc_id, min_importance])  # for WHERE npc_id, importance
            params.extend(kw_params)  # for WHERE relevance

            if category:
                sql += " AND category = ?"
                params.append(category)

            sql += " ORDER BY relevance DESC, importance DESC, timestamp DESC LIMIT ?"
            params.append(limit)
        else:
            sql = "SELECT * FROM memories WHERE npc_id = ? AND importance >= ?"
            params = [npc_id, min_importance]

            if category:
                sql += " AND category = ?"
                params.append(category)

            sql += " ORDER BY importance DESC, timestamp DESC LIMIT ?"
            params.append(limit)

        rows = self.conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def get_recent_memories(self, npc_id: str, limit: int = 10) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM memories WHERE npc_id = ? ORDER BY timestamp DESC LIMIT ?",
            (npc_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_all_memories(self, npc_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM memories WHERE npc_id = ? ORDER BY timestamp DESC",
            (npc_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ── Relationships ─────────────────────────────────────────────────

    def get_relationship(self, npc_id: str, target: str) -> Optional[dict]:
        row = self.conn.execute(
            "SELECT * FROM relationships WHERE npc_id = ? AND target = ?",
            (npc_id, target),
        ).fetchone()
        return dict(row) if row else None

    def update_relationship(
        self,
        npc_id: str,
        target: str,
        disposition: Optional[int] = None,
        trust: Optional[int] = None,
        notes: Optional[str] = None,
        known_as: Optional[str] = None,
    ) -> dict:
        existing = self.get_relationship(npc_id, target)
        if existing:
            d = disposition if disposition is not None else existing["disposition"]
            t = trust if trust is not None else existing["trust"]
            n = notes if notes is not None else existing["notes"]
            k = known_as if known_as is not None else existing.get("known_as")
            self.conn.execute(
                """UPDATE relationships
                   SET disposition=?, trust=?, notes=?, known_as=?,
                       updated_at=CURRENT_TIMESTAMP
                   WHERE npc_id=? AND target=?""",
                (min(max(d, 0), 100), min(max(t, 0), 100), n, k, npc_id, target),
            )
        else:
            d = disposition if disposition is not None else 50
            t = trust if trust is not None else 50
            n = notes or ""
            k = known_as
            self.conn.execute(
                """INSERT INTO relationships (npc_id, target, disposition, trust, notes, known_as)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (npc_id, target, min(max(d, 0), 100), min(max(t, 0), 100), n, k),
            )
        self.conn.commit()
        return self.get_relationship(npc_id, target)

    def get_all_relationships(self, npc_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM relationships WHERE npc_id = ?", (npc_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    # ── Inter-NPC Messages ────────────────────────────────────────────

    def send_message(self, from_npc: str, to_npc: str, content: str) -> int:
        cur = self.conn.execute(
            "INSERT INTO npc_messages (from_npc, to_npc, content) VALUES (?, ?, ?)",
            (from_npc, to_npc, content),
        )
        self.conn.commit()
        return cur.lastrowid

    def get_pending_messages(self, npc_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM npc_messages WHERE to_npc = ? AND delivered = 0 ORDER BY created_at",
            (npc_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def mark_messages_delivered(self, npc_id: str):
        self.conn.execute(
            "UPDATE npc_messages SET delivered = 1 WHERE to_npc = ? AND delivered = 0",
            (npc_id,),
        )
        self.conn.commit()

    # ── World State ───────────────────────────────────────────────────

    def get_world_state(self, key: str) -> Optional[str]:
        row = self.conn.execute(
            "SELECT value FROM world_state WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else None

    def set_world_state(self, key: str, value: str):
        self.conn.execute(
            """INSERT INTO world_state (key, value, updated_at)
               VALUES (?, ?, CURRENT_TIMESTAMP)
               ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=CURRENT_TIMESTAMP""",
            (key, value),
        )
        self.conn.commit()
