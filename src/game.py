"""Game master orchestrator — manages the game loop, NPC routing, and between-turn processing."""

import anthropic
from pathlib import Path

from .database import init_db
from .memory import MemoryManager
from .npc_agent import NPCAgent, load_npc_definition
from .seed import seed_initial_data

NPCS_DIR = Path(__file__).parent.parent / "npcs"


class GameMaster:
    def __init__(self, api_key: str = None):
        init_db()

        self.client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
        self.memory_mgr = MemoryManager()
        self.agents: dict[str, NPCAgent] = {}
        self.current_npc: str = None
        self.turn_count = 0

        # Load all NPC agents
        for yaml_file in NPCS_DIR.glob("*.yaml"):
            npc_id = yaml_file.stem
            self.agents[npc_id] = NPCAgent(npc_id, self.memory_mgr, self.client)

    def seed_if_needed(self):
        """Seed initial data if the database is empty."""
        existing = self.memory_mgr.get_all_relationships("barkeeper")
        if not existing:
            seed_initial_data(self.memory_mgr)
            return True
        return False

    def get_available_npcs(self) -> list[str]:
        return list(self.agents.keys())

    def get_npc_display_name(self, npc_id: str) -> str:
        return self.agents[npc_id].npc_def["name"]

    def resolve_npc(self, input_str: str) -> str | None:
        """Resolve a player input to an npc_id. Accepts id, full name, or first name (case-insensitive)."""
        key = input_str.lower().strip()
        # Direct id match
        if key in self.agents:
            return key
        # Match by full name or first name
        for npc_id, agent in self.agents.items():
            full_name = agent.npc_def["name"].lower()
            first_name = full_name.split()[0]
            if key == full_name or key == first_name:
                return npc_id
        return None

    def talk_to(self, npc_id: str):
        """Switch conversation to a different NPC."""
        if npc_id not in self.agents:
            raise ValueError(f"Unknown NPC: {npc_id}")
        if self.current_npc and self.current_npc != npc_id:
            # Auto-summarize the conversation before walking away
            self.agents[self.current_npc].summarize_and_save()
            self.agents[self.current_npc].reset_conversation()
        self.current_npc = npc_id

    def player_say(self, message: str) -> tuple[str, list[dict]]:
        """Send a player message to the current NPC and return their response."""
        if not self.current_npc:
            raise RuntimeError("No NPC selected. Use talk_to() first.")
        self.turn_count += 1
        agent = self.agents[self.current_npc]
        dialogue, tool_log = agent.respond(message)
        return dialogue, tool_log

    def process_between_turns(self):
        """Process NPC-to-NPC messages — deliver pending messages as memories."""
        for npc_id, agent in self.agents.items():
            messages = self.memory_mgr.get_pending_messages(npc_id)
            for msg in messages:
                from_name = self.get_npc_display_name(msg["from_npc"]) if msg["from_npc"] in self.agents else msg["from_npc"]
                self.memory_mgr.save_memory(
                    npc_id=npc_id,
                    content=f"{from_name} ({msg['from_npc']}) told me: {msg['content']}",
                    category="social",
                    source=msg["from_npc"],
                    importance=7,
                    tags=f"{msg['from_npc']},told me,message",
                )
            self.memory_mgr.mark_messages_delivered(npc_id)

    def shutdown(self):
        self.memory_mgr.close()
