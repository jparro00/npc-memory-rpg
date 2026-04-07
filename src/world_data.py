"""World data loader — reads and caches location and lore YAML files."""

import yaml
from pathlib import Path

WORLD_DIR = Path(__file__).parent.parent / "world"
LOCATIONS_DIR = WORLD_DIR / "locations"
LORE_DIR = WORLD_DIR / "lore"

_location_cache: dict[str, dict] = {}
_lore_cache: dict[str, dict] = {}


def load_location(location_id: str) -> dict | None:
    if location_id in _location_cache:
        return _location_cache[location_id]
    path = LOCATIONS_DIR / f"{location_id}.yaml"
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    _location_cache[location_id] = data
    return data


def load_all_locations() -> dict[str, dict]:
    if _location_cache:
        return _location_cache
    if not LOCATIONS_DIR.exists():
        return {}
    for path in LOCATIONS_DIR.glob("*.yaml"):
        loc_id = path.stem
        if loc_id not in _location_cache:
            with open(path, "r", encoding="utf-8") as f:
                _location_cache[loc_id] = yaml.safe_load(f)
    return _location_cache


def load_all_lore() -> dict[str, dict]:
    if _lore_cache:
        return _lore_cache
    if not LORE_DIR.exists():
        return {}
    for path in LORE_DIR.glob("*.yaml"):
        lore_id = path.stem
        if lore_id not in _lore_cache:
            with open(path, "r", encoding="utf-8") as f:
                _lore_cache[lore_id] = yaml.safe_load(f)
    return _lore_cache


def search_lore(query: str) -> list[dict]:
    """Search lore files by keyword. Returns matching lore entries ranked by relevance."""
    keywords = query.lower().split()
    all_lore = load_all_lore()
    results = []
    for lore_id, lore in all_lore.items():
        text = f"{lore.get('name', '')} {lore.get('summary', '')} {' '.join(lore.get('details', []))}".lower()
        tags = lore.get("id", "").lower()
        hits = sum(1 for kw in keywords if kw in text or kw in tags)
        if hits > 0:
            results.append((hits, lore))
    results.sort(key=lambda x: x[0], reverse=True)
    return [entry for _, entry in results]


def get_location_description(location_id: str) -> str:
    """Render a location description from YAML data. No LLM call."""
    loc = load_location(location_id)
    if not loc:
        return "You find yourself somewhere unfamiliar."

    lines = [f"  {loc['name']}", f"  {'=' * len(loc['name'])}", ""]
    lines.append(f"  {loc['description'].strip()}")
    lines.append("")
    lines.append(f"  {loc.get('atmosphere', '').strip()}")

    objects = loc.get("objects", {})
    interactive = [k for k, v in objects.items() if v.get("interactive")]
    if interactive:
        lines.append("")
        lines.append("  You notice: " + ", ".join(
            o.replace("_", " ") for o in interactive
        ) + ".")

    exits = loc.get("exits", {})
    if exits:
        lines.append("")
        for exit_name, exit_data in exits.items():
            lines.append(f"  Exit: {exit_data['description']}")

    return "\n".join(lines)


def get_object_description(location_id: str, object_name: str) -> str | None:
    """Get a static object description from location data. Returns None if not found."""
    loc = load_location(location_id)
    if not loc:
        return None
    objects = loc.get("objects", {})
    key = object_name.lower().replace(" ", "_")
    if key in objects:
        return objects[key]["description"].strip()
    # Try partial match
    for obj_key, obj_data in objects.items():
        if key in obj_key or obj_key in key:
            return obj_data["description"].strip()
    return None


def get_npcs_at_location(location_id: str) -> list[str]:
    """Return list of NPC IDs present at a location."""
    loc = load_location(location_id)
    if not loc:
        return []
    return loc.get("npcs_present", [])
