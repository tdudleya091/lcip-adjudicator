"""Rules engine: dice, supply checks, combat adjudication and turn flow.

Every action takes the game state (a plain dict, so it saves straight to JSON)
and the unit catalog, mutates the state in place, and returns a list of events
({"kind": ..., "text": ...}) describing each roll for the UI and the game log.
A d20 succeeds when it rolls at or under the unit's rating.
"""
import random

ASW_KILL_ROLL = 10   # a detected sub is sunk on d20 <= 10
TORPEDO_RANGE = 2    # torpedoes reach ships up to 2 hexes away

_system_rng = random.SystemRandom()


class RuleError(ValueError):
    """An action the rules don't allow; the message is shown to the player."""


def d20(rng=None) -> int:
    return (rng or _system_rng).randint(1, 20)


def ev(kind: str, text: str) -> dict:
    return {"kind": kind, "text": text}


# ---------------------------------------------------------------- lookups

def get_unit(state, uid):
    try:
        return state["units"][uid]
    except KeyError:
        raise RuleError(f"Unknown unit: {uid}") from None


def is_alive(u) -> bool:
    return u["hp"] >= 1


def unit_type(cat, u) -> dict:
    return cat.types[u["type"]]


def weapon(cat, u, key, kind=None) -> dict:
    for w in unit_type(cat, u)["weapons"]:
        if w["key"] == key and (kind is None or w["kind"] == kind):
            return w
    raise RuleError(f"{u['name']} has no {kind or key} weapon")


def first_weapon(cat, u, kind):
    return next((w for w in unit_type(cat, u)["weapons"] if w["kind"] == kind), None)


def supply_left(u, w):
    """Rolls left for a weapon; None means unlimited."""
    return None if w["supply"] is None else u["supply"][w["supply"]]


def spend(u, w, n=1):
    if w["supply"] is not None:
        u["supply"][w["supply"]] -= n


def damage(u, events, n=1):
    u["hp"] = max(0, u["hp"] - n)
    if is_alive(u):
        events.append(ev("hit", f"{u['name']} hit: {u['hp']} HP left"))
    else:
        events.append(ev("kill", f"{u['name']} hit: DESTROYED"))


def require_alive(u):
    if not is_alive(u):
        raise RuleError(f"{u['name']} is destroyed")


def require_enemies(a, b):
    if a["team"] == b["team"]:
        raise RuleError(f"{a['name']} and {b['name']} are on the same team")


def whole_number(value, what) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        raise RuleError(f"{what} must be a whole number") from None
    if n < 0:
        raise RuleError(f"{what} cannot be negative")
    return n


def check_supply(state, cat, demand):
    """demand maps (unit id, weapon key) -> rolls wanted; raise if any supply slot is overdrawn."""
    per_slot = {}
    for (uid, wkey), n in demand.items():
        w = weapon(cat, get_unit(state, uid), wkey)
        if w["supply"] is not None:
            per_slot[(uid, w["supply"])] = per_slot.get((uid, w["supply"]), 0) + n
    for (uid, slot), n in per_slot.items():
        u = get_unit(state, uid)
        have = u["supply"][slot]
        if n > have:
            label = cat.supply_def(u["type"], slot)["label"]
            raise RuleError(f"{u['name']} needs {n} {label} supply but has {have}. Resupply it first.")


def task_force_of(state, uid):
    return next((tf for tf in state["task_forces"] if uid in tf["units"]), None)


def tf_in_play(tf) -> bool:
    """A task force flagged requires_landing stays out of play until the umpire marks it landed."""
    return tf.get("landed", True)


def require_in_play(state, u):
    tf = task_force_of(state, u["id"])
    if tf is not None and not tf_in_play(tf):
        raise RuleError(f"{u['name']} is in {tf['name']}, which has not landed yet")


def require_ready(state, u):
    require_alive(u)
    require_in_play(state, u)


def require_phase(state, phase):
    current = state.get("phase", "engage")
    if current == "order" and phase != "order":
        raise RuleError("Set the turn order for this round first")
    if current != phase:
        if phase == "engage":
            raise RuleError("Engagements are finished for this turn; only resupply is allowed now")
        raise RuleError("Resupply happens after engagements. Click 'Engagements done' first.")


