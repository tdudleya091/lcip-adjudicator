"""Rules tests with scripted dice, so every branch of the pseudocode is checked deterministically."""
import pytest

from lcip import engine
from lcip.api import Api
from lcip.catalog import Catalog
from lcip.engine import RuleError
from lcip.storage import Storage

CAT = Catalog()


class Dice:
    """Returns the given rolls in order and fails if the engine rolls more than expected."""
    def __init__(self, *rolls):
        self.rolls = list(rolls)

    def randint(self, a, b):
        assert self.rolls, "engine rolled more dice than the test expected"
        return self.rolls.pop(0)


def game(blue, red, blue2=()):
    tfs = [{"name": "TF Miami", "team": "blue", "units": [f"blue:{n}" for n in blue]},
           {"name": "TF Beijing", "team": "red", "units": [f"red:{n}" for n in red]}]
    if blue2:
        tfs.append({"name": "TF SF", "team": "blue", "units": [f"blue:{n}" for n in blue2]})
    sc = {"name": "t", "initiative": {"start": 0, "blue_wins_at": 3, "red_wins_at": -3}, "task_forces": tfs}
    g = engine.new_game(CAT, sc, "t")
    engine.set_round_order(g, range(len(tfs)))  # rule tests start mid-round in listed order
    return g


def test_catalog_starting_values():
    ddg = CAT.new_unit_state("blue:DDG-56")
    assert ddg["hp"] == 2 and ddg["supply"] == {"s1": 10, "s2": 10, "s3": 4}
    assert CAT.new_unit_state("red:T-55-103")["supply"] == {"s1": 16, "s2": 9, "s3": 6}
    assert CAT.types["red_sub_shang"]["detect"] == 16


def test_lrs_hit_miss_and_intercept():
    g = game(["DDG-56"], ["T-54-573"])
    # shot1 roll 3 on target -> intercept roll 15 fails -> hit; shot2 roll 20 miss; shot3 on target -> intercepted (5<=12)
    ev = engine.long_range_strike(g, CAT,
                                  [{"shooter": "blue:DDG-56", "weapon": "lrs", "target": "red:T-54-573", "shots": 3}],
                                  [{"unit": "red:T-54-573", "weapon": "intercept", "attempts": 4}], Dice(3, 15, 20, 7, 5))
    assert g["units"]["red:T-54-573"]["hp"] == 1
    assert g["units"]["blue:DDG-56"]["supply"]["s1"] == 7
    assert g["units"]["red:T-54-573"]["supply"]["s2"] == 2  # all 4 declared attempts cost supply (only 2 rolled)
    assert any(e["kind"] == "intercept" for e in ev)


def test_lrs_without_intercepts_hits_and_stops_at_dead_target():
    g = game(["DDGX-101"], ["2:1 Echo"])
    engine.long_range_strike(g, CAT, [{"shooter": "blue:DDGX-101", "weapon": "lrs", "target": "red:2:1 Echo", "shots": 5}],
                             [], Dice(1, 1))
    assert g["units"]["red:2:1 Echo"]["hp"] == 0
    assert g["units"]["blue:DDGX-101"]["supply"]["s1"] == 10  # all 5 declared shots cost supply, 3 wasted


def test_best_intercept_used_first():
    g = game(["1:1 Charlie"], ["T-76-201", "T-52-172"])
    engine.long_range_strike(g, CAT, [{"shooter": "blue:1:1 Charlie", "weapon": "lrs1", "target": "red:T-52-172", "shots": 1}],
                             [{"unit": "red:T-76-201", "weapon": "intercept", "attempts": 5},
                              {"unit": "red:T-52-172", "weapon": "intercept", "attempts": 1}], Dice(2, 10))
    # T-52 (≤14) outranks T-76 (≤4), so it rolls first: 10 ≤ 14 intercepts
    assert g["units"]["red:T-52-172"]["supply"]["s2"] == 6
    assert g["units"]["red:T-52-172"]["hp"] == 2


