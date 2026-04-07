"""Main entry point — terminal-based game loop with modal prompts."""

import sys
import os
import textwrap
import shutil

# Fix Windows console encoding
if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

from src.game import GameMaster, GameMode

MARGIN = "    "

HELP_TEXT = """
  COMMANDS (work in any mode):
    /talk <name>    — Approach an NPC (e.g. /talk Greta, /talk sera)
    /leave          — Walk away from current conversation
    /look           — Describe the scene
    /examine <obj>  — Examine something (e.g. /examine notice board)
    /npcs           — List NPCs present
    /memories <npc> — View an NPC's memories (debug)
    /relations <npc>— View an NPC's relationships (debug)
    /reset          — Reset all memories and start fresh
    /help           — Show this help
    /quit           — Exit the game
"""


def wrap_text(text: str, indent: str = MARGIN) -> str:
    """Word-wrap text to fit the terminal, with consistent indentation."""
    width = shutil.get_terminal_size((80, 24)).columns
    wrap_width = max(40, width - len(indent) - 2)
    lines = []
    for paragraph in text.split("\n"):
        if not paragraph.strip():
            lines.append("")
        else:
            wrapped = textwrap.fill(
                paragraph.strip(),
                width=wrap_width,
                initial_indent=indent,
                subsequent_indent=indent,
            )
            lines.append(wrapped)
    return "\n".join(lines)


VERBOSE = os.environ.get("NPC_VERBOSE", "0") == "1"


def print_tool_log(tool_log: list[dict], source: str = "NPC"):
    """Print tool calls if verbose mode is on."""
    if not VERBOSE or not tool_log:
        return
    print(f"\n  ┌─ [{source} Internal] ─────────────────────────")
    for entry in tool_log:
        tool = entry["tool"]
        if tool == "save_memory":
            print(f"  │ 📝 Saved: {entry['input'].get('content', '')[:80]}...")
        elif tool == "update_relationship":
            target = entry["input"].get("target", "?")
            print(f"  │ 💛 Updated feelings about {target}")
        elif tool == "send_message_to_npc":
            print(f"  │ 📨 Message to {entry['input'].get('to_npc', '?')}")
        elif tool == "recall_memories":
            print(f"  │ 🔍 Searching memories for: {entry['input'].get('query', '')}")
        elif tool == "check_relationship":
            print(f"  │ 👤 Checking feelings about: {entry['input'].get('target', '?')}")
        elif tool == "look_around":
            print(f"  │ 👀 Looking around")
        elif tool == "recall_conversation":
            print(f"  │ 💬 Reviewing earlier conversation")
        elif tool == "describe_location":
            print(f"  │ 🏠 Reading location data")
        elif tool == "examine_object":
            print(f"  │ 🔎 Examining: {entry['input'].get('object_name', '?')}")
        elif tool == "get_npc_presence":
            print(f"  │ 👥 Checking who's here")
        elif tool == "get_lore":
            print(f"  │ 📖 Looking up: {entry['input'].get('query', '')}")
        elif tool == "check_world_state":
            print(f"  │ 🌍 Checking: {entry['input'].get('key', '?')}")
        elif tool == "update_world_state":
            print(f"  │ 🌍 Updated: {entry['input'].get('key', '?')}")
        elif tool == "log_scene_event":
            actor = entry['input'].get('actor', '?')
            desc = entry['input'].get('description', '')[:80]
            print(f"  │ 📢 Event [{actor}]: {desc}")
        else:
            print(f"  │ 🔧 {tool}")
    print("  └────────────────────────────────────────────\n")


def print_scene(gm: GameMaster):
    """Print the scene description from world data (no LLM)."""
    print()
    print(wrap_text(gm.get_scene_description()))
    print()


def print_gm_narration(text: str):
    """Print GM narration with formatting."""
    print()
    print(wrap_text(text))
    print()


def print_npc_dialogue(name: str, dialogue: str):
    """Print NPC dialogue with formatting."""
    print()
    print(f"{MARGIN}{name}:")
    print(f"{MARGIN}{'─' * 50}")
    print(wrap_text(dialogue))
    print(f"{MARGIN}{'─' * 50}")
    print()


def get_prompt(gm: GameMaster) -> str:
    """Return the mode-appropriate input prompt."""
    if gm.mode == GameMode.NPC_CONVERSATION and gm.current_npc:
        name = gm.get_npc_display_name(gm.current_npc)
        return f"[Speaking with {name}] You > "
    else:
        location = gm.get_location_name()
        return f"[{location}] > "


