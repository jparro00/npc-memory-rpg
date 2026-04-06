"""Seed initial data — load starting relationships and base memories from NPC definitions."""

from pathlib import Path
import yaml
from .memory import MemoryManager

NPCS_DIR = Path(__file__).parent.parent / "npcs"


def seed_initial_data(memory_mgr: MemoryManager):
    """Load starting relationships and base knowledge into the database."""
    for yaml_file in NPCS_DIR.glob("*.yaml"):
        with open(yaml_file, "r", encoding="utf-8") as f:
            npc_def = yaml.safe_load(f)

        npc_id = npc_def["id"]

        # Seed starting relationships
        for target, rel in npc_def.get("starting_relationships", {}).items():
            memory_mgr.update_relationship(
                npc_id=npc_id,
                target=target,
                disposition=rel.get("disposition", 50),
                trust=rel.get("trust", 50),
                notes=rel.get("notes", ""),
            )

        # Seed base knowledge as semantic memories
        for i, fact in enumerate(npc_def.get("base_knowledge", [])):
            memory_mgr.save_memory(
                npc_id=npc_id,
                content=fact,
                category="semantic",
                source="base_knowledge",
                importance=7,
                tags="world,starting",
            )

    print(f"Seeded data for {len(list(NPCS_DIR.glob('*.yaml')))} NPCs.")
