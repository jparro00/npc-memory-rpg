"""Main entry point — terminal-based game loop."""

import sys
import os

# Fix Windows console encoding
if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass

from src.game import GameMaster


SCENE_INTRO = """
╔══════════════════════════════════════════════════════════════╗
║                    THE RUSTY FLAGON                         ║
╚══════════════════════════════════════════════════════════════╝

You push open the heavy oak door and step into the warmth of The Rusty
Flagon. The smell of wood smoke and stew fills the air. A few candles
flicker on rough-hewn tables.

Behind the bar, a stocky woman with silver-streaked hair polishes a mug
and looks you over with sharp eyes.

At a corner table, a wiry man in a colorful coat shuffles through papers,
glancing up as the door creaks.

Near the entrance, a tall woman in chain mail sits with perfect posture,
nursing a cup of coffee and watching you with open suspicion.

──────────────────────────────────────────────────────────────
COMMANDS:
  /talk <name>    — Talk to an NPC (barkeeper, guard, merchant)
  /look           — Describe the scene again
  /npcs           — List available NPCs
  /memories <npc> — View an NPC's memories (debug)
  /relations <npc>— View an NPC's relationships (debug)
  /reset          — Reset all memories and start fresh
  /quit           — Exit the game

Just type normally to speak to whoever you're talking to.
──────────────────────────────────────────────────────────────
"""

VERBOSE = os.environ.get("NPC_VERBOSE", "0") == "1"


def print_tool_log(tool_log: list[dict]):
    """Print tool calls if verbose mode is on."""
    if not VERBOSE or not tool_log:
        return
    print("\n  ┌─ [NPC Internal] ─────────────────────────")
    for entry in tool_log:
        tool = entry["tool"]
        if tool == "internal_monologue":
            print(f"  │ 💭 {entry['input'].get('thought', '')}")
        elif tool == "save_memory":
            print(f"  │ 📝 Saved: {entry['input'].get('content', '')[:80]}...")
        elif tool == "update_relationship":
            target = entry["input"].get("target", "?")
            print(f"  │ 💛 Updated feelings about {target}")
        elif tool == "send_message_to_npc":
            print(f"  │ 📨 Message to {entry['input'].get('to_npc', '?')}")
        elif tool == "recall_memories":
            print(f"  │ 🔍 Searching memories for: {entry['input'].get('query', '')}")
        else:
            print(f"  │ 🔧 {tool}")
    print("  └────────────────────────────────────────────\n")


def main():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("Error: Set ANTHROPIC_API_KEY environment variable first.")
        print("  export ANTHROPIC_API_KEY=sk-ant-...")
        sys.exit(1)

    gm = GameMaster(api_key=api_key)
    seeded = gm.seed_if_needed()
    if seeded:
        print("[Game initialized with fresh data]")

    print(SCENE_INTRO)

    try:
        while True:
            try:
                user_input = input("\n> ").strip()
            except EOFError:
                break

            if not user_input:
                continue

            # ── Commands ──────────────────────────────────────────
            if user_input.startswith("/"):
                parts = user_input.split(maxsplit=1)
                cmd = parts[0].lower()
                arg = parts[1].strip() if len(parts) > 1 else ""

                if cmd == "/quit":
                    print("Farewell, traveler.")
                    break

                elif cmd == "/look":
                    print(SCENE_INTRO)

                elif cmd == "/npcs":
                    print("\nAvailable NPCs:")
                    for npc_id in gm.get_available_npcs():
                        name = gm.get_npc_display_name(npc_id)
                        marker = " ← (talking)" if npc_id == gm.current_npc else ""
                        print(f"  {npc_id}: {name}{marker}")

                elif cmd == "/talk":
                    if not arg:
                        print("Usage: /talk <name>  (e.g. /talk Greta, /talk barkeeper)")
                        continue
                    npc_id = gm.resolve_npc(arg)
                    if not npc_id:
                        print(f"Unknown NPC: {arg}. Try /npcs to see available NPCs.")
                        continue
                    gm.talk_to(npc_id)
                    gm.process_between_turns()
                    name = gm.get_npc_display_name(npc_id)
                    print(f"\n[You approach {name}.]")

                elif cmd == "/memories":
                    if not arg:
                        print("Usage: /memories <name>  (e.g. /memories Greta)")
                        continue
                    npc_id = gm.resolve_npc(arg)
                    if not npc_id:
                        print(f"Unknown NPC: {arg}. Try /npcs to see available NPCs.")
                        continue
                    name = gm.get_npc_display_name(npc_id)
                    memories = gm.memory_mgr.get_all_memories(npc_id)
                    if not memories:
                        print(f"No memories found for {name}.")
                    else:
                        print(f"\n── Memories for {name} ({len(memories)} total) ──")
                        for m in memories:
                            print(
                                f"  [{m['category']}] (imp={m['importance']}) "
                                f"{m['content']}"
                            )

                elif cmd == "/relations":
                    if not arg:
                        print("Usage: /relations <name>  (e.g. /relations Sera)")
                        continue
                    npc_id = gm.resolve_npc(arg)
                    if not npc_id:
                        print(f"Unknown NPC: {arg}. Try /npcs to see available NPCs.")
                        continue
                    name = gm.get_npc_display_name(npc_id)
                    rels = gm.memory_mgr.get_all_relationships(npc_id)
                    if not rels:
                        print(f"No relationships found for {name}.")
                    else:
                        print(f"\n── Relationships for {name} ──")
                        for r in rels:
                            print(
                                f"  {r['target']}: disposition={r['disposition']}/100, "
                                f"trust={r['trust']}/100 — {r['notes']}"
                            )

                elif cmd == "/reset":
                    from src.database import reset_db
                    reset_db()
                    gm = GameMaster(api_key=api_key)
                    gm.seed_if_needed()
                    print("[Game reset. All memories cleared.]")
                    print(SCENE_INTRO)

                else:
                    print(f"Unknown command: {cmd}. Type /look for help.")

            # ── Dialogue ──────────────────────────────────────────
            else:
                if not gm.current_npc:
                    print("[You're not talking to anyone. Use /talk <name> first.]")
                    continue

                name = gm.get_npc_display_name(gm.current_npc)
                print(f"\n[{name}]")
                try:
                    dialogue, tool_log = gm.player_say(user_input)
                    print_tool_log(tool_log)
                    print(dialogue)
                except Exception as e:
                    print(f"\n[Error communicating with {name}: {e}]")

    except KeyboardInterrupt:
        print("\n\nFarewell, traveler.")
    finally:
        gm.shutdown()


if __name__ == "__main__":
    main()