# ---------------------------------------------------------------- supply checks

def supply_report(cat, u) -> list[str]:
    """The supply check messages from the turn flow, for one unit."""
    t = unit_type(cat, u)
    if not is_alive(u):
        return ["UNIT DEAD"]
    msgs = []
    if t["category"] in ("logistics", "sub"):
        n = u["supply"]["s1"]
        msgs.append(f"There is {n} supply remaining" if n >= 1 else "Out of supply")
    for w in t["weapons"]:
        left = supply_left(u, w)
        if left is None:
            msgs.append(f"{w['label']} supply: ∞ at {w['roll']}")
        elif left >= 1:
            msgs.append(f"You have {left} {w['label']} rolls at {w['roll']}")
        else:
            msgs.append(f"No supply for {w['label']}: consider resupplying from a nearby logistics unit")
    return msgs


# ---------------------------------------------------------------- long-range strike

def long_range_strike(state, cat, attacks, intercepts, rng=None):
    """attacks: [{shooter, weapon, target, shots}]; intercepts: [{unit, weapon, attempts}].

    Each shot rolls against the shooter's LRS rating. A shot on target is met by
    the next available intercept attempt (best rating first); if that fails, or
    no attempts are left, the target loses 1 HP. Every declared shot and intercept
    attempt costs supply, whether or not it ends up being rolled.
    """
    require_phase(state, "engage")
    lines, demand = [], {}
    for a in attacks:
        s, t = get_unit(state, a.get("shooter")), get_unit(state, a.get("target"))
        w = weapon(cat, s, a.get("weapon"), "lrs")
        require_ready(state, s)
        require_ready(state, t)
        require_enemies(s, t)
        n = whole_number(a.get("shots"), "Shots")
        if n:
            demand[(s["id"], w["key"])] = demand.get((s["id"], w["key"]), 0) + n
            lines.append((s, w, t, n))
    if not lines:
        raise RuleError("Enter at least one shot")

    defending_teams = {t["team"] for _, _, t, _ in lines}
    pool = []
    for i in intercepts:
        d = get_unit(state, i.get("unit"))
        w = weapon(cat, d, i.get("weapon"), "intercept")
        n = whole_number(i.get("attempts"), "Intercept attempts")
        if not n:
            continue
        require_ready(state, d)
        if d["team"] not in defending_teams:
            raise RuleError(f"{d['name']} is not on the defending team")
        demand[(d["id"], w["key"])] = demand.get((d["id"], w["key"]), 0) + n
        pool.append({"unit": d, "weapon": w, "left": n})
    check_supply(state, cat, demand)
    for s, w, _, n in lines:  # all declared shots and attempts are spent up front
        spend(s, w, n)
    for p in pool:
        spend(p["unit"], p["weapon"], p["left"])
    # Best interceptors first; at equal rating, unlimited-supply ones before finite ones.
    pool.sort(key=lambda p: (-p["weapon"]["roll"], p["weapon"]["supply"] is not None))

    events = []
    for p in pool:
        events.append(ev("info", f"{p['unit']['name']} commits {p['left']} × {p['weapon']['label']} "
                                 f"(intercepts on ≤{p['weapon']['roll']})"))
    for s, w, t, n in lines:
        events.append(ev("info", f"{s['name']} fires {n} × {w['label']} at {t['name']} (hits on ≤{w['roll']})"))
        for k in range(n):
            if not is_alive(t):
                events.append(ev("info", f"{t['name']} already destroyed: {n - k} shot(s) wasted; their supply is still spent"))
                break
            r = d20(rng)
            if r > w["roll"]:
                events.append(ev("miss", f"Shot {k + 1}: rolled {r}, miss"))
                continue
            p = next((p for p in pool if p["left"] > 0 and is_alive(p["unit"])), None)
            if p:
                p["left"] -= 1
                ir = d20(rng)
                who = f"{p['unit']['name']} {p['weapon']['label']}"
                if ir <= p["weapon"]["roll"]:
                    events.append(ev("intercept", f"Shot {k + 1}: rolled {r}, on target; INTERCEPTED by {who} (rolled {ir} ≤ {p['weapon']['roll']})"))
                    continue
                events.append(ev("info", f"Shot {k + 1}: rolled {r}, on target; {who} failed to intercept (rolled {ir})"))
            else:
                events.append(ev("info", f"Shot {k + 1}: rolled {r}, on target; no intercepts left"))
            damage(t, events)
    unused = sum(p["left"] for p in pool)
    if unused:
        events.append(ev("info", f"{unused} intercept attempt(s) not needed; their supply is still spent"))
    return events


