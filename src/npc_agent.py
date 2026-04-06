"""NPC Agent — runs a single NPC's turn using the Anthropic API with tool use."""

import yaml
import anthropic
from pathlib import Path
from typing import Optional

from .memory import MemoryManager
from .npc_tools import NPC_TOOLS

NPCS_DIR = Path(__file__).parent.parent / "npcs"

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


def build_scene_context(current_npc_id: str) -> str:
    """Build awareness of other NPCs present in the scene."""
    all_npcs = load_all_npc_definitions()
    others = []
    for npc_id, npc_def in all_npcs.items():
        if npc_id == current_npc_id:
            continue
        others.append(
            f"- {npc_def['name']} ({npc_id}): {npc_def['role']}. "
            f"{npc_def.get('appearance', '').strip().split(chr(10))[0]}"
        )
    if not others:
        return ""
    return "\n## Other People Present\n" + "\n".join(others) + "\n"


def build_memory_context(npc_id: str, memory_mgr: MemoryManager) -> str:
    """Build memory section with stratified retrieval — base knowledge stays in YAML,
    this loads conversation memories, learned facts, and social observations separately."""
    sections = []

    # High-importance memories (things the NPC decided were important)
    important = memory_mgr.recall_memories(
        npc_id, category=None, limit=10, min_importance=7
    )
    # Filter out base_knowledge since that's already in the YAML
    important = [m for m in important if m["source"] != "base_knowledge"]
    if important:
        sections.append("## Important Things You Remember")
        for m in important:
            sections.append(f"- {m['content']}")

    # Recent episodic memories (what happened recently)
    recent_episodic = memory_mgr.recall_memories(
        npc_id, category="episodic", limit=10, min_importance=1
    )
    if recent_episodic:
        sections.append("\n## Recent Events You Recall")
        for m in recent_episodic:
            sections.append(f"- {m['content']}")

    # Social memories (things learned about people)
    social = memory_mgr.recall_memories(
        npc_id, category="social", limit=10, min_importance=1
    )
    if social:
        sections.append("\n## Things You've Heard About People")
        for m in social:
            src = f" (from {m['source']})" if m["source"] not in ("self", "observation") else ""
            sections.append(f"- {m['content']}{src}")

    # Learned facts beyond base knowledge
    semantic = memory_mgr.recall_memories(
        npc_id, category="semantic", limit=10, min_importance=1
    )
    semantic = [m for m in semantic if m["source"] != "base_knowledge"]
    if semantic:
        sections.append("\n## Things You've Learned")
        for m in semantic:
            sections.append(f"- {m['content']}")

    if not sections:
        return ""
    return "\n" + "\n".join(sections) + "\n"


def build_system_prompt(npc_def: dict, memory_mgr: MemoryManager) -> str:
    """Construct the full system prompt for an NPC, including identity, memories, and relationships."""
    npc_id = npc_def["id"]

    # Scene awareness — who else is here
    scene_text = build_scene_context(npc_id)

    # Stratified memory loading
    memory_text = build_memory_context(npc_id, memory_mgr)

    # Relationships
    relationships = memory_mgr.get_all_relationships(npc_id)
    rel_text = ""
    if relationships:
        rel_text = "\n## Your Current Relationships\n"
        for r in relationships:
            rel_text += (
                f"- {r['target']}: disposition={r['disposition']}/100, "
                f"trust={r['trust']}/100. {r['notes']}\n"
            )

    # Pending messages from other NPCs
    messages = memory_mgr.get_pending_messages(npc_id)
    msg_text = ""
    if messages:
        msg_text = "\n## Messages You've Received\n"
        msg_text += "These are things other NPCs have told you since your last conversation:\n"
        for msg in messages:
            msg_text += f"- From {msg['from_npc']}: {msg['content']}\n"
        memory_mgr.mark_messages_delivered(npc_id)

    # Base knowledge from YAML
    knowledge_text = "\n## What You Know\n"
    for fact in npc_def.get("base_knowledge", []):
        knowledge_text += f"- {fact}\n"

    # Available NPCs for send_message_to_npc
    all_npcs = load_all_npc_definitions()
    npc_ids = [nid for nid in all_npcs if nid != npc_id]
    npc_list = ", ".join(npc_ids)

    system = f"""You are {npc_def['name']}, {npc_def['role']}.

## Your Personality
{npc_def['personality']}

## Your Appearance
{npc_def['appearance']}

## How You Speak
{npc_def['dialogue_style']}
{scene_text}{knowledge_text}{memory_text}{rel_text}{msg_text}
## Instructions
Stay in character. Respond with dialogue and brief actions (e.g., *wipes down the bar*).
Keep responses to a few sentences — this is a game, not a novel.

**Each turn:** Think (internal_monologue) → recall if relevant → respond → save what happened.

**Memory is critical.** Anything you don't save_memory will be forgotten permanently.
Save: what the player told you, impressions, promises, facts learned.
Categories: episodic=events, semantic=facts, social=about people.
Importance: chitchat=2-3, useful=5-6, critical=8-10.

**You only see the last few exchanges.** Use recall_conversation to look back further
if the player references something from earlier. Use recall_memories for past conversations.

**Other tools:** update_relationship when feelings change. send_message_to_npc to share
info with NPCs you trust ({npc_list}). Never break character.
"""
    return system


