"""Tool definitions for the GM (Game Master) agent."""

GM_TOOLS = [
    {
        "name": "describe_location",
        "description": (
            "Get the full description of a location including atmosphere, "
            "notable objects, and exits. Use this to ground your narration "
            "in concrete details."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "location_id": {
                    "type": "string",
                    "description": "The location to describe (e.g. 'rusty_flagon').",
                },
            },
            "required": ["location_id"],
        },
    },
    {
        "name": "examine_object",
        "description": (
            "Get the detailed description of a specific object at the current location. "
            "Use this when the player wants to examine or interact with something."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "object_name": {
                    "type": "string",
                    "description": "The object to examine (e.g. 'notice_board', 'fireplace', 'bar').",
                },
            },
            "required": ["object_name"],
        },
    },
    {
        "name": "get_npc_presence",
        "description": (
            "See who is present at the current location. Returns NPC names, "
            "roles, and brief appearance descriptions."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "get_lore",
        "description": (
            "Search world lore and background information by keyword. Use this "
            "when narrating about the town, its history, the mine, or other "
            "world details the player might observe or investigate."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Keywords to search for (e.g. 'silver mine', 'millhaven').",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "check_world_state",
        "description": (
            "Check a world state variable. Use this to see if something has "
            "already happened or changed (e.g. 'notice_board_read', 'time_of_day')."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "The world state key to check.",
                },
            },
            "required": ["key"],
        },
    },
    {
        "name": "update_world_state",
        "description": (
            "Update a world state variable to record that something has changed "
            "or happened. Only use this for meaningful changes to the environment."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "The world state key to set.",
                },
                "value": {
                    "type": "string",
                    "description": "The new value.",
                },
            },
            "required": ["key", "value"],
        },
    },
    {
        "name": "log_scene_event",
        "description": (
            "Record a significant event that everyone in the scene would witness. "
            "Call this for impactful player actions, dramatic environmental changes, "
            "or observable NPC reactions you narrated (body language only, not dialogue). "
            "Events should be factual, third-person, and brief."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "description": {
                    "type": "string",
                    "description": (
                        "What happened, in factual third person. "
                        "E.g. 'Drove a hatchet into the tavern wall, splintering boards.' "
                        "or 'The barkeeper flinched and stepped back from the bar.'"
                    ),
                },
                "actor": {
                    "type": "string",
                    "description": (
                        "Who performed the action: 'player', an npc_id like "
                        "'barkeeper', or 'environment' for natural events."
                    ),
                },
            },
            "required": ["description", "actor"],
        },
    },
    {
        "name": "create_npc",
        "description": (
            "Create a new NPC character in the current scene. Use this when the "
            "narrative naturally introduces a new character who doesn't already exist "
            "(a traveler walks in, a townsfolk is mentioned and needs to become "
            "interactable). Check get_npc_presence first to avoid duplicates. "
            "Keep personality, appearance, and dialogue_style to 2-3 sentences each."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "id": {
                    "type": "string",
                    "description": (
                        "Unique snake_case identifier, e.g. 'old_finn', 'hooded_stranger'. "
                        "Lowercase letters, digits, and underscores only."
                    ),
                },
                "name": {
                    "type": "string",
                    "description": "Display name, e.g. 'Old Finn'.",
                },
                "role": {
                    "type": "string",
                    "description": "Brief role, e.g. 'Retired soldier and tavern regular'.",
                },
                "personality": {
                    "type": "string",
                    "description": "2-3 sentences describing personality and demeanor.",
                },
                "appearance": {
                    "type": "string",
                    "description": "2-3 sentences describing physical appearance.",
                },
                "dialogue_style": {
                    "type": "string",
                    "description": (
                        "2-3 sentences describing how they speak: sentence length, "
                        "vocabulary, verbal tics, accent, body language during conversation. "
                        "E.g. 'Speaks in short, clipped sentences. Avoids eye contact. "
                        "Taps the table when nervous.'"
                    ),
                },
                "base_knowledge": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Facts this NPC knows — their backstory, what brought them here, "
                        "opinions, rumors they've heard. Include at least 3-5 facts so "
                        "the NPC has something to talk about."
                    ),
                },
            },
            "required": ["id", "name", "role", "personality", "appearance", "dialogue_style", "base_knowledge"],
        },
    },
    {
        "name": "start_conversation",
        "description": (
            "Start a conversation between the player and an NPC. Use this when "
            "the player wants to talk to someone — e.g. 'talk to this girl', "
            "'I want to speak with the merchant', 'can I ask her something'. "
            "Use get_npc_presence first if you need to identify who the player means."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "npc_id": {
                    "type": "string",
                    "description": "The npc_id of the character to talk to (e.g. 'barkeeper', 'barmaid').",
                },
            },
            "required": ["npc_id"],
        },
    },
    {
        "name": "recall_world_events",
        "description": (
            "Search the world event log for significant things that have happened "
            "in the game — NPC conversations, dramatic events, plot developments. "
            "Use this when you need context about what the player has been doing, "
            "who they've talked to, or what has happened in the world."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Keywords to search for (e.g. 'goblin mines', 'cindy', 'burglars').",
                },
            },
            "required": ["query"],
        },
    },
]