# ---------------------------------------------------------------- close combat

def close_combat(state, cat, attackers, defender, rng=None):
    """attackers: [{unit, shots}]; defender: {unit, shots}.

    Fought in rounds: each living attacker with shots left fires once at the
    defender, then the defender (if alive) fires once at the attackers in turn.
    Ends when the defender or every attacker is destroyed, or all shots are spent.
    Every declared shot, attacker's and defender's, costs supply even if never fired.
    """
    require_phase(state, "engage")
    d = get_unit(state, defender.get("unit"))
    require_ready(state, d)
    side, demand = [], {}
    for a in attackers:
        u = get_unit(state, a.get("unit"))
        w = first_weapon(cat, u, "close")
        if w is None:
            raise RuleError(f"{u['name']} has no close assault weapon")
        require_ready(state, u)
        require_enemies(u, d)
        n = whole_number(a.get("shots"), "Shots")
        if any(x["unit"] is u for x in side):
            raise RuleError(f"{u['name']} is listed twice")
        if n:
            demand[(u["id"], w["key"])] = n
            side.append({"unit": u, "weapon": w, "left": n})
    if not side:
        raise RuleError("Enter at least one attacking shot")
    dshots = whole_number(defender.get("shots", 0), "Defender shots")
    dw = first_weapon(cat, d, "close")
    if dshots and dw is None:
        raise RuleError(f"{d['name']} has no close assault weapon to fire back with")
    if dshots:
        demand[(d["id"], dw["key"])] = dshots
    check_supply(state, cat, demand)
    for x in side:  # all declared shots are spent up front
        spend(x["unit"], x["weapon"], x["left"])
    if dshots:
        spend(d, dw, dshots)

    events = [ev("info", f"Close assault on {d['name']}: " + ", ".join(
        f"{x['unit']['name']} {x['left']} shot(s) at ≤{x['weapon']['roll']}" for x in side)
        + (f"; defender returns {dshots} at ≤{dw['roll']}" if dshots else "; defender does not fire back"))]
    rnd = 0
    while is_alive(d) and any(is_alive(x["unit"]) for x in side):
        attackers_can = any(x["left"] and is_alive(x["unit"]) for x in side)
        if not attackers_can and not dshots:
            break
        rnd += 1
        events.append(ev("info", f"Round {rnd}"))
        for x in side:
            if x["left"] and is_alive(x["unit"]) and is_alive(d):
                x["left"] -= 1
                r = d20(rng)
                if r <= x["weapon"]["roll"]:
                    events.append(ev("info", f"{x['unit']['name']} rolled {r}: hit"))
                    damage(d, events)
                else:
                    events.append(ev("miss", f"{x['unit']['name']} rolled {r}: miss"))
        living = [x for x in side if is_alive(x["unit"])]
        if dshots and is_alive(d) and living:
            target = living[(rnd - 1) % len(living)]["unit"]
            dshots -= 1
            r = d20(rng)
            if r <= dw["roll"]:
                events.append(ev("info", f"{d['name']} fires at {target['name']}, rolled {r}: hit"))
                damage(target, events)
            else:
                events.append(ev("miss", f"{d['name']} fires at {target['name']}, rolled {r}: miss"))
    if not any(is_alive(x["unit"]) for x in side):
        events.append(ev("kill", "All attacking units destroyed: the attack stops"))
    elif is_alive(d):
        events.append(ev("info", f"{d['name']} holds with {d['hp']} HP"))
    wasted = sum(x["left"] for x in side) + dshots
    if wasted:
        events.append(ev("info", f"{wasted} shot(s) not fired; their supply is still spent"))
    return events


# ---------------------------------------------------------------- submarines & ASW

