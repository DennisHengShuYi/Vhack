"""Landmark registry — maps landmark names/aliases to (x, y) grid coordinates."""
import json
from pathlib import Path

_REGISTRY_PATH = Path(__file__).parent / "landmark_registry.json"


class LandmarkRegistry:

    def __init__(self) -> None:
        with open(_REGISTRY_PATH, encoding="utf-8") as f:
            raw = json.load(f)
        self.landmarks: list[dict] = raw
        self._index: dict[str, tuple[int, int]] = {}
        for entry in raw:
            self._index[entry["name"].lower()] = (entry["x"], entry["y"])
            for alias in entry.get("aliases", []):
                self._index[alias.lower()] = (entry["x"], entry["y"])

    def lookup(self, name: str) -> tuple[int, int] | None:
        """Return (x, y) for landmark name/alias, or None if not found."""
        return self._index.get(name.strip().lower())

    def all_names_for_prompt(self) -> str:
        """Compact representation injected into LLM grounding prompt."""
        parts = []
        for e in self.landmarks:
            aliases = "/".join(e.get("aliases", []))
            parts.append(f"{e['name']}[{aliases}]({e['x']},{e['y']})")
        return "; ".join(parts)
