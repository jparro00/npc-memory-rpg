"""Game master orchestrator — manages the game loop, NPC routing, and between-turn processing."""

import anthropic
from enum import Enum
from pathlib import Path

from .database import init_db
from .memory import MemoryManager
from .npc_agent import NPCAgent, load_npc_definition
from .gm_agent import GMAgent
from .seed import seed_initial_data

NPCS_DIR = Path(__file__).parent.parent / "npcs"


class GameMode(Enum):
    FREE_ROAM = "free_roam"
    NPC_CONVERSATION = "npc_conversation"


class GameMaster:
    def __init__(self, api_key: str = None):
        init_db()

        self.client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
        self.memory_mgr = MemoryManager()
        self.agents: dict[str, NPCAgent] = {}
        self.current_npc: str = None
        self.mode = GameMode.FREE_ROAM
        self.turn_count = 0

        # Load all NPC agents
        for yaml_file in NPCS_DIR.glob("*.yaml"):
            npc_id = yaml_file.stem
            self.agents[npc_id] = NPCAgent(npc_id, self.memory_mgr, self.client)

        # Initialize GM agent
        self.gm = GMAgent(self.memory_mgr, api_key=api_key, register_npc_fn=self._register_npc)

        # Inject dynamically created NPCs into their locations.
        # Static NPCs are listed in the location YAML; dynamic NPCs store
        # their location in their own YAML and need to be added at startup.
        from . import world_data
        for npc_id, agent in self.agents.items():
            loc_field = agent.npc_def.get("location")
            if loc_field:
                world_data.add_npc_to_location(loc_field, npc_id)

    def _register_npc(self, npc_id: str):
        """Register a dynamically created NPC as a live agent."""
        if npc_id not in self.agents:
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

    def get_location_name(self) -> str:
        """Return the display name of the current location."""
        from . import world_data
        loc = world_data.load_location(self.gm.current_location)
        return loc["name"] if loc else "Unknown"

    def get_scene_description(self) -> str:
        """Get a formatted scene description. No LLM call."""
        return self.gm.get_scene_description()

    def resolve_npc(self, input_str: str) -> str | None:
        """Resolve a player input to an npc_id. Accepts id, full name, or first name (case-insensitive)."""
        key = input_str.lower().strip()
        # Strip leading articles ("the barkeeper" → "barkeeper")
        for article in ("the ", "a ", "an "):
            if key.startswith(article):
                key = key[len(article):]
                break
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
        """Switch to NPC conversation mode."""
        if npc_id not in self.agents:
            raise ValueError(f"Unknown NPC: {npc_id}")
        if self.current_npc and self.current_npc != npc_id:
            self.agents[self.current_npc].summarize_and_save()
            self.agents[self.current_npc].reset_conversation()
        self.current_npc = npc_id
        self.mode = GameMode.NPC_CONVERSATION
        # Inject scene events so the NPC knows what just happened
        self.agents[npc_id].pending_scene_events = self.gm.get_scene_events()

    def leave_conversation(self) -> str:
        """Leave current NPC conversation, return to free roam.
        Returns a brief transition message."""
        if self.current_npc:
            npc_name = self.get_npc_display_name(self.current_npc)
            self.agents[self.current_npc].summarize_and_save()
            self.agents[self.current_npc].reset_conversation()
            self.current_npc = None
            self.mode = GameMode.FREE_ROAM
            return f"You step away from {npc_name}."
        self.mode = GameMode.FREE_ROAM
        return ""

    def player_say(self, message: str) -> tuple[str, list[dict]]:
        """Send a player message to the current NPC and return their response."""
        if not self.current_npc:
            raise RuntimeError("No NPC selected. Use talk_to() first.")
        self.turn_count += 1
        agent = self.agents[self.current_npc]
        dialogue, tool_log = agent.respond(message)
        return dialogue, tool_log

    def free_roam_input(self, message: str) -> tuple[str, list[dict]]:
        """Handle freeform input in free roam mode via the GM agent."""
        return self.gm.narrate(message)

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
