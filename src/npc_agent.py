"""NPC Agent — runs a single NPC's turn using the Anthropic API with tool use."""

import json
import os
import yaml
import anthropic
from datetime import datetime
from pathlib import Path
from typing import Optional

from .memory import MemoryManager
from .npc_tools import NPC_TOOLS
from .action_tools import ACTION_TOOLS

# Set NPC_LOG=1 to dump every API call to data/api_logs/
API_LOG_ENABLED = os.environ.get("NPC_LOG", "0") == "1"
API_LOG_DIR = Path(__file__).parent.parent / "data" / "api_logs"
_api_call_counter = 0


def _log_api_call(npc_id: str, system: str, messages: list, tools: list, response):
    """Write the full API request and response to a JSON file."""
    if not API_LOG_ENABLED:
        return
    global _api_call_counter
    _api_call_counter += 1

    os.makedirs(API_LOG_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%H%M%S")
    filename = f"{_api_call_counter:04d}_{timestamp}_{npc_id}.json"

    # Serialize messages — content blocks may be Anthropic objects
    def serialize(obj):
        if hasattr(obj, "to_dict"):
            return obj.to_dict()
        if hasattr(obj, "model_dump"):
            return obj.model_dump()
        if hasattr(obj, "__dict__"):
            return {k: v for k, v in obj.__dict__.items() if not k.startswith("_")}
        return str(obj)

    def clean_messages(msgs):
        cleaned = []
        for msg in msgs:
            content = msg.get("content")
            if isinstance(content, list):
                content = [serialize(b) if not isinstance(b, dict) else b for b in content]
            cleaned.append({"role": msg["role"], "content": content})
        return cleaned

    log_entry = {
        "call_number": _api_call_counter,
        "npc_id": npc_id,
        "model": response.model if hasattr(response, "model") else "unknown",
        "timestamp": datetime.now().isoformat(),
        "request": {
            "system_prompt": system,
            "system_prompt_words": len(system.split()),
            "messages": clean_messages(messages),
            "message_count": len(messages),
            "tool_count": len(tools),
        },
        "response": {
            "content": [serialize(b) for b in response.content],
            "stop_reason": response.stop_reason,
            "usage": {
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            },
        },
    }

    with open(API_LOG_DIR / filename, "w", encoding="utf-8") as f:
        json.dump(log_entry, f, indent=2, ensure_ascii=False, default=str)

NPCS_DIR = Path(__file__).parent.parent / "npcs"
CONFIG_DIR = Path(__file__).parent.parent / "config"


def _load_template(filename: str) -> str:
    """Load a prompt template from the config directory."""
    path = CONFIG_DIR / filename
    with open(path, "r", encoding="utf-8") as f:
        return f.read().strip()

# Cache all NPC definitions for scene awareness
_npc_defs_cache: dict[str, dict] = {}


def load_all_npc_definitions() -> dict[str, dict]:
    """Load and cache all NPC YAML files."""
    if not _npc_defs_cache:
        for path in NPCS_DIR.glob("*.yaml"):
            with open(path, "r", encoding="utf-8") as f:
                npc_def = yaml.safe_load(f)
                _npc_defs_cache[npc_def["id"]] = npc_def
    return _npc_defs_cache


def load_npc_definition(npc_id: str) -> dict:
    defs = load_all_npc_definitions()
    if npc_id in defs:
        return defs[npc_id]
    path = NPCS_DIR / f"{npc_id}.yaml"
    with open(path, "r", encoding="utf-8") as f:
        npc_def = yaml.safe_load(f)
        _npc_defs_cache[npc_id] = npc_def
        return npc_def


def get_scene_description(current_npc_id: str) -> str:
    """Return a description of who else is present — called via look_around tool.
    Uses world data for location info, falls back to NPC definitions."""
    from . import world_data

    # Try to get location data for atmosphere
    loc = world_data.load_location("rusty_flagon")
    parts = []
    if loc:
        parts.append(loc.get("atmosphere", "").strip())

    # List other NPCs present
    all_npcs = load_all_npc_definitions()
    others = []
    for npc_id, npc_def in all_npcs.items():
        if npc_id == current_npc_id:
            continue
        others.append(
            f"- {npc_def['name']} ({npc_id}): {npc_def['role']}. "
            f"{npc_def.get('appearance', '').strip().split(chr(10))[0]}"
        )
    if others:
        parts.append("You see:\n" + "\n".join(others))
    elif not parts:
        return "You don't see anyone else around."

    return "\n\n".join(parts)


def build_system_prompt(npc_def: dict, memory_mgr: MemoryManager) -> str:
    """Construct a minimal system prompt — identity and instructions only.
    All knowledge, memories, relationships, and scene info are accessed via tools."""
    npc_name = npc_def["name"]
    instructions = _load_template("npc_instructions.txt").replace("{name}", npc_name)
    template = _load_template("system_prompt.txt")
    return template.format(
        name=npc_name,
        role=npc_def["role"],
        personality=npc_def["personality"].strip(),
        appearance=npc_def.get("appearance", "").strip(),
        dialogue_style=npc_def["dialogue_style"].strip(),
        instructions=instructions,
    )


def _resolve_target(name: str) -> str:
    """Resolve a name/alias to a system ID. Handles NPC names, first names, IDs,
    and player aliases like 'traveler', 'stranger', etc."""
    key = name.lower().strip()

    # Player aliases
    if key in ("player", "traveler", "stranger", "the traveler", "the player", "the stranger"):
        return "player"

    # Direct NPC ID match
    all_npcs = load_all_npc_definitions()
    if key in all_npcs:
        return key

    # Match by full name or first name
    for npc_id, npc_def in all_npcs.items():
        full_name = npc_def["name"].lower()
        first_name = full_name.split()[0]
        if key == full_name or key == first_name:
            return npc_id

    # No match — return original (will still work, just won't route properly)
    return name


def execute_tool(
    npc_id: str, tool_name: str, tool_input: dict, memory_mgr: MemoryManager,
    npc_agent: "NPCAgent | None" = None,
) -> str:
    """Execute a tool call from the NPC and return the result as a string."""
    if tool_name == "save_memory":
        mem_id = memory_mgr.save_memory(
            npc_id=npc_id,
            content=tool_input["content"],
            category=tool_input.get("category", "episodic"),
            source="self",
            importance=tool_input.get("importance", 5),
            tags=tool_input.get("tags", ""),
        )
        return f"Memory saved (id={mem_id})."

    elif tool_name == "recall_memories":
        memories = memory_mgr.recall_memories(
            npc_id=npc_id,
            query=tool_input.get("query"),
            category=tool_input.get("category"),
            limit=10,
        )
        if not memories:
            return "You don't recall anything about that."
        result = "You remember:\n"
        for m in memories:
            result += f"- [{m['category']}] {m['content']}\n"
        return result

    elif tool_name == "check_relationship":
        target = _resolve_target(tool_input["target"])
        rel = memory_mgr.get_relationship(npc_id, target)
        if not rel:
            return f"You don't have any particular feelings about {target}."
        return (
            f"Your feelings about {target}: "
            f"disposition={rel['disposition']}/100 (0=hostile, 50=neutral, 100=devoted), "
            f"trust={rel['trust']}/100. Notes: {rel['notes']}"
        )

    elif tool_name == "update_relationship":
        rel = memory_mgr.update_relationship(
            npc_id=npc_id,
            target=_resolve_target(tool_input["target"]),
            disposition=tool_input.get("disposition"),
            trust=tool_input.get("trust"),
            notes=tool_input.get("notes"),
            known_as=tool_input.get("known_as"),
        )
        return f"Relationship updated: disposition={rel['disposition']}, trust={rel['trust']}."

    elif tool_name == "look_around":
        return get_scene_description(npc_id)

    elif tool_name == "send_message_to_npc":
        resolved_to = _resolve_target(tool_input["to_npc"])
        msg_id = memory_mgr.send_message(
            from_npc=npc_id,
            to_npc=resolved_to,
            content=tool_input["content"],
        )
        return f"Message sent to {resolved_to} (id={msg_id})."

    elif tool_name == "check_content_guidelines":
        return _load_template("content_guidelines.txt")

    elif tool_name == "escalate_to_gm":
        if npc_agent is None:
            return "Error: No agent context available."
        npc_agent.pending_gm_event = {
            "description": tool_input["description"],
            "npc_id": npc_id,
        }
        return "Scene handed off to the GM. Finish your own reaction, then stop."

    return f"Unknown tool: {tool_name}"


# How many recent player<->NPC exchanges to keep in the API messages.
# Each "exchange" = one player message + the NPC's full response chain (tool calls + reply).
RECENT_EXCHANGES_IN_CONTEXT = 3


def _extract_dialogue_text(history: list[dict]) -> list[dict]:
    """Extract a clean player/NPC dialogue log from the full conversation history.
    Strips tool calls and tool results, keeping only player messages and NPC text."""
    exchanges = []
    for msg in history:
        content = msg.get("content")
        if msg["role"] == "user" and isinstance(content, str):
            # Skip system nudges
            if content.startswith("[System:"):
                continue
            exchanges.append({"role": "player", "text": content})
        elif msg["role"] == "assistant" and isinstance(content, list):
            text_parts = []
            for block in content:
                if hasattr(block, "text") and block.text.strip():
                    text_parts.append(block.text.strip())
            if text_parts:
                exchanges.append({"role": "npc", "text": " ".join(text_parts)})
    return exchanges


class NPCAgent:
    def __init__(self, npc_id: str, memory_mgr: MemoryManager, client: anthropic.Anthropic):
        self.npc_id = npc_id
        self.npc_def = load_npc_definition(npc_id)
        self.memory_mgr = memory_mgr
        self.client = client
        self.model = self.npc_def.get("model", "claude-haiku-4-5-20251001")
        # Full history — everything that happened, used for recall_conversation and summarize
        self.full_history: list[dict] = []
        # Working history — only recent exchanges, sent to the API
        self.working_history: list[dict] = []
        # Scene events to inject on first message (set by GameMaster.talk_to)
        self.pending_scene_events: list = []
        # Set by escalate_to_gm tool — checked by main.py after respond()
        self.pending_gm_event: dict | None = None

    def reset_conversation(self):
        self.full_history = []
        self.working_history = []
        self.pending_scene_events = []
        self.pending_gm_event = None

    def _trim_working_history(self):
        """Trim working_history to only keep the last N player exchanges.
        An 'exchange' starts with a user message (that isn't a tool result)."""
        # Find the starts of player exchanges (user messages that are strings, not tool results)
        exchange_starts = []
        for i, msg in enumerate(self.working_history):
            if msg["role"] == "user" and isinstance(msg.get("content"), str):
                exchange_starts.append(i)

        # Keep only the last N exchanges
        if len(exchange_starts) > RECENT_EXCHANGES_IN_CONTEXT:
            trim_to = exchange_starts[-RECENT_EXCHANGES_IN_CONTEXT]
            self.working_history = self.working_history[trim_to:]

    def get_conversation_log(self, last_n: int = 5) -> str:
        """Get a readable log of the last N player exchanges from full history.
        Excludes the most recent exchange (which is already visible in working_history)."""
        exchanges = _extract_dialogue_text(self.full_history)
        # Need at least 3 entries (prior exchanges + current) to have anything useful
        if len(exchanges) < 3:
            return "No earlier conversation to recall. Use recall_memories to search past conversations."

        # Exclude the last exchange (it's the current one), take N*2 before that
        prior = exchanges[:-1]
        recent = prior[-(last_n * 2):]
        lines = []
        for ex in recent:
            if ex["role"] == "player":
                lines.append(f"Player: {ex['text']}")
            else:
                lines.append(f"You: {ex['text']}")
        return "\n".join(lines) if lines else "No earlier conversation to recall. Use recall_memories to search past conversations."

    def summarize_and_save(self):
        """Auto-save a conversation summary when the player walks away."""
        exchanges = _extract_dialogue_text(self.full_history)
        if len(exchanges) < 2:
            return

        # Build readable log
        lines = []
        for ex in exchanges[-20:]:
            role = "Player" if ex["role"] == "player" else self.npc_def["name"]
            lines.append(f"{role}: {ex['text']}")

        summary_template = _load_template("summarize_prompt.txt")
        summary_prompt = summary_template.format(
            name=self.npc_def["name"],
            conversation="\n".join(lines),
        )

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=256,
                messages=[{"role": "user", "content": summary_prompt}],
            )
            summary = response.content[0].text
            self.memory_mgr.save_memory(
                npc_id=self.npc_id,
                content=f"Conversation with the player: {summary}",
                category="episodic",
                source="self",
                importance=6,
                tags="player,conversation",
            )
            # Log conversation summary to world events so the GM knows what happened
            npc_name = self.npc_def["name"]
            self.memory_mgr.log_world_event(
                content=f"Player had a conversation with {npc_name}: {summary}",
                source_npc=self.npc_id,
                event_type="conversation_summary",
                importance=6,
                tags=f"player,{self.npc_id},conversation",
            )
        except Exception:
            self.memory_mgr.save_memory(
                npc_id=self.npc_id,
                content=f"Had a conversation with the player ({len(exchanges)} exchanges).",
                category="episodic",
                source="self",
                importance=4,
                tags="player,conversation",
            )

    MAX_SCENE_EVENTS = 10

    def _resolve_actor_for_npc(self, actor: str) -> str:
        """Resolve a system actor ID into text appropriate for this NPC's knowledge.

        For 'player': uses known_as name, or 'a person you recognize', or 'someone'.
        For NPC IDs: uses the NPC's display name.
        For 'environment': returns empty string (description stands alone).
        """
        if actor == "player":
            rel = self.memory_mgr.get_relationship(self.npc_id, "player")
            if rel:
                known_as = rel.get("known_as")
                if known_as:
                    return known_as
                return "a person you recognize"
            return "someone"
        elif actor == "environment":
            return ""
        else:
            # NPC actor — resolve to display name
            try:
                npc_def = load_npc_definition(actor)
                return npc_def["name"]
            except Exception:
                return actor

    def _build_first_message_context(self, scene_events: list = None) -> str:
        """Build automatic context for the first message of a conversation.
        Checks relationship with player, retrieves recent player-related memories,
        and injects any recent scene events with resolved actor identities."""
        parts = []

        # Check relationship
        rel = self.memory_mgr.get_relationship(self.npc_id, "player")
        if rel:
            known_as = rel.get("known_as")
            known_str = f" You know them as {known_as}." if known_as else ""
            parts.append(
                f"[Context: You know this person.{known_str} "
                f"disposition={rel['disposition']}/100, trust={rel['trust']}/100. "
                f"Notes: {rel['notes']}]"
            )
        else:
            parts.append("[Context: You have never met this person before.]")

        # Get recent player-related memories
        memories = self.memory_mgr.recall_memories(
            self.npc_id, query="player", limit=5, min_importance=5
        )
        if memories:
            parts.append("[Your recent memories about this person:]")
            for m in memories:
                parts.append(f"- {m['content']}")

        # Inject scene events with resolved actor identities
        if scene_events:
            events_to_show = scene_events[-self.MAX_SCENE_EVENTS:]
            event_lines = []
            player_was_actor = False
            for event in events_to_show:
                actor_name = self._resolve_actor_for_npc(event.actor)
                if event.actor == "environment" or not actor_name:
                    event_lines.append(f"- {event.description}")
                else:
                    event_lines.append(f"- {actor_name} {event.description}")
                if event.actor == "player":
                    player_was_actor = True

            parts.append("[Moments ago, you witnessed:]")
            parts.extend(event_lines)

            if player_was_actor:
                actor_name = self._resolve_actor_for_npc("player")
                parts.append(f"[That same person ({actor_name}) is now speaking with you.]")

        return "\n".join(parts)

    def _run_action_phase(self, system_prompt: str, tool_log: list[dict]):
        """Post-dialogue action phase: give the NPC a chance to save memories,
        send messages, and update relationships after speaking."""
        action_prompt = _load_template("action_phase_prompt.txt")

        # Build a minimal message list: just the action prompt
        # The NPC can see the recent working_history for context
        action_messages = list(self.working_history)
        action_messages.append({"role": "user", "content": action_prompt})

        max_iterations = 5
        for _ in range(max_iterations):
            response = self.client.messages.create(
                model=self.model,
                max_tokens=512,
                system=system_prompt,
                tools=ACTION_TOOLS,
                messages=action_messages,
            )
            _log_api_call(self.npc_id, system_prompt, action_messages, ACTION_TOOLS, response)

            assistant_content = response.content
            action_messages.append({"role": "assistant", "content": assistant_content})

            tool_uses = [b for b in assistant_content if b.type == "tool_use"]
            if not tool_uses:
                # Done — no more actions to take
                return

            # Execute action tools
            tool_results = []
            for tool_use in tool_uses:
                result_str = execute_tool(
                    self.npc_id, tool_use.name, tool_use.input, self.memory_mgr,
                    npc_agent=self,
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

            action_messages.append({"role": "user", "content": tool_results})

    def respond(self, player_message: str) -> tuple[str, list[dict]]:
        """
        Process a player message and return (npc_dialogue, tool_calls_log).
        Two-phase approach:
          1. Dialogue phase — NPC reads tools, thinks, responds with speech
          2. Action phase — NPC saves memories, sends messages, updates relationships
        """
        # On first message, prepend relationship/memory/scene context
        is_first_message = len(self.full_history) == 0
        if is_first_message:
            context = self._build_first_message_context(
                scene_events=self.pending_scene_events
            )
            self.pending_scene_events = []  # consumed

            # Use the name this NPC knows the player by, if any
            rel = self.memory_mgr.get_relationship(self.npc_id, "player")
            if rel and rel.get("known_as"):
                speaker_label = rel["known_as"]
            else:
                speaker_label = "The traveler"
            player_message = f"{context}\n\n{speaker_label} says: {player_message}"

        user_msg = {"role": "user", "content": player_message}
        self.full_history.append(user_msg)
        self.working_history.append(user_msg)

        # Trim before sending to keep API payload small
        self._trim_working_history()

        system_prompt = build_system_prompt(self.npc_def, self.memory_mgr)
        tool_log = []
        max_iterations = 10

        # ── Phase 1: Dialogue ──
        for _ in range(max_iterations):
            response = self.client.messages.create(
                model=self.model,
                max_tokens=1024,
                system=system_prompt,
                tools=NPC_TOOLS,
                messages=self.working_history,
            )
            _log_api_call(self.npc_id, system_prompt, self.working_history, NPC_TOOLS, response)

            assistant_content = response.content
            assistant_msg = {"role": "assistant", "content": assistant_content}
            self.full_history.append(assistant_msg)
            self.working_history.append(assistant_msg)

            tool_uses = [b for b in assistant_content if b.type == "tool_use"]
            if not tool_uses:
                text_blocks = [b.text for b in assistant_content if b.type == "text"]
                dialogue = "\n".join(text_blocks).strip()

                if len(dialogue.replace("_", "").replace("*", "").strip()) < 2:
                    nudge = {
                        "role": "user",
                        "content": (
                            "[System: You used your tools but didn't say anything to the player. "
                            "Now respond in character with actual dialogue. The player is waiting.]"
                        ),
                    }
                    self.full_history.append(nudge)
                    self.working_history.append(nudge)
                    continue

                # ── Phase 2: Actions ──
                self._run_action_phase(system_prompt, tool_log)

                return dialogue, tool_log

            # Process tool calls
            tool_results = []
            for tool_use in tool_uses:
                # Handle recall_conversation locally — it reads from full_history
                if tool_use.name == "recall_conversation":
                    last_n = min(tool_use.input.get("last_n", 5), 20)
                    result_str = self.get_conversation_log(last_n)
                else:
                    result_str = execute_tool(
                        self.npc_id, tool_use.name, tool_use.input, self.memory_mgr,
                        npc_agent=self,
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

            results_msg = {"role": "user", "content": tool_results}
            self.full_history.append(results_msg)
            self.working_history.append(results_msg)

        return "[The NPC seems lost in thought...]", tool_log
