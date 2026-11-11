"""The methods JavaScript can call. Same object serves pywebview's bridge and the browser fallback.

Every public method returns {"ok": True, "data": ...} or {"ok": False, "error": message},
so rule violations show up as messages in the UI instead of crashing it.
"""
import copy
import functools
import traceback
from datetime import datetime

from . import engine
from .catalog import Catalog
from .engine import RuleError
from .storage import Storage

UNDO_DEPTH = 30
LOG_LIMIT = 500


def _endpoint(fn):
    @functools.wraps(fn)
    def wrapper(self, *args):
        try:
            return {"ok": True, "data": fn(self, *args)}
        except (RuleError, ValueError, KeyError) as e:
            return {"ok": False, "error": str(e)}
        except Exception as e:  # unexpected: keep the app alive, print for debugging
            traceback.print_exc()
            return {"ok": False, "error": f"Internal error: {e}"}
    return wrapper


class Api:
    def __init__(self, catalog: Catalog | None = None, storage: Storage | None = None):
        self._cat = catalog or Catalog()
        self._store = storage or Storage()
        self._game = None
        self._undo = []
        self._umpire = False  # umpire mode unlocks direct edits of any game value; resets on restart

    # ------------------------------------------------------------ umpire mode

    @_endpoint
    def umpire_status(self):
        return {"unlocked": self._umpire, "pin_set": self._store.umpire_pin_set()}

    @_endpoint
    def umpire_unlock(self, pin):
        """The first unlock sets the PIN; later unlocks must match it."""
        pin = str(pin or "")
        if not self._store.umpire_pin_set():
            if len(pin) < 4:
                raise RuleError("Choose an umpire PIN of at least 4 characters")
            self._store.set_umpire_pin(pin)
        elif not self._store.check_umpire_pin(pin):
            raise RuleError("Wrong umpire PIN")
        self._umpire = True
        return {"unlocked": True, "pin_set": True}

    @_endpoint
    def umpire_lock(self):
        self._umpire = False
        return {"unlocked": False, "pin_set": self._store.umpire_pin_set()}

    # ------------------------------------------------------------ catalog & scenarios

    @_endpoint
    def catalog(self):
        return self._cat.to_json()

    @_endpoint
    def list_scenarios(self):
        return self._store.list_scenarios()

    @_endpoint
    def save_scenario(self, sc, original_name=None):
        self._store.save_scenario(self._validate_scenario(sc), original_name)
        return self._store.list_scenarios()

    @_endpoint
    def delete_scenario(self, name):
        self._store.delete_scenario(name)
        return self._store.list_scenarios()

    def _validate_scenario(self, sc):
        name = str(sc.get("name", "")).strip()
        if not name:
            raise ValueError("Give the situation a name")
        ini = sc.get("initiative", {})
        try:
            ini = {k: int(ini.get(k, d)) for k, d in (("start", 0), ("blue_wins_at", 10), ("red_wins_at", -10))}
        except (TypeError, ValueError):
            raise ValueError("Initiative values must be whole numbers") from None
        if not ini["red_wins_at"] < ini["start"] < ini["blue_wins_at"]:
            raise ValueError("Initiative start must sit between the Red and Blue win values")
        tfs, seen = [], {}
        for tf in sc.get("task_forces", []):
            tf_name = str(tf.get("name", "")).strip()
            if not tf_name:
                raise ValueError("Every task force needs a name")
            if tf.get("team") not in ("blue", "red"):
                raise ValueError(f"{tf_name}: team must be blue or red")
            for uid in tf.get("units", []):
                info = self._cat.units.get(uid)
                if info is None:
                    raise ValueError(f"Unknown unit {uid}")
                if info["team"] != tf["team"]:
                    raise ValueError(f"{info['name']} is not a {tf['team']} unit")
                if uid in seen:
                    raise ValueError(f"{info['name']} is in both {seen[uid]} and {tf_name}")
                seen[uid] = tf_name
            entry = {"name": tf_name, "team": tf["team"], "units": list(tf.get("units", []))}
            if tf.get("requires_landing"):
                entry["requires_landing"] = True
            tfs.append(entry)
        if len(tfs) < 2:
            raise ValueError("A situation needs at least two task forces")
        if len({tf["name"] for tf in tfs}) != len(tfs):
            raise ValueError("Task force names must be unique")
        return {"name": name, "map": str(sc.get("map", "")).strip(), "preset": bool(sc.get("preset")),
                "initiative": ini, "task_forces": tfs}

    # ------------------------------------------------------------ games

    @_endpoint
    def list_games(self):
        return self._store.list_games()

    @_endpoint
    def new_game(self, scenario_name):
        sc = self._store.get_scenario(scenario_name)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        self._game = engine.new_game(self._cat, sc, f"{stamp}-{sc['name']}")
        self._undo = []
        self._log("Game started", [engine.ev("info", "Players choose the turn order for round 1")])
        self._save()
        return self._view()

    @_endpoint
    def load_game(self, game_id):
        self._game = self._store.load_game(game_id)
        self._game.setdefault("phase", "engage")  # saves from before turn phases existed
        self._undo = []
        return self._view()

    @_endpoint
    def delete_game(self, game_id):
        self._store.delete_game(game_id)
        if self._game and self._game["id"] == game_id:
            self._game = None
        return self._store.list_games()

    @_endpoint
    def game(self):
        return self._view()

    @_endpoint
    def undo(self):
        if not self._undo:
            raise RuleError("Nothing to undo")
        self._game = self._undo.pop()
        self._save()
        return self._view()

    @_endpoint
    def action(self, kind, p):
        """Run one game action. Snapshot first so Undo can restore it; nothing changes on a rule error."""
        g = self._require_game()
        if g.get("winner") and kind != "umpire":
            raise RuleError(f"The game is over: {g['winner'].title()} won")
        snapshot = copy.deepcopy(g)
        when = (snapshot["turn"], snapshot["task_forces"][snapshot["active_tf"]]["name"])  # log under who acted
        cat = self._cat
        try:
            if kind == "lrs":
                title, events = "Long-range strike", engine.long_range_strike(g, cat, p.get("attacks", []), p.get("intercepts", []))
            elif kind == "close":
                title, events = "Close combat", engine.close_combat(g, cat, p.get("attackers", []), p.get("defender", {}))
            elif kind == "asw":
                title, events = "ASW attack", engine.asw_attack(g, cat, p.get("hunter"), p.get("sub"))
            elif kind == "torpedo":
                title, events = "Torpedo attack", engine.torpedo_attack(g, cat, p.get("sub"), p.get("target"), p.get("distance"))
            elif kind == "resupply":
                title, events = "Resupply", engine.resupply(g, cat, p.get("from"), p.get("to"), p.get("slot"), p.get("amount"))
            elif kind == "umpire":
                if not self._umpire:
                    raise RuleError("Only the umpire can do that. Unlock umpire mode first.")
                title, events = "Umpire edit", engine.umpire_edit(g, cat, p)
            elif kind == "round_order":
                title, events = "Turn order set", engine.set_round_order(g, p.get("order"))
            elif kind == "end_engagements":
                title, events = "Engagements done", engine.end_engagements(g)
            elif kind == "initiative":
                title, events = "Initiative", engine.adjust_initiative(g, p.get("delta", 0))
            elif kind == "end_turn":
                tf = g["task_forces"][g["active_tf"]]["name"]
                title, events = f"{tf} ends turn", engine.end_turn(g)
            else:
                raise RuleError(f"Unknown action {kind}")
        except Exception:
            self._game = snapshot  # roll back any partial change
            raise
        self._undo.append(snapshot)
        del self._undo[:-UNDO_DEPTH]
        self._log(title, events, when)
        self._save()
        return {"events": events, "game": self._view()}

    # ------------------------------------------------------------ helpers

    def _require_game(self):
        if self._game is None:
            raise RuleError("No game loaded")
        return self._game

    def _log(self, title, events, when=None):
        g = self._game
        turn, tf = when or (g["turn"], g["task_forces"][g["active_tf"]]["name"])
        g["log"].append({"turn": turn, "tf": tf, "title": title, "events": events})
        del g["log"][:-LOG_LIMIT]

    def _save(self):
        self._game["saved"] = datetime.now().isoformat(timespec="seconds")
        self._store.save_game(self._game)

    def _view(self):
        """Game state plus everything the UI needs to draw each unit without knowing the rules."""
        g = self._require_game()
        cat = self._cat
        units = {}
        for uid, u in g["units"].items():
            t = cat.types[u["type"]]
            tf = engine.task_force_of(g, uid)
            units[uid] = {
                **u,
                "type_label": t["label"], "category": t["category"], "asw": t["asw"], "detect": t["detect"],
                "max_hp": t["hp"], "alive": engine.is_alive(u), "in_play": tf is None or engine.tf_in_play(tf),
                "supplies": [{"key": s["key"], "label": s["label"], "value": u["supply"][s["key"]], "cap": s["start"]}
                             for s in t["supplies"]],
                "weapons": [{**w, "left": engine.supply_left(u, w)} for w in t["weapons"]],
                "messages": engine.supply_report(cat, u),
            }
        return {**{k: v for k, v in g.items() if k != "log"}, "units": units,
                "task_forces": [{**tf, "in_play": engine.tf_in_play(tf), "playable": engine.playable(g, tf)}
                                for tf in g["task_forces"]],
                "log": g["log"][-100:], "can_undo": bool(self._undo), "umpire": self._umpire}