def test_lrs_rejects_over_supply_and_friendly_fire():
    g = game(["1 Alpha", "2 Alpha"], ["1 Lima"])
    with pytest.raises(RuleError, match="needs 2"):
        engine.long_range_strike(g, CAT, [{"shooter": "blue:1 Alpha", "weapon": "lrs", "target": "red:1 Lima", "shots": 2}], [])
    with pytest.raises(RuleError, match="same team"):
        engine.long_range_strike(g, CAT, [{"shooter": "blue:1 Alpha", "weapon": "lrs", "target": "blue:2 Alpha", "shots": 1}], [])


def test_close_combat_rounds():
    g = game(["1:1 Bravo", "1 Alpha"], ["1 Fox"])
    # round 1: Bravo 2 (hit), Alpha 19 (miss), Fox fires at Bravo 1 (hit); round 2: Bravo 4 (hit) -> Fox dead
    ev = engine.close_combat(g, CAT, [{"unit": "blue:1:1 Bravo", "shots": 3}, {"unit": "blue:1 Alpha", "shots": 1}],
                             {"unit": "red:1 Fox", "shots": 2}, Dice(2, 19, 1, 4))
    assert g["units"]["red:1 Fox"]["hp"] == 0
    assert g["units"]["blue:1:1 Bravo"]["hp"] == 1
    assert g["units"]["blue:1:1 Bravo"]["supply"]["s1"] == 2   # declared 3 (fired 2): all 3 spent
    assert g["units"]["red:1 Fox"]["supply"]["s1"] == 3        # declared 2 (fired 1): both spent
    assert any(e["kind"] == "kill" for e in ev)
    assert "2 shot(s) not fired" in ev[-1]["text"]


def test_close_combat_attack_stops_when_attackers_die():
    g = game(["1 Alpha"], ["1 Delta"])
    g["units"]["blue:1 Alpha"]["hp"] = 1
    ev = engine.close_combat(g, CAT, [{"unit": "blue:1 Alpha", "shots": 3}], {"unit": "red:1 Delta", "shots": 3}, Dice(20, 1))
    assert g["units"]["blue:1 Alpha"]["hp"] == 0
    assert any("attack stops" in e["text"] for e in ev)
    assert g["units"]["red:1 Delta"]["supply"]["s1"] == 2      # declared 3, fired 1


def test_asw_detect_then_kill_or_evade():
    g = game(["DDG-56"], ["Sui-1"])
    engine.asw_attack(g, CAT, "blue:DDG-56", "red:Sui-1", Dice(14))         # 14 > 13: not detected
    assert g["units"]["red:Sui-1"]["hp"] == 1
    engine.asw_attack(g, CAT, "blue:DDG-56", "red:Sui-1", Dice(13, 11))     # detected, 11 > 10 evades
    assert g["units"]["red:Sui-1"]["hp"] == 1
    engine.asw_attack(g, CAT, "blue:DDG-56", "red:Sui-1", Dice(1, 10))      # detected, sunk
    assert g["units"]["red:Sui-1"]["hp"] == 0


def test_torpedo_asw_target_checks_first_and_torpedoes_are_unlimited():
    g = game(["Virginia"], ["T-55-102", "T-76-201"])
    engine.torpedo_attack(g, CAT, "blue:Virginia", "red:T-55-102", 2, Dice(8, 3))  # undetected (8>7), torpedo hits
    assert g["units"]["red:T-55-102"]["hp"] == 1
    engine.torpedo_attack(g, CAT, "blue:Virginia", "red:T-76-201", 1, Dice(14))  # no ASW: straight to torpedo, 14 ≤ 14
    assert g["units"]["red:T-76-201"]["hp"] == 1
    assert g["units"]["blue:Virginia"]["supply"]["s1"] == 6  # torpedoes cost nothing; s1 is LRS only
    g["units"]["blue:Virginia"]["supply"]["s1"] = 0
    engine.torpedo_attack(g, CAT, "blue:Virginia", "red:T-55-102", 1, Dice(2, 5))  # still fires with 0 LRS supply; sunk first
    assert g["units"]["blue:Virginia"]["hp"] == 0