def main():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        api_key = input("Enter your Anthropic API key: ").strip()
        if not api_key:
            print("No API key provided. Exiting.")
            sys.exit(1)
        os.environ["ANTHROPIC_API_KEY"] = api_key

    gm = GameMaster(api_key=api_key)
    seeded = gm.seed_if_needed()
    if seeded:
        print("[Game initialized with fresh data]")

    # Opening scene
    print()
    print("  ╔══════════════════════════════════════════════════════════════╗")
    print("  ║                    THE RUSTY FLAGON                         ║")
    print("  ╚══════════════════════════════════════════════════════════════╝")
    print_scene(gm)
    print(HELP_TEXT)

    try:
        while True:
            try:
                user_input = input(f"\n{get_prompt(gm)}").strip()
            except EOFError:
                break

            if not user_input:
                continue

            # ── Commands (work in any mode) ──────────────────────
            if user_input.startswith("/"):
                parts = user_input.split(maxsplit=1)
                cmd = parts[0].lower()
                arg = parts[1].strip() if len(parts) > 1 else ""

                if cmd == "/quit":
                    print("\n  Farewell, traveler.")
                    break

                elif cmd == "/help":
                    print(HELP_TEXT)

                elif cmd == "/look":
                    if gm.mode == GameMode.NPC_CONVERSATION and gm.current_npc:
                        # In conversation — describe who you're talking to
                        npc_def = gm.agents[gm.current_npc].npc_def
                        print(f"\n{MARGIN}{npc_def['name']}, {npc_def['role']}.")
                        print(wrap_text(npc_def.get("appearance", "").strip()))
                    else:
                        print_scene(gm)

                elif cmd == "/examine":
                    if not arg:
                        print(f"{MARGIN}Examine what? (e.g. /examine notice board)")
                        continue
                    # Try static lookup first
                    desc = gm.gm.examine(arg)
                    if desc:
                        print_gm_narration(desc)
                    else:
                        # Fall through to GM LLM for unknown objects
                        narration, tool_log = gm.free_roam_input(f"I examine the {arg}")
                        print_tool_log(tool_log, source="GM")
                        print_gm_narration(narration)

                elif cmd == "/npcs":
                    print(f"\n{MARGIN}People here:")
                    for npc_id in gm.get_available_npcs():
                        name = gm.get_npc_display_name(npc_id)
                        marker = " <-- (talking)" if npc_id == gm.current_npc else ""
                        print(f"{MARGIN}  {name} ({npc_id}){marker}")

                elif cmd == "/talk":
                    if not arg:
                        print(f"{MARGIN}Talk to whom? (e.g. /talk Greta, /talk sera)")
                        continue
                    npc_id = gm.resolve_npc(arg)
                    if not npc_id:
                        print(f"{MARGIN}You don't see anyone by that name. Try /npcs.")
                        continue
                    gm.talk_to(npc_id)
                    gm.process_between_turns()
                    name = gm.get_npc_display_name(npc_id)
                    print(f"\n{MARGIN}[You approach {name}.]")

                elif cmd in ("/leave", "/back"):
                    if gm.mode == GameMode.NPC_CONVERSATION:
                        transition = gm.leave_conversation()
                        print(f"\n{MARGIN}{transition}")
                    else:
                        print(f"{MARGIN}You're not in a conversation.")

                elif cmd == "/memories":
                    if not arg:
                        print(f"{MARGIN}Usage: /memories <name>  (e.g. /memories Greta)")
                        continue
                    npc_id = gm.resolve_npc(arg)
                    if not npc_id:
                        print(f"{MARGIN}Unknown NPC: {arg}. Try /npcs.")
                        continue
                    name = gm.get_npc_display_name(npc_id)
                    memories = gm.memory_mgr.get_all_memories(npc_id)
                    if not memories:
                        print(f"{MARGIN}No memories found for {name}.")
                    else:
                        print(f"\n{MARGIN}── Memories for {name} ({len(memories)} total) ──")
                        for m in memories:
                            print(
                                f"{MARGIN}  [{m['category']}] (imp={m['importance']}) "
                                f"{m['content']}"
                            )

                elif cmd == "/relations":
                    if not arg:
                        print(f"{MARGIN}Usage: /relations <name>  (e.g. /relations Sera)")
                        continue
                    npc_id = gm.resolve_npc(arg)
                    if not npc_id:
                        print(f"{MARGIN}Unknown NPC: {arg}. Try /npcs.")
                        continue
                    name = gm.get_npc_display_name(npc_id)
                    rels = gm.memory_mgr.get_all_relationships(npc_id)
                    if not rels:
                        print(f"{MARGIN}No relationships found for {name}.")
                    else:
                        print(f"\n{MARGIN}── Relationships for {name} ──")
                        for r in rels:
                            known = r.get('known_as', '')
                            known_str = f" (known as: {known})" if known else ""
                            print(
                                f"{MARGIN}  {r['target']}{known_str}: disposition={r['disposition']}/100, "
                                f"trust={r['trust']}/100 — {r['notes']}"
                            )

                elif cmd == "/reset":
                    from src.database import reset_db
                    gm.shutdown()
                    reset_db()
                    gm = GameMaster(api_key=api_key)
                    gm.seed_if_needed()
                    print(f"{MARGIN}[Game reset. All memories cleared.]")
                    print_scene(gm)

                else:
                    print(f"{MARGIN}Unknown command: {cmd}. Type /help for commands.")

            # ── Freeform input ───────────────────────────────────
            else:
                if gm.mode == GameMode.NPC_CONVERSATION and gm.current_npc:
                    # Send to NPC
                    name = gm.get_npc_display_name(gm.current_npc)
                    try:
                        dialogue, tool_log = gm.player_say(user_input)
                        print_tool_log(tool_log)
                        print_npc_dialogue(name, dialogue)
                    except Exception as e:
                        print(f"\n{MARGIN}[Error communicating with {name}: {e}]")
                else:
                    # Free roam — send to GM
                    try:
                        narration, tool_log = gm.free_roam_input(user_input)
                        print_tool_log(tool_log, source="GM")
                        print_gm_narration(narration)
                    except Exception as e:
                        print(f"\n{MARGIN}[Error: {e}]")

    except KeyboardInterrupt:
        print("\n\n  Farewell, traveler.")
    finally:
        gm.shutdown()


if __name__ == "__main__":
    main()
