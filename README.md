# LCIP Adjudicator

A desktop companion for Littoral Commander. It tracks unit health and supply per task force and adjudicates
long-range strikes with intercepts, close combat, submarine and ASW engagements, resupply, initiative and
turn order. Runs on Linux and Windows. **Fully offline:** there is no network code, no CDN, and no telemetry.
The UI talks to Python in-process, and the optional `--browser` mode listens on `127.0.0.1` only.

> **Unofficial fan project.** Not affiliated with or endorsed by the publishers of *Littoral Commander*. You need
> the game itself to play. Unit values and situations in `data/` are house settings and can be edited freely.
> If you want to get the latest version you can go to the Dietz Foundation's website at https://dietzfoundation-org.square.site/product/littoral-indo-pac-2nd-edition
> This is for version 1.7 so if you have any rule updates, please understand it is for version 1.7 which I have.

## Get it

```bash
git clone https://github.com/tdudleya091/lcip-adjudicator.git
cd lcip-adjudicator
./install.sh        # Linux; on Windows double-click install.bat
```

## Run

| | Linux | Windows |
|---|---|---|
| First-time prerequisite | `sudo apt install python3-gi gir1.2-webkit2-4.1` (Fedora: `python3-gobject webkit2gtk4.1`) | Python 3.10+ from python.org. Edge WebView2 ships with Windows 10/11 |
| **Desktop icon + app menu** | `./install.sh` (`./uninstall.sh` removes it) | `install.bat` |
| Run from source | `./run.sh` | `run.bat` |
| Build a standalone app | `./build.sh` → `dist/LCIP/LCIP` | `build.bat` → `dist\LCIP\LCIP.exe` (build on Windows) |
| No app window? | `./run.sh --browser` | `run.bat --browser` |

Tests: `.venv/bin/python -m pytest tests` (scripted dice cover every rule branch).