def _asw_check(cat, hunter, sub, events, rng=None) -> bool:
    """Detect roll vs the sub's detect rating, then a d20 <= 10 kills it. True if sunk."""
    detect = unit_type(cat, sub)["detect"]
    dr = d20(rng)
    if dr > detect:
        events.append(ev("miss", f"{hunter['name']} ASW: detect roll {dr} > {detect}, {sub['name']} not detected"))
        return False
    events.append(ev("info", f"{hunter['name']} ASW: detect roll {dr} ≤ {detect}, {sub['name']} detected"))
    ar = d20(rng)
    if ar <= ASW_KILL_ROLL:
        events.append(ev("info", f"ASW attack roll {ar} ≤ {ASW_KILL_ROLL}"))
        sub["hp"] = 0
        events.append(ev("kill", f"{sub['name']} DESTROYED"))
        return True
    events.append(ev("miss", f"ASW attack roll {ar} > {ASW_KILL_ROLL}: {sub['name']} evades"))
    return False


def asw_attack(state, cat, hunter_id, sub_id, rng=None):
    require_phase(state, "engage")
    hunter, sub = get_unit(state, hunter_id), get_unit(state, sub_id)
    require_ready(state, hunter)
    require_ready(state, sub)
    require_enemies(hunter, sub)
    if not unit_type(cat, hunter)["asw"]:
        raise RuleError(f"{hunter['name']} has no ASW capability")
    if unit_type(cat, sub)["category"] != "sub":
        raise RuleError(f"{sub['name']} is not a submarine")
    events = []
    _asw_check(cat, hunter, sub, events, rng)
    return events


def torpedo_attack(state, cat, sub_id, target_id, distance, rng=None):
    """ASW-capable targets get an ASW check first; if the sub survives it fires one torpedo (unlimited supply)."""
    require_phase(state, "engage")
    sub, target = get_unit(state, sub_id), get_unit(state, target_id)
    w = weapon(cat, sub, "torpedo", "torpedo")
    require_ready(state, sub)
    require_ready(state, target)
    require_enemies(sub, target)
    if unit_type(cat, target)["category"] != "ship":
        raise RuleError("Torpedoes can only target ships")
    if whole_number(distance, "Distance") > TORPEDO_RANGE:
        raise RuleError(f"Target is out of torpedo range (max {TORPEDO_RANGE} hexes)")
    check_supply(state, cat, {(sub["id"], "torpedo"): 1})
    events = []
    if unit_type(cat, target)["asw"]:
        events.append(ev("info", f"{target['name']} is ASW-capable and searches first"))
        if _asw_check(cat, target, sub, events, rng):
            events.append(ev("info", "Torpedo not fired"))
            return events
    spend(sub, w)
    r = d20(rng)
    if r <= w["roll"]:
        events.append(ev("info", f"{sub['name']} torpedo rolled {r} ≤ {w['roll']}: hit"))
        damage(target, events)
    else:
        events.append(ev("miss", f"{sub['name']} torpedo rolled {r} > {w['roll']}: miss"))
    return events


# ---------------------------------------------------------------- supply ops & manual edits

def resupply(state, cat, from_id, to_id, slot, amount):
    """Draw down a supply unit of the active task force to refill any unit on the same team.

    Only allowed in the resupply phase, i.e. after the task force's engagements.
    """
    require_phase(state, "resupply")
    src, dst = get_unit(state, from_id), get_unit(state, to_id)
    require_ready(state, src)
    require_ready(state, dst)
    if unit_type(cat, src)["category"] != "logistics":
        raise RuleError(f"{src['name']} is not a supply unit")
    active = state["task_forces"][state["active_tf"]]
    if from_id not in active["units"]:
        raise RuleError(f"{src['name']} is not in {active['name']}, which has the turn")
    if src is dst:
        raise RuleError("A supply unit cannot resupply itself")
    if src["team"] != dst["team"]:
        raise RuleError(f"{dst['name']} is not on your team")
    if slot not in dst["supply"]:
        raise RuleError(f"{dst['name']} has no supply slot {slot}")
    n = whole_number(amount, "Amount")
    cap = cat.supply_def(dst["type"], slot)["start"]
    room = cap - dst["supply"][slot]
    if n < 1:
        raise RuleError("Amount must be at least 1")
    if n > src["supply"]["s1"]:
        raise RuleError(f"{src['name']} only has {src['supply']['s1']} supply")
    if n > room:
        raise RuleError(f"{dst['name']} can only take {room} more (full is {cap})")
    src["supply"]["s1"] -= n
    dst["supply"][slot] += n
    label = cat.supply_def(dst["type"], slot)["label"]
    return [ev("info", f"{src['name']} gave {n} {label} supply to {dst['name']} "
                       f"({dst['supply'][slot]}/{cap}); {src['name']} has {src['supply']['s1']} left")]


