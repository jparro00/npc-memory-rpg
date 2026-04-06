"""Utility to inspect the game database — view NPC memories, relationships, and messages."""

import sys
import os

# Fix Windows console encoding
if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

from src.database import init_db
from src.memory import MemoryManager


def inspect_npc(npc_id: str, memory_mgr: MemoryManager):
    print(f"\n{'='*60}")
    print(f"  NPC: {npc_id}")
    print(f"{'='*60}")

    # Memories
    memories = memory_mgr.get_all_memories(npc_id)
    print(f"\n  MEMORIES ({len(memories)} total)")
    print(f"  {'-'*50}")
    for m in memories:
        src = f" [from: {m['source']}]" if m['source'] != 'self' else ""
        tags = f" #{m['tags']}" if m['tags'] else ""
        print(f"  [{m['category']:8}] imp={m['importance']:2d}  {m['content'][:80]}{src}{tags}")

    # Relationships
    rels = memory_mgr.get_all_relationships(npc_id)
    print(f"\n  RELATIONSHIPS ({len(rels)} total)")
    print(f"  {'-'*50}")
    for r in rels:
        bar_d = "█" * (r['disposition'] // 10) + "░" * (10 - r['disposition'] // 10)
        bar_t = "█" * (r['trust'] // 10) + "░" * (10 - r['trust'] // 10)
        print(f"  {r['target']:12} disp=[{bar_d}] {r['disposition']:3d}  trust=[{bar_t}] {r['trust']:3d}")
        if r['notes']:
            print(f"  {'':12} \"{r['notes']}\"")

    # Pending messages
    msgs = memory_mgr.get_pending_messages(npc_id)
    if msgs:
        print(f"\n  PENDING MESSAGES ({len(msgs)})")
        print(f"  {'-'*50}")
        for msg in msgs:
            print(f"  From {msg['from_npc']}: {msg['content'][:80]}")


def main():
    init_db()
    memory_mgr = MemoryManager()

    if len(sys.argv) > 1:
        for npc_id in sys.argv[1:]:
            inspect_npc(npc_id, memory_mgr)
    else:
        # Show all NPCs
        from pathlib import Path
        npcs_dir = Path(__file__).parent / "npcs"
        for yaml_file in sorted(npcs_dir.glob("*.yaml")):
            inspect_npc(yaml_file.stem, memory_mgr)

    memory_mgr.close()


if __name__ == "__main__":
    main()