def test_torpedo_range_and_target_rules():
    g = game(["Ohio"], ["T-55-102", "1 Lima"])
    with pytest.raises(RuleError, match="range"):
        engine.torpedo_attack(g, CAT, "blue:Ohio", "red:T-55-102", 3)
    with pytest.raises(RuleError, match="ships"):
        engine.torpedo_attack(g, CAT, "blue:Ohio", "red:1 Lima", 1)


def test_resupply_only_after_engagements_and_across_task_forces():
    g = game(["Lima", "1 Alpha"], ["1 Fox"], blue2=["2 Alpha", "Kilo"])
    g["units"]["blue:1 Alpha"]["supply"]["s1"] = 1
    g["units"]["blue:2 Alpha"]["supply"]["s1"] = 0
    with pytest.raises(RuleError, match="after engagements"):
        engine.resupply(g, CAT, "blue:Lima", "blue:1 Alpha", "s1", 4)
    engine.end_engagements(g)
    with pytest.raises(RuleError, match="Engagements are finished"):
        engine.long_range_strike(g, CAT, [{"shooter": "blue:1 Alpha", "weapon": "lrs", "target": "red:1 Fox", "shots": 1}], [])
    engine.resupply(g, CAT, "blue:Lima", "blue:1 Alpha", "s1", 4)
    engine.resupply(g, CAT, "blue:Lima", "blue:2 Alpha", "s1", 5)  # other task force, same team
    assert g["units"]["blue:1 Alpha"]["supply"]["s1"] == 5
    assert g["units"]["blue:2 Alpha"]["supply"]["s1"] == 5
    assert g["units"]["blue:Lima"]["supply"]["s1"] == 11
    with pytest.raises(RuleError, match="only take 0"):
        engine.resupply(g, CAT, "blue:Lima", "blue:1 Alpha", "s1", 1)
    with pytest.raises(RuleError, match="has the turn"):        # source must be in the active task force
        engine.resupply(g, CAT, "blue:Kilo", "blue:1 Alpha", "s2", 1)
    engine.end_turn(g)
    assert g["phase"] == "engage"


def test_supply_messages_follow_pseudocode():
    ada = CAT.new_unit_state("blue:1:1 Delta")
    assert "Intercept type 1 (close range) supply: ∞ at 6" in engine.supply_report(CAT, ada)
    assert "Torpedo supply: ∞ at 14" in engine.supply_report(CAT, CAT.new_unit_state("blue:Virginia"))
    inf = CAT.new_unit_state("red:1 Fox")
    inf["supply"]["s1"] = 0
    assert "consider resupplying" in engine.supply_report(CAT, inf)[0]
    log = CAT.new_unit_state("red:1 Lima")
    log["supply"]["s1"] = 0
    assert engine.supply_report(CAT, log) == ["Out of supply"]
    log["hp"] = 0
    assert engine.supply_report(CAT, log) == ["UNIT DEAD"]


def test_rounds_skip_dead_task_forces_and_pick_chooser():
    g = game(["1 Alpha"], ["1 Fox"], blue2=["2 Alpha"])   # Miami, Beijing, SF
    g["units"]["red:1 Fox"]["hp"] = 0                     # Beijing out: only Blue left, so back to back is fine
    engine.end_turn(g)                                    # Miami -> (Beijing skipped) -> SF
    assert g["active_tf"] == 2 and g["turn"] == 1
    engine.end_turn(g)                                    # SF went last -> round 2 starts with ordering
    assert g["phase"] == "order" and g["turn"] == 2 and g["chooser"] == "red"
    with pytest.raises(RuleError, match="turn order"):
        engine.end_turn(g)


