"""GM Agent — handles world narration, environment descriptions, and non-NPC interactions."""

import anthropic
import re
import time
import yaml
from dataclasses import dataclass, field
from pathlib import Path

from .memory import MemoryManager
from .gm_tools import GM_TOOLS
from .npc_agent import _log_api_call, load_all_npc_definitions, _load_template
from . import world_data

NPCS_DIR = Path(__file__).parent.parent / "npcs"


@dataclass
class SceneEvent:
    """A witnessed event in the current scene, used to bridge GM narration to NPC awareness."""
    description: str       # factual, third-person, brief
    actor: str             # "player", npc_id, or "environment"
    timestamp: float = field(default_factory=time.time)

GM_MODEL = "claude-haiku-4-5-20251001"
# Max LLM exchanges in a single narration call
MAX_ITERATIONS = 5
# Keep working history short — GM doesn't need long context
MAX_GM_HISTORY = 6  # 3 player inputs + 3 GM responses


def build_gm_system_prompt(location_id: str) -> str:
    """Build the GM system prompt from templates, injecting current location."""
    instructions = _load_template("gm_instructions.txt")
    template = _load_template("gm_system_prompt.txt")

    loc = world_data.load_location(location_id)
    if loc:
        location_name = loc["name"]
        location_atmosphere = loc.get("atmosphere", "").strip()
    else:
        location_name = location_id
        location_atmosphere = ""

    return template.format(
        instructions=instructions,
        location_name=location_name,
        location_atmosphere=location_atmosphere,
    )


def execute_gm_tool(
    tool_name: str, tool_input: dict, location_id: str, memory_mgr: MemoryManager,
    gm_agent: "GMAgent | None" = None,
) -> str:
    """Execute a GM tool and return the result string."""

    if tool_name == "describe_location":
        loc_id = tool_input.get("location_id", location_id)
        loc = world_data.load_location(loc_id)
        if not loc:
            return f"No data found for location '{loc_id}'."
        parts = [
            f"Location: {loc['name']}",
            f"Description: {loc['description'].strip()}",
            f"Atmosphere: {loc.get('atmosphere', '').strip()}",
        ]
        objects = loc.get("objects", {})
        if objects:
            parts.append("Objects: " + ", ".join(
                f"{k.replace('_', ' ')} ({'interactive' if v.get('interactive') else 'scenery'})"
                for k, v in objects.items()
            ))
        exits = loc.get("exits", {})
        if exits:
            parts.append("Exits: " + ", ".join(
                f"{k} — {v['description']}" for k, v in exits.items()
            ))
        return "\n".join(parts)

    elif tool_name == "examine_object":
        desc = world_data.get_object_description(location_id, tool_input["object_name"])
        if desc:
            return desc
        return f"You don't see anything called '{tool_input['object_name']}' here."

    elif tool_name == "get_npc_presence":
        npc_ids = world_data.get_npcs_at_location(location_id)
        if not npc_ids:
            return "No one else is here."
        all_npcs = load_all_npc_definitions()
        lines = []
        for npc_id in npc_ids:
            npc_def = all_npcs.get(npc_id)
            if npc_def:
                first_line = npc_def.get("appearance", "").strip().split("\n")[0]
                lines.append(f"- {npc_def['name']}, {npc_def['role']}. {first_line}")
        return "\n".join(lines) if lines else "No one else is here."

    elif tool_name == "get_lore":
        results = world_data.search_lore(tool_input["query"])
        if not results:
            return "You don't know anything specific about that."
        parts = []
        for lore in results[:3]:
            parts.append(f"{lore['name']}: {lore.get('summary', '').strip()}")
            for detail in lore.get("details", [])[:4]:
                parts.append(f"  - {detail}")
        return "\n".join(parts)

    elif tool_name == "check_world_state":
        value = memory_mgr.get_world_state(tool_input["key"])
        if value is None:
            return f"No state recorded for '{tool_input['key']}'."
        return f"{tool_input['key']} = {value}"

    elif tool_name == "update_world_state":
        memory_mgr.set_world_state(tool_input["key"], tool_input["value"])
        return f"World state updated: {tool_input['key']} = {tool_input['value']}"

    elif tool_name == "log_scene_event":
        if gm_agent is None:
            return "Error: No GM agent context available."
        event = gm_agent.log_scene_event(
            description=tool_input["description"],
            actor=tool_input["actor"],
        )
        return f"Event logged: {event.description}"

    elif tool_name == "recall_world_events":
        results = memory_mgr.recall_world_events(
            query=tool_input.get("query"),
            limit=10,
            min_importance=1,
        )
        if not results:
            return "No world events found for that query."
        lines = []
        for evt in results:
            source = evt.get("source_npc", "?")
            etype = evt.get("event_type", "event")
            lines.append(f"- [{etype}] (from {source}, imp={evt['importance']}) {evt['content']}")
        return "\n".join(lines)

    elif tool_name == "create_npc":
        if gm_agent is None:
            return "Error: No GM agent context available."
        return gm_agent.create_npc(tool_input, location_id)

    elif tool_name == "start_conversation":
        if gm_agent is None:
            return "Error: No GM agent context available."
        npc_id = tool_input["npc_id"]
        # Check the NPC actually exists at this location
        npc_ids = world_data.get_npcs_at_location(location_id)
        if npc_id not in npc_ids:
            all_npcs = load_all_npc_definitions()
            if npc_id not in all_npcs:
                return f"Error: NPC '{npc_id}' does not exist."
            return f"Error: NPC '{npc_id}' is not at this location."
        gm_agent.pending_action = {"type": "talk", "npc_id": npc_id}
        all_npcs = load_all_npc_definitions()
        name = all_npcs[npc_id]["name"]
        return f"Starting conversation with {name}."

    return f"Unknown tool: {tool_name}"


