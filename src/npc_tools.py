"""Tool definitions for NPC agents — these are what the LLM can call during interactions."""

# Anthropic API tool schema format
NPC_TOOLS = [
    {
        "name": "save_memory",
        "description": (
            "Save something to your long-term memory. Use this to remember important "
            "facts, events, promises, or impressions from this conversation. Be selective — "
            "only save things worth remembering later."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "What you want to remember. Write it as a clear, self-contained note.",
                },
                "category": {
                    "type": "string",
                    "enum": ["episodic", "semantic", "social"],
                    "description": (
                        "episodic = a specific event or interaction that happened. "
                        "semantic = a general fact or belief you've formed. "
                        "social = something about a person or relationship."
                    ),
                },
                "importance": {
                    "type": "integer",
                    "description": "1-10 how important this is to remember. 1=trivial, 5=notable, 10=critical.",
                },
                "tags": {
                    "type": "string",
                    "description": "Comma-separated tags for later retrieval (e.g. 'player,quest,mine').",
                },
            },
            "required": ["content", "category", "importance"],
        },
    },
    {
        "name": "recall_memories",
        "description": (
            "Search your memories for something specific. Use this when the conversation "
            "touches on something you might have encountered before."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Keywords to search for in your memories.",
                },
                "category": {
                    "type": "string",
                    "enum": ["episodic", "semantic", "social"],
                    "description": "Optionally filter by memory type.",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "update_relationship",
        "description": (
            "Update how you feel about someone based on this interaction. "
            "Disposition is how much you like them (0=hostile, 50=neutral, 100=devoted). "
            "Trust is how much you believe them (0=total distrust, 50=neutral, 100=complete trust)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": "Who this is about (e.g. 'player', 'barkeeper', 'guard').",
                },
                "disposition": {
                    "type": "integer",
                    "description": "0-100 how much you like/dislike them.",
                },
                "trust": {
                    "type": "integer",
                    "description": "0-100 how much you trust them.",
                },
                "notes": {
                    "type": "string",
                    "description": "Brief note about why your feelings changed.",
                },
            },
            "required": ["target"],
        },
    },
    {
        "name": "send_message_to_npc",
        "description": (
            "Send a message to another NPC. They will receive it later — this represents "
            "you telling them something when you next see them, or sending word through "
            "the usual channels. Use this to share gossip, warnings, or information."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "to_npc": {
                    "type": "string",
                    "description": "The NPC to send the message to (e.g. 'barkeeper', 'guard', 'merchant').",
                },
                "content": {
                    "type": "string",
                    "description": "What you want to tell them. Write it in your own voice.",
                },
            },
            "required": ["to_npc", "content"],
        },
    },
    {
        "name": "internal_monologue",
        "description": (
            "Think privately to yourself. The player will NOT see this. Use this to "
            "reason about what you know, what you suspect, whether to trust the player, "
            "or what to say next. This is your inner voice."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "thought": {
                    "type": "string",
                    "description": "Your private thought.",
                },
            },
            "required": ["thought"],
        },
    },
    {
        "name": "recall_conversation",
        "description": (
            "Recall earlier parts of your current conversation with the player. "
            "You can only see the last couple of exchanges by default. Use this "
            "to look back further — for example if the player says 'like I said earlier' "
            "or you need to remember what was discussed a few minutes ago."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "last_n": {
                    "type": "integer",
                    "description": "How many previous player exchanges to retrieve (default 5, max 20).",
                },
            },
            "required": [],
        },
    },
]