def execute_tool(npc_id: str, tool_name: str, tool_input: dict, memory_mgr: MemoryManager) -> str:
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

    elif tool_name == "update_relationship":
        rel = memory_mgr.update_relationship(
            npc_id=npc_id,
            target=tool_input["target"],
            disposition=tool_input.get("disposition"),
            trust=tool_input.get("trust"),
            notes=tool_input.get("notes"),
        )
        return f"Relationship updated: disposition={rel['disposition']}, trust={rel['trust']}."

    elif tool_name == "send_message_to_npc":
        msg_id = memory_mgr.send_message(
            from_npc=npc_id,
            to_npc=tool_input["to_npc"],
            content=tool_input["content"],
        )
        return f"Message sent to {tool_input['to_npc']} (id={msg_id})."

    elif tool_name == "internal_monologue":
        # Just acknowledge — the thought is in the conversation context already
        return "You think to yourself."

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

    def reset_conversation(self):
        self.full_history = []
        self.working_history = []

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
        """Get a readable log of the last N player exchanges from full history."""
        exchanges = _extract_dialogue_text(self.full_history)
        if not exchanges:
            return "No prior conversation to recall."

        # Take last N*2 entries (player + npc pairs)
        recent = exchanges[-(last_n * 2):]
        lines = []
        for ex in recent:
            if ex["role"] == "player":
                lines.append(f"Player: {ex['text']}")
            else:
                lines.append(f"You: {ex['text']}")
        return "\n".join(lines) if lines else "No prior conversation to recall."

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

        summary_prompt = (
            f"You are {self.npc_def['name']}. Summarize this conversation in 2-3 sentences "
            f"from your perspective. Focus on: what you learned, what you told the player, "
            f"any promises made, and your impression of the player. Be specific about facts.\n\n"
            + "\n".join(lines)
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
        except Exception:
            self.memory_mgr.save_memory(
                npc_id=self.npc_id,
                content=f"Had a conversation with the player ({len(exchanges)} exchanges).",
                category="episodic",
                source="self",
                importance=4,
                tags="player,conversation",
            )

    def respond(self, player_message: str) -> tuple[str, list[dict]]:
        """
        Process a player message and return (npc_dialogue, tool_calls_log).
        Handles the full agent loop: send message, process tool calls, repeat until done.
        """
        user_msg = {"role": "user", "content": player_message}
        self.full_history.append(user_msg)
        self.working_history.append(user_msg)

        # Trim before sending to keep API payload small
        self._trim_working_history()

        system_prompt = build_system_prompt(self.npc_def, self.memory_mgr)
        tool_log = []
        max_iterations = 10

        for _ in range(max_iterations):
            response = self.client.messages.create(
                model=self.model,
                max_tokens=1024,
                system=system_prompt,
                tools=NPC_TOOLS,
                messages=self.working_history,
            )

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
                        self.npc_id, tool_use.name, tool_use.input, self.memory_mgr
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