def test_round_order_must_alternate():
    g = engine.new_game(CAT, {"name": "t", "initiative": {"start": 0, "blue_wins_at": 3, "red_wins_at": -3}, "task_forces": [
        {"name": "A", "team": "blue", "units": ["blue:1 Alpha"]}, {"name": "B", "team": "blue", "units": ["blue:2 Alpha"]},
        {"name": "C", "team": "blue", "units": ["blue:3 Alpha"]}, {"name": "X", "team": "red", "units": ["red:1 Fox"]},
        {"name": "Y", "team": "red", "units": ["red:2 Fox"]}]}, "t")
    assert g["phase"] == "order"
    with pytest.raises(RuleError, match="set the turn order|Set the turn order"):
        engine.long_range_strike(g, CAT, [{"shooter": "blue:1 Alpha", "weapon": "lrs", "target": "red:1 Fox", "shots": 1}], [])
    with pytest.raises(RuleError, match="alternate"):
        engine.set_round_order(g, [0, 1, 3, 2, 4])          # A B ... two Blue in a row with Red left
    engine.set_round_order(g, [3, 0, 4, 1, 2])              # X A Y B C: Red ran out, so B C back to back is OK
    assert [tf["name"] for tf in g["task_forces"]] == ["X", "A", "Y", "B", "C"] and g["active_tf"] == 0
    for _ in range(5):
        engine.end_turn(g)
    assert g["phase"] == "order" and g["chooser"] == "red"  # C (Blue) went last


def test_task_force_must_land_before_playing():
    sc = {"name": "t", "initiative": {"start": 0, "blue_wins_at": 3, "red_wins_at": -3}, "task_forces": [
        {"name": "TF Shanghai", "team": "red", "units": ["red:1 Alpha"], "requires_landing": True},
        {"name": "TF Miami", "team": "blue", "units": ["blue:1 Alpha"]},
        {"name": "TF Beijing", "team": "red", "units": ["red:1 Fox"]}]}
    g = engine.new_game(CAT, sc, "t")
    engine.set_round_order(g, [1, 2, 0])                  # Miami, Beijing; Shanghai sits out
    with pytest.raises(RuleError, match="not landed"):
        engine.long_range_strike(g, CAT, [{"shooter": "blue:1 Alpha", "weapon": "lrs", "target": "red:1 Alpha", "shots": 1}], [])
    engine.end_turn(g)                                    # Miami -> Beijing
    engine.end_turn(g)                                    # Beijing last; Shanghai skipped
    assert g["phase"] == "order" and g["chooser"] == "blue"
    engine.umpire_edit(g, CAT, {"what": "landed", "tf": 2, "value": True})
    with pytest.raises(RuleError, match="alternate"):
        engine.set_round_order(g, [1, 2, 0])              # Beijing, Shanghai, Miami: two Red while Blue still waits
    engine.set_round_order(g, [1, 0, 2])                  # Beijing, Miami, Shanghai
    assert g["task_forces"][g["active_tf"]]["name"] == "TF Beijing"


def test_umpire_edit_overrides_everything():
    g = game(["1 Alpha"], ["1 Fox"])
    g["units"]["red:1 Fox"]["hp"] = 0
    engine.umpire_edit(g, CAT, {"what": "unit", "unit": "red:1 Fox", "field": "hp", "value": 2})   # revive
    engine.umpire_edit(g, CAT, {"what": "unit", "unit": "blue:1 Alpha", "field": "s2", "value": 0})
    engine.umpire_edit(g, CAT, {"what": "active_tf", "value": 1})
    engine.umpire_edit(g, CAT, {"what": "turn", "value": 5})
    assert g["units"]["red:1 Fox"]["hp"] == 2 and g["units"]["blue:1 Alpha"]["supply"]["s2"] == 0
    assert g["active_tf"] == 1 and g["turn"] == 5
    engine.umpire_edit(g, CAT, {"what": "order", "value": [1, 0]})          # Beijing first; it still has the turn
    assert [tf["name"] for tf in g["task_forces"]] == ["TF Beijing", "TF Miami"] and g["active_tf"] == 0
    with pytest.raises(RuleError, match="exactly once"):
        engine.umpire_edit(g, CAT, {"what": "order", "value": [0, 0]})
    engine.umpire_edit(g, CAT, {"what": "unit", "unit": "red:1 Fox", "field": "hp", "value": 99})
    assert g["units"]["red:1 Fox"]["hp"] == 2                     # capped at max HP