def umpire_edit(state, cat, p):
    """Umpire override of any game value; bypasses phase, landing and dead-unit locks.

    p["what"] is one of: unit (uid, field = "hp" or a supply slot, value), turn, active_tf,
    order (value = list of current task force indexes in their new order), phase,
    landed (tf, value), initiative, reopen.
    """
    what = p.get("what")
    if what == "unit":
        u = get_unit(state, p.get("unit"))
        field, value = p.get("field"), whole_number(p.get("value"), "Value")
        if field == "hp":
            u["hp"] = min(value, unit_type(cat, u)["hp"])
            text = f"{u['name']} HP set to {u['hp']}"
            return [ev("info", text) if is_alive(u) else ev("kill", text + ": DESTROYED")]
        if field not in u["supply"]:
            raise RuleError(f"Unknown field {field}")
        s = cat.supply_def(u["type"], field)
        u["supply"][field] = min(value, s["start"])
        return [ev("info", f"{u['name']} {s['label']} supply set to {u['supply'][field]}")]
    if what == "turn":
        state["turn"] = max(1, whole_number(p.get("value"), "Turn"))
        return [ev("info", f"Turn number set to {state['turn']}")]
    if what == "active_tf":
        i = whole_number(p.get("value"), "Task force")
        if i >= len(state["task_forces"]):
            raise RuleError("No such task force")
        state["active_tf"], state["phase"] = i, "engage"
        return [ev("info", f"{state['task_forces'][i]['name']} given the turn")]
    if what == "order":
        tfs = state["task_forces"]
        order = [whole_number(i, "Task force") for i in p.get("value") or []]
        if sorted(order) != list(range(len(tfs))):
            raise RuleError("Turn order must list every task force exactly once")
        active = tfs[state["active_tf"]]
        state["task_forces"] = [tfs[i] for i in order]
        state["active_tf"] = state["task_forces"].index(active)  # whoever had the turn keeps it
        return [ev("info", "Turn order: " + " → ".join(tf["name"] for tf in state["task_forces"]))]
    if what == "phase":
        names = {"order": "choosing turn order", "engage": "engagements", "resupply": "resupply"}
        if p.get("value") not in names:
            raise RuleError("Phase must be order, engage or resupply")
        state["phase"] = p["value"]
        return [ev("info", f"Phase set to {names[p['value']]}")]
    if what == "landed":
        tf = state["task_forces"][whole_number(p.get("tf"), "Task force")]
        tf["landed"] = bool(p.get("value"))
        return [ev("info", f"{tf['name']} marked {'landed' if tf['landed'] else 'not landed'}")]
    if what == "initiative":
        state["initiative"]["value"] = int(p.get("value"))
        return [ev("info", f"Initiative set to {state['initiative']['value']}")]
    if what == "reopen":
        state["winner"] = None
        return [ev("info", "Game reopened")]
    raise RuleError(f"Unknown umpire edit {what}")


def end_engagements(state):
    require_phase(state, "engage")
    state["phase"] = "resupply"
    return [ev("info", "Engagements done: resupply phase")]


# ---------------------------------------------------------------- initiative & turns

def check_initiative(state):
    ini = state["initiative"]
    if ini["value"] >= ini["blue_wins_at"]:
        return "blue"
    if ini["value"] <= ini["red_wins_at"]:
        return "red"
    return None


def adjust_initiative(state, delta):
    state["initiative"]["value"] += int(delta)
    return [ev("info", f"Initiative now {state['initiative']['value']}")]


def playable(state, tf) -> bool:
    """Takes a turn this round: landed and has at least one living unit."""
    return tf_in_play(tf) and any(is_alive(state["units"][uid]) for uid in tf["units"])