class GMAgent:
    """Game Master agent — narrates the world and handles non-NPC interactions."""

    def __init__(self, memory_mgr: MemoryManager, api_key: str, register_npc_fn=None):
        self.memory_mgr = memory_mgr
        self.client = anthropic.Anthropic(api_key=api_key)
        self.current_location = "rusty_flagon"
        self.working_history: list[dict] = []
        self.scene_events: list[SceneEvent] = []
        self.register_npc_fn = register_npc_fn
        # Pending game action — checked by main.py after narrate() returns
        self.pending_action: dict | None = None

    def get_scene_description(self) -> str:
        """Render location description from YAML. No LLM call."""
        return world_data.get_location_description(self.current_location)

    def get_npcs_here(self) -> list[str]:
        """Return NPC IDs at the current location."""
        return world_data.get_npcs_at_location(self.current_location)

    def examine(self, object_name: str) -> str | None:
        """Try to get a static object description. Returns None if not found."""
        return world_data.get_object_description(self.current_location, object_name)

    def narrate(self, player_input: str) -> tuple[str, list[dict]]:
        """Handle freeform player input with an LLM call.
        Returns (narration_text, tool_log)."""
        user_msg = {"role": "user", "content": player_input}
        self.working_history.append(user_msg)
        self._trim_history()

        system_prompt = build_gm_system_prompt(self.current_location)
        tool_log = []

        for _ in range(MAX_ITERATIONS):
            response = self.client.messages.create(
                model=GM_MODEL,
                max_tokens=1024,
                system=system_prompt,
                tools=GM_TOOLS,
                messages=self.working_history,
            )
            _log_api_call("gm", system_prompt, self.working_history, GM_TOOLS, response)

            assistant_content = response.content
            self.working_history.append({"role": "assistant", "content": assistant_content})

            # Extract text
            text_blocks = [b.text for b in assistant_content if b.type == "text"]
            tool_uses = [b for b in assistant_content if b.type == "tool_use"]

            if not tool_uses:
                narration = "\n".join(text_blocks).strip()
                return narration or "Nothing notable happens.", tool_log

            # Process tool calls
            tool_results = []
            for tool_use in tool_uses:
                result_str = execute_gm_tool(
                    tool_use.name, tool_use.input, self.current_location,
                    self.memory_mgr, gm_agent=self,
                )
                tool_log.append({
                    "tool": tool_use.name,
                    "input": tool_use.input,
                    "result": result_str,
                })
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use.id,
                    "content": result_str,
                })
            self.working_history.append({"role": "user", "content": tool_results})

        # Fallback if we hit max iterations
        return "You pause and take in your surroundings.", tool_log

    # ── Scene Events ────────────────────────────────────────────────

    def log_scene_event(self, description: str, actor: str) -> SceneEvent:
        """Log a significant event that NPCs in the scene would witness."""
        event = SceneEvent(description=description, actor=actor)
        self.scene_events.append(event)
        return event

    def get_scene_events(self) -> list[SceneEvent]:
        """Return current scene events for NPC context injection."""
        return list(self.scene_events)

    def clear_scene_events(self):
        """Clear events — called when the player changes location."""
        self.scene_events = []

    # ── Dynamic NPC Creation ──────────────────────────────────────

    def create_npc(self, tool_input: dict, location_id: str) -> str:
        """Create a new NPC: write YAML, seed data, register agent."""
        npc_id = tool_input["id"]

        # Validate ID format
        if not re.match(r"^[a-z][a-z0-9_]*$", npc_id):
            return (
                f"Error: Invalid NPC id '{npc_id}'. "
                "Use lowercase letters, digits, and underscores only."
            )

        # Check for collision
        yaml_path = NPCS_DIR / f"{npc_id}.yaml"
        all_npcs = load_all_npc_definitions()
        if npc_id in all_npcs or yaml_path.exists():
            return f"Error: NPC '{npc_id}' already exists."

        # Build NPC definition
        npc_def = {
            "id": npc_id,
            "name": tool_input["name"],
            "role": tool_input["role"],
            "model": GM_MODEL,
            "personality": tool_input["personality"],
            "appearance": tool_input["appearance"],
            "dialogue_style": tool_input["dialogue_style"],
            "location": location_id,
            "starting_relationships": {
                "player": {
                    "disposition": 50,
                    "trust": 50,
                    "notes": "Just met.",
                }
            },
            "base_knowledge": tool_input.get("base_knowledge", []),
        }

        # Write YAML to disk
        with open(yaml_path, "w", encoding="utf-8") as f:
            yaml.dump(
                npc_def, f,
                default_flow_style=False, allow_unicode=True, sort_keys=False,
            )

        # Add to NPC definitions cache
        all_npcs[npc_id] = npc_def

        # Seed player relationship
        self.memory_mgr.update_relationship(
            npc_id=npc_id,
            target="player",
            disposition=50,
            trust=50,
            notes="Just met.",
        )

        # Seed base knowledge
        for fact in npc_def.get("base_knowledge", []):
            self.memory_mgr.save_memory(
                npc_id=npc_id,
                content=fact,
                category="semantic",
                source="base_knowledge",
                importance=7,
                tags="world,starting",
            )

        # Add to location
        world_data.add_npc_to_location(location_id, npc_id)

        # Register live agent via callback
        if self.register_npc_fn:
            self.register_npc_fn(npc_id)

        return f"Created NPC '{npc_def['name']}' ({npc_id}) at {location_id}."

    # ── Internal ──────────────────────────────────────────────────

    def _trim_history(self):
        """Keep working history short."""
        if len(self.working_history) > MAX_GM_HISTORY:
            self.working_history = self.working_history[-MAX_GM_HISTORY:]

    def reset(self):
        """Clear GM conversation history."""
        self.working_history = []