Saves live in `~/.local/share/lcip/` (Linux) or `%APPDATA%\LCIP\` (Windows): `scenarios/*.json` and `saves/*.json`.
Every action autosaves; Undo goes back up to 30 actions in the current session. When the bundled presets change, your copies are refreshed and any you had edited are kept as `.json.bak`.

## Layout

```
main.py            starts the window (pywebview) or --browser mode
lcip/engine.py     the rules: dice, supply checks, LRS, close combat, ASW, torpedo, resupply, turns
lcip/catalog.py    loads data/units.json
lcip/api.py        methods the JS calls; validation, undo, autosave
lcip/storage.py    JSON files in the user data folder
lcip/server.py     127.0.0.1-only server for --browser mode
data/units.json    every unit type's HP, supply and roll values; edit to change stats
data/scenarios.json  Situations 1–6 (copied to your data folder on first run)
web/               index.html, app.js, style.css (plain JS, no build step)
```

## Using it

1. **Start** a situation. Situations 1–6 come with the task forces from the spec. **Edit** changes units, map,
   initiative values, the **turn order** (▲▼ next to each task force) and whether a task force **must land before it plays**. **💾 Save** stores it, and
   **🗑 Delete** removes it. **+ New custom situation** supports 2 or more task forces.
2. **Every round starts with choosing the turn order.** Drag the task forces into order (or use ▲ ▼), then click
   **Start round**. Red and Blue must alternate. If one team has more task forces, its extra ones go back to back
   at the end. **Make it alternate** fixes an invalid order in one click. Before round 1 the players decide
   together. Before every later round, the team that did *not* take the last turn chooses which task force goes
   first. The situation editor's ▲▼ order is only the suggested starting order.
3. On its turn, each task force has two phases:
   - **Phase 1, Engagements:** long-range strike, close combat, and subs/ASW. Each result lists every roll.
     Click **Engagements done → Resupply** when finished.
   - **Phase 2, Resupply:** pick a supply unit in the task force whose turn it is, then any unit on your team
     (any task force), a supply type, and an amount from the dropdown. The supply unit is drawn down by that amount.
4. Adjust initiative with −/+, then **End turn**: it checks the win condition and passes to the next task force. After the last one, the next round's order screen opens.
5. A task force that must land (TF Shanghai in Situation 6) shows **not landed**. It skips its turns, and its
   units can't act, be targeted or be resupplied until the umpire clicks **Mark … landed**.

### Umpire mode

Players can't type in HP or supply. Supply changes only through combat and resupply, and HP only through combat.
**🔒 Umpire** (top right) unlocks umpire mode with a PIN. The first unlock sets the PIN, which is stored as a
salted hash in `umpire.json` in the data folder; delete that file to reset it. In umpire mode the umpire can:

- Use −/+ on the HP and every supply value of any unit, including destroyed units (to bring them back).
- Set the turn number and the initiative value, choose which task force has the turn, and switch the phase.
- Reorder the task forces mid-game with ◀ ▶ under **Turn order**. The task force whose turn it is keeps the turn.
- Mark a task force landed or not landed (umpire only), and reopen a finished game.

Anyone can edit situations and use Undo. Umpire edits are logged and can be undone. Umpire mode locks again when you click the button or restart the app.

## How the pseudocode was interpreted

Where the spec was ambiguous, these are the choices made. Each one is a small change in `engine.py`, `units.json` or `scenarios.json`.

- **Rolls:** a d20 succeeds on a roll at or under the rating (`randint(1, 20)` via the OS random source).
- **Blue air defense:** close-range intercept (≤6) has unlimited supply, and long-range intercept (≤13) uses the 10 supply.
  **Red T-76 ships:** intercept (≤4) is unlimited. **Red T-55:** supply 2 and 3 are its two intercept types.
- **Submarines (V0.9):** torpedoes are unlimited. The sub's supply is LRS only. Ohio, Sui and Shang II had no HP listed, so 1 is assumed.
- **LRS:** a shot that rolls on target uses the next intercept attempt (best rating first; unlimited before
  finite at equal rating). If the intercept fails, **or no attempts are left**, the target loses 1 HP. (The
  pseudocode only covered the case where intercepts remain.) **Every declared intercept attempt costs supply**, even ones that end up not needed.
  Every declared shot also costs supply; shots left over once the target is destroyed are wasted.
- **Close combat:** fought in rounds. Each living attacker fires one shot, then the defender fires one shot back,
  targeting attackers in rotation. It stops when either side is wiped out or every shot is spent. Every declared
  shot, attacker's and defender's, costs supply even if the fight ends before it is fired.
- **ASW:** detect roll ≤ the sub's detect value, then a roll ≤10 sinks it. Units with ASW: Blue DDG and DDGX,
  Red T-55 and T-54. T-76 and **T-52 (not mentioned in the torpedo rule)** have none; set `"asw": true` in
  `units.json` to change that.
- **Torpedo:** "torpedo<=2" is read as range ≤2 hexes (you enter the distance). ASW-capable targets search first.
- **Resupply (V0.9):** only in the resupply phase. The source is a supply unit in the active task force. The
  target is any unit on the same team. 1 supply point refills 1 roll, never above the starting value.
- **Initiative:** a single track where positive favours Blue. Blue wins at ≥ the Blue value and Red at ≤ the Red value.
  Defaults are ±10 because the spec did not give numbers.
- **Turn order:** chosen by the players at the start of every round (alternating Red/Blue; the team that didn't go last picks who goes first, and may put any task force first). The umpire can still reorder mid-round. Dead or not-landed task forces sit the round out. A task force with no living units, or not yet landed, is skipped.
- **Map:** there is no map data, so the map is a name field.

### Situation unit names

The situation lists use different names from the unit catalog; they map as follows:

- `1-1 Bravo` is `1:1 Bravo`.
- Red hulls: `LHD-20x` is T-76-20x, `FFG-57x` is T-54-57x, `DDG-17x` is T-52-17x, and `DDG-10x` is T-55-10x.
  Ship cards show both names, e.g. "T-76 · LHD".
- Red infantry is named `1 Charlie` and `1 Fox`. Situation 3's two Sui-class boats are `Sui-1` and `Sui-2`.

Three entries in the spec conflict with other parts of it:

- Situation 5 lists FFG-574 in both Beijing and Tianjin. Beijing uses FFG-573, as in Situations 4 and 6.
- Situation 6's TF Shanghai lists 3 Victor, but Red armor only has 1–2 Victor. It is left out.
- Situation 5's header says "SF, NY" but the units are listed NY first. The listed order (NY, then SF) is used.
## License

MIT. See [LICENSE](LICENSE).
