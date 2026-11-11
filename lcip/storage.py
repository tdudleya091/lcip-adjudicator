"""JSON files in the user's data folder: scenarios/ for situations, saves/ for games in progress."""
import hashlib
import hmac
import json
import os
import secrets
import re
from pathlib import Path

from .paths import data_dir, resource_dir


def _pin_hash(pin: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", pin.encode(), salt, 200_000)


def _slug(name: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", name).strip("-").lower()
    if not slug:
        raise ValueError("Name must contain letters or numbers")
    return slug


def _write(path: Path, obj):
    """Write via a temp file so a crash never leaves a half-written save."""
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, indent=1, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def _read_all(folder: Path):
    out = []
    for p in sorted(folder.glob("*.json")):
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass  # skip unreadable files rather than block the whole list
    return out


class Storage:
    def __init__(self, root: Path | None = None):
        self.root = root or data_dir()
        self.scenarios = self.root / "scenarios"
        self.saves = self.root / "saves"
        self.scenarios.mkdir(parents=True, exist_ok=True)
        self.saves.mkdir(parents=True, exist_ok=True)
        self._install_presets()

    def _install_presets(self):
        """Write the bundled presets on first run and whenever their version goes up.

        A preset you edited is kept as <name>.json.bak before being replaced.
        """
        bundled = json.loads((resource_dir() / "data" / "scenarios.json").read_text(encoding="utf-8"))
        marker = self.root / "presets_version"
        installed = int(marker.read_text()) if marker.exists() else 0
        if installed >= bundled["version"]:
            return
        for sc in bundled["scenarios"]:
            path = self.scenarios / f"{_slug(sc['name'])}.json"
            if path.exists() and json.loads(path.read_text(encoding="utf-8")) != sc:
                os.replace(path, path.with_suffix(".json.bak"))
            self.save_scenario(sc)
        marker.write_text(str(bundled["version"]))

    # umpire PIN: stored only as a salted PBKDF2 hash. Delete umpire.json to reset it.
    def umpire_pin_set(self):
        return (self.root / "umpire.json").exists()

    def set_umpire_pin(self, pin):
        salt = secrets.token_bytes(16)
        _write(self.root / "umpire.json", {"salt": salt.hex(), "hash": _pin_hash(pin, salt).hex()})

    def check_umpire_pin(self, pin):
        rec = json.loads((self.root / "umpire.json").read_text(encoding="utf-8"))
        return hmac.compare_digest(_pin_hash(pin, bytes.fromhex(rec["salt"])).hex(), rec["hash"])

    # scenarios
    def list_scenarios(self):
        return sorted(_read_all(self.scenarios), key=lambda s: (not s.get("preset"), s["name"].lower()))

    def get_scenario(self, name):
        p = self.scenarios / f"{_slug(name)}.json"
        if not p.exists():
            raise ValueError(f"No situation named {name}")
        return json.loads(p.read_text(encoding="utf-8"))

    def save_scenario(self, sc, original_name=None):
        _write(self.scenarios / f"{_slug(sc['name'])}.json", sc)
        if original_name and _slug(original_name) != _slug(sc["name"]):
            self.delete_scenario(original_name)

    def delete_scenario(self, name):
        (self.scenarios / f"{_slug(name)}.json").unlink(missing_ok=True)

    # games
    def list_games(self):
        games = _read_all(self.saves)
        return sorted(({"id": g["id"], "scenario": g["scenario"], "turn": g["turn"], "winner": g.get("winner"),
                        "saved": g.get("saved", "")} for g in games), key=lambda g: g["saved"], reverse=True)

    def load_game(self, game_id):
        return json.loads((self.saves / f"{_slug(game_id)}.json").read_text(encoding="utf-8"))

    def save_game(self, game):
        _write(self.saves / f"{_slug(game['id'])}.json", game)

    def delete_game(self, game_id):
        (self.saves / f"{_slug(game_id)}.json").unlink(missing_ok=True)
