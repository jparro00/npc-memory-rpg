"""Reduced tool set for the post-dialogue action phase. Only write/send tools."""

ACTION_TOOLS = [
    {
        "name": "save_memory",
        "description": (
            "Save something to your long-term memory. You WILL forget anything you don't save."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "What you want to remember.",
                },
                "category": {
                    "type": "string",
                    "enum": ["episodic", "semantic", "social"],
                    "description": "episodic=event, semantic=fact, social=about a person.",
                },
                "importance": {
                    "type": "integer",
                    "description": "1-10. 2-3 trivial, 5-6 useful, 8-10 critical.",
                },
                "tags": {
                    "type": "string",
                    "description": "Comma-separated tags.",
                },
            },
            "required": ["content", "category", "importance"],
        },
    },
    {
        "name": "update_relationship",
        "description": (
            "Update how you feel about someone. "
            "Disposition: 0=hostile, 50=neutral, 100=devoted. "
            "Trust: 0=distrust, 50=neutral, 100=complete trust."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": "Who this is about.",
                },
                "disposition": {
                    "type": "integer",
                    "description": "0-100.",
                },
                "trust": {
                    "type": "integer",
                    "description": "0-100.",
                },
                "notes": {
                    "type": "string",
                    "description": "Brief note about why.",
                },
            },
            "required": ["target"],
        },
    },
    {
        "name": "send_message_to_npc",
        "description": (
            "Send a message to another NPC. Use this if you promised to tell someone "
            "something or want to pass along information."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "to_npc": {
                    "type": "string",
                    "description": "The NPC to message (e.g. 'barkeeper', 'guard', 'merchant', 'barmaid').",
                },
                "content": {
                    "type": "string",
                    "description": "What you want to tell them, in your own voice.",
                },
            },
            "required": ["to_npc", "content"],
        },
    },
]