def test_initiative_ends_game():
    g = game(["1 Alpha"], ["1 Fox"])
    engine.adjust_initiative(g, 3)
    engine.end_turn(g)
    assert g["winner"] == "blue"


def test_presets_are_valid(tmp_path):
    api = Api(CAT, Storage(tmp_path))
    for sc in api.list_scenarios()["data"]:
        assert api.save_scenario(sc)["ok"], sc["name"]           # every unit exists, no unit in two task forces
        assert api.new_game(sc["name"])["ok"], sc["name"]
    s6 = api.new_game("Situation 6")["data"]
    shanghai = next(tf for tf in s6["task_forces"] if tf["name"] == "TF Shanghai")
    assert not shanghai["in_play"]


def test_preset_refresh_backs_up_edited_copy(tmp_path):
    store = Storage(tmp_path)
    edited = {**store.get_scenario("Situation 1"), "map": "my map"}
    store.save_scenario(edited)
    (tmp_path / "presets_version").write_text("1")              # pretend an older preset set is installed
    Storage(tmp_path)
    assert store.get_scenario("Situation 1")["map"] == ""
    assert (tmp_path / "scenarios" / "situation-1.json.bak").exists()


def test_umpire_pin_and_permissions(tmp_path):
    api = Api(CAT, Storage(tmp_path))
    api.new_game("Situation 1")
    edit = {"what": "unit", "unit": "blue:DDG-56", "field": "hp", "value": 1}
    assert "Only the umpire" in api.action("umpire", edit)["error"]
    assert api.action("umpire", {"what": "landed", "tf": 0, "value": True})["ok"] is False  # landing is umpire-only
    assert "Unknown action" in api.action("land", {"tf": 0})["error"]
    assert api.umpire_unlock("12")["ok"] is False                 # too short to set
    assert api.umpire_unlock("1234")["ok"]                        # first unlock sets the PIN
    assert api.action("umpire", edit)["data"]["game"]["units"]["blue:DDG-56"]["hp"] == 1
    api.umpire_lock()
    assert api.umpire_unlock("9999")["error"] == "Wrong umpire PIN"
    assert "1234" not in (tmp_path / "umpire.json").read_text()   # stored hashed
    assert api.umpire_unlock("1234")["ok"]


def test_api_roundtrip_and_undo(tmp_path):
    api = Api(CAT, Storage(tmp_path))
    view = api.new_game("Situation 1")["data"]
    assert view["phase"] == "order"
    assert api.action("round_order", {"order": [0, 2, 1, 3]})["ok"]       # Miami, Beijing, SF, Shanghai
    assert api.action("adjust", {"unit": "blue:DDG-56", "field": "s1", "delta": -2})["ok"] is False  # players can't edit supply
    r = api.action("lrs", {"attacks": [{"shooter": "blue:1 Alpha", "weapon": "lrs", "target": "red:1 Alpha", "shots": 1}],
                           "intercepts": []})["data"]
    assert r["game"]["units"]["blue:1 Alpha"]["supply"]["s2"] == 0
    assert api.undo()["data"]["units"]["blue:1 Alpha"]["supply"]["s2"] == 1
    assert api.list_games()["data"][0]["id"] == view["id"]