def check_alternation(state, tfs):
    """Playing task forces must alternate Red/Blue. Once one team has no task forces left
    to place, the other team's remaining ones may follow each other."""
    teams = [tf["team"] for tf in tfs if playable(state, tf)]
    for k in range(1, len(teams)):
        if teams[k] == teams[k - 1] and any(t != teams[k] for t in teams[k:]):
            other = "Red" if teams[k] == "blue" else "Blue"
            raise RuleError(f"Turns must alternate: two {teams[k].title()} task forces in a row "
                            f"while {other} still has a task force to place")


def set_round_order(state, order):
    """Players set the order for the round (order = current task force indexes, new order)."""
    if state.get("phase") != "order":
        raise RuleError("The turn order is chosen at the start of a round")
    tfs = state["task_forces"]
    try:
        order = [int(i) for i in order]
    except (TypeError, ValueError):
        raise RuleError("Invalid turn order") from None
    if sorted(order) != list(range(len(tfs))):
        raise RuleError("Turn order must list every task force exactly once")
    new = [tfs[i] for i in order]
    check_alternation(state, new)
    first = next((k for k, tf in enumerate(new) if playable(state, tf)), None)
    if first is None:
        raise RuleError("No task force can play")
    state["task_forces"], state["active_tf"], state["phase"] = new, first, "engage"
    names = " → ".join(tf["name"] for tf in new if playable(state, tf))
    return [ev("info", f"Round {state['turn']} order: {names}"), ev("info", f"{new[first]['name']} has the turn")]


def end_turn(state):
    """Check initiative, then pass to the next playing task force in this round's order.
    After the last one, the next round starts with choosing its turn order."""
    if state.get("phase") == "order":
        raise RuleError("Set the turn order for this round first")
    winner = check_initiative(state)
    if winner:
        state["winner"] = winner
        return [ev("kill", f"{winner.title()} meets the initiative condition: game over")]
    tfs, i = state["task_forces"], state["active_tf"]
    j = next((k for k in range(i + 1, len(tfs)) if playable(state, tfs[k])), None)
    if j is not None:
        state["active_tf"], state["phase"] = j, "engage"
        return [ev("info", f"{tfs[j]['name']} has the turn")]
    # round over: the team that did not go last chooses who goes first next round
    chooser = "red" if tfs[i]["team"] == "blue" else "blue"
    state["turn"] += 1
    state["phase"], state["chooser"] = "order", chooser
    return [ev("info", f"Round {state['turn'] - 1} complete. {tfs[i]['name']} ({tfs[i]['team'].title()}) went last, "
                       f"so {chooser.title()} chooses which task force goes first in round {state['turn']}")]


def new_game(cat, scenario, game_id):
    tfs = scenario["task_forces"]
    if not any(tf["team"] == "blue" for tf in tfs) or not any(tf["team"] == "red" for tf in tfs):
        raise RuleError("A situation needs at least one Blue and one Red task force")
    for tf in tfs:
        if not tf["units"]:
            raise RuleError(f"{tf['name']} has no units yet. Edit the situation to add some.")
    first = next((i for i, tf in enumerate(tfs) if not tf.get("requires_landing")), None)
    if first is None:
        raise RuleError("At least one task force must start in play (not waiting to land)")
    ini = scenario["initiative"]
    return {
        "id": game_id,
        "scenario": scenario["name"],
        "map": scenario.get("map", ""),
        "turn": 1,               # round number; every playing task force gets one turn per round
        "active_tf": first,
        "phase": "order",        # order -> engage -> resupply -> (next task force) engage ...
        "chooser": None,         # team choosing who goes first; None = players decide together (round 1)
        "winner": None,
        "initiative": {"value": ini["start"], "blue_wins_at": ini["blue_wins_at"], "red_wins_at": ini["red_wins_at"]},
        "task_forces": [{"name": tf["name"], "team": tf["team"], "units": list(tf["units"]),
                         "requires_landing": bool(tf.get("requires_landing")),
                         "landed": not tf.get("requires_landing")} for tf in tfs],
        "units": {uid: cat.new_unit_state(uid) for tf in tfs for uid in tf["units"]},
        "log": [],
    }
