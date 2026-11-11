"""Unit catalog loaded from data/units.json."""
import json
from pathlib import Path

from .paths import resource_dir


class Catalog:
    def __init__(self, path: Path | None = None):
        path = path or resource_dir() / "data" / "units.json"
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        self.types = {t["id"]: t for t in raw["types"]}
        self.units = {}  # unit id ("team:name") -> {"id", "name", "team", "type"}
        for t in raw["types"]:
            t.setdefault("asw", False)
            t.setdefault("detect", None)
            slots = {s["key"] for s in t["supplies"]}
            for w in t["weapons"]:
                if w["supply"] is not None and w["supply"] not in slots:
                    raise ValueError(f"{t['id']}: weapon {w['key']} uses unknown supply slot {w['supply']}")
            for name in t["units"]:
                uid = f"{t['team']}:{name}"
                if uid in self.units:
                    raise ValueError(f"Duplicate unit {uid} in units.json")
                self.units[uid] = {"id": uid, "name": name, "team": t["team"], "type": t["id"]}

    def new_unit_state(self, uid: str) -> dict:
        info = self.units[uid]
        t = self.types[info["type"]]
        return {**info, "hp": t["hp"], "supply": {s["key"]: s["start"] for s in t["supplies"]}}

    def supply_def(self, type_id: str, key: str) -> dict:
        return next(s for s in self.types[type_id]["supplies"] if s["key"] == key)

    def to_json(self) -> dict:
        return {"types": list(self.types.values()), "units": list(self.units.values())}
