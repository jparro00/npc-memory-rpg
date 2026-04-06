"""Dump the entire game database to a JSON file for inspection."""
import sys, os, json
if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

from src.database import init_db, get_connection
from pathlib import Path

OUTPUT_PATH = Path(__file__).parent / "data" / "db_dump.json"


def dump():
    init_db()
    conn = get_connection()

    # Load all NPC ids from memories/relationships
    npc_ids = set()
    for row in conn.execute("SELECT DISTINCT npc_id FROM memories").fetchall():
        npc_ids.add(row["npc_id"])
    for row in conn.execute("SELECT DISTINCT npc_id FROM relationships").fetchall():
        npc_ids.add(row["npc_id"])

    npcs = {}
    for npc_id in sorted(npc_ids):
        memories = [dict(r) for r in conn.execute(
            "SELECT id, category, content, source, importance, tags, timestamp FROM memories WHERE npc_id = ? ORDER BY timestamp DESC",
            (npc_id,),
        ).fetchall()]

        relationships = [dict(r) for r in conn.execute(
            "SELECT target, disposition, trust, notes FROM relationships WHERE npc_id = ? ORDER BY target",
            (npc_id,),
        ).fetchall()]

        pending_msgs = [dict(r) for r in conn.execute(
            "SELECT from_npc, content, created_at FROM npc_messages WHERE to_npc = ? AND delivered = 0 ORDER BY created_at",
            (npc_id,),
        ).fetchall()]

        delivered_msgs = [dict(r) for r in conn.execute(
            "SELECT from_npc, to_npc, content, created_at FROM npc_messages WHERE (from_npc = ? OR to_npc = ?) AND delivered = 1 ORDER BY created_at",
            (npc_id, npc_id),
        ).fetchall()]

        npcs[npc_id] = {
            "memories": memories,
            "relationships": relationships,
            "pending_messages": pending_msgs,
            "delivered_messages": delivered_msgs,
        }

    # World state
    world_state = {row["key"]: row["value"] for row in conn.execute(
        "SELECT key, value FROM world_state ORDER BY key"
    ).fetchall()}

    dump_data = {
        "npcs": npcs,
        "world_state": world_state,
    }

    conn.close()

    os.makedirs(OUTPUT_PATH.parent, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(dump_data, f, indent=2, ensure_ascii=False)

    print(f"Database dumped to {OUTPUT_PATH}")
    for npc_id, data in npcs.items():
        print(f"  {npc_id}: {len(data['memories'])} memories, {len(data['relationships'])} relationships")


if __name__ == "__main__":
    dump()
