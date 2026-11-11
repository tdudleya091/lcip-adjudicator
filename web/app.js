'use strict';

// ------------------------------------------------------------------ bridge to Python
// Desktop window: pywebview injects window.pywebview.api (fires 'pywebviewready' when it is ready).
// Browser fallback: lcip/server.py sets window.LCIP_BROWSER and we POST /api/<method> on 127.0.0.1.
const desktop = !window.LCIP_BROWSER;
const bridgeReady = new Promise(resolve => {
  if (!desktop || (window.pywebview && window.pywebview.api)) return resolve();
  window.addEventListener('pywebviewready', resolve, { once: true });
});

async function call(name, ...args) {
  await bridgeReady;
  let res;
  if (desktop) {
    res = await window.pywebview.api[name](...args);
  } else {
    const r = await fetch('/api/' + name, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(args),
    });
    res = await r.json();
  }
  if (!res.ok) throw new Error(res.error);
  return res.data;
}

// ------------------------------------------------------------------ DOM helpers
// h('div', {class: 'x', onclick: fn}, child, ...) builds elements; text is always inserted as text, never HTML.
function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const kid of kids.flat()) {
    if (kid == null || kid === false) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else if (k === 'class') el.className = v;
    else if (k === 'value' || k === 'checked' || k === 'disabled') el[k] = v;
    else el.setAttribute(k, v === true ? '' : v);
  }
  return el;
}

const app = document.getElementById('app');
let toastTimer;
function toast(msg, good = false) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = good ? 'good' : '';
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.hidden = true; }, good ? 2000 : 5000);
}

async function guard(fn) {
  try { return await fn(); } catch (e) { toast(e.message); }
}

// Grouped <select>: groups = [{label, items: [{value, text}]}]; empty groups are skipped.
function groupedSelect(groups) {
  const s = h('select');
  for (const g of groups) {
    if (!g.items.length) continue;
    s.append(h('optgroup', { label: g.label }, g.items.map(i => h('option', { value: i.value }, i.text))));
  }
  return s;
}

const num = (value, min = 0) => h('input', { type: 'number', min, value });
const left = w => (w.left === null ? '∞' : `${w.left} left`);
const teamName = t => (t === 'blue' ? 'Blue' : 'Red');

// ------------------------------------------------------------------ state
let CAT = null;          // unit catalog
let GAME = null;         // current game view from Python
let viewTF = 0;          // task force shown in the unit grid
let tab = 'lrs';         // open action panel
let lastEvents = [];     // result of the last combat action
let UMPIRE = false;      // umpire mode: can edit any value in the running game

document.getElementById('nav-home').onclick = () => showHome();

// ------------------------------------------------------------------ umpire mode
const umpireBtn = document.getElementById('nav-umpire');

function setUmpire(status) {
  UMPIRE = status.unlocked;
  umpireBtn.textContent = UMPIRE ? '🔓 Umpire mode ON (click to lock)' : '🔒 Umpire';
  umpireBtn.classList.toggle('on', UMPIRE);
  umpireBtn.dataset.pinSet = status.pin_set ? '1' : '';
  if (GAME) renderGame();
}

umpireBtn.onclick = () => guard(async () => {
  if (UMPIRE) return setUmpire(await call('umpire_lock'));
  const pin = await pinDialog(umpireBtn.dataset.pinSet
    ? 'Enter the umpire PIN'
    : 'Set an umpire PIN (at least 4 characters). It is needed to change HP or edit the game directly.');
  if (pin != null) setUmpire(await call('umpire_unlock', pin));
});

// Small in-page password prompt (native prompt() can't mask input). Resolves to the PIN, or null on cancel.
function pinDialog(message) {
  return new Promise(resolve => {
    const input = h('input', { type: 'password', autocomplete: 'off' });
    const close = value => { overlay.remove(); resolve(value); };
    const overlay = h('div', { class: 'overlay' }, h('form', { class: 'panel dialog', onsubmit: e => { e.preventDefault(); close(input.value); } },
      h('p', null, message), input,
      h('div', { class: 'row' }, h('button', { class: 'primary', type: 'submit' }, 'Unlock'),
        h('button', { type: 'button', onclick: () => close(null) }, 'Cancel'))));
    document.body.append(overlay);
    input.focus();
  });
}

const umpire = (what, extra) => act('umpire', { what, ...extra }, false);

// ------------------------------------------------------------------ home
async function showHome() {
  GAME = null;
  const [scenarios, games] = await Promise.all([call('list_scenarios'), call('list_games')]);
  app.replaceChildren(h('div', { class: 'home' },
    h('section', { class: 'panel' },
      h('h2', null, 'Situations'),
      scenarios.map(sc => h('div', { class: 'list-item' },
        h('div', null,
          h('div', null, h('strong', null, sc.name), sc.map ? h('span', { class: 'muted' }, ` · ${sc.map}`) : null),
          h('div', { class: 'muted' }, sc.task_forces.map(tf => `${tf.name} (${tf.units.length})`).join(' · '))),
        h('div', { class: 'row' },
          h('button', { class: 'primary', onclick: () => guard(async () => { await startGame(sc.name); }) }, 'Start'),
          h('button', { onclick: () => showEditor(sc) }, 'Edit')))),
      h('div', { class: 'row', style: 'margin-top:10px' },
        h('button', { onclick: () => showEditor(null) }, '+ New custom situation'))),
    h('section', { class: 'panel' },
      h('h2', null, 'Saved games'),
      games.length ? null : h('p', { class: 'muted' }, 'No games yet. Games save automatically after every action.'),
      games.map(g => h('div', { class: 'list-item' },
        h('div', null,
          h('strong', null, g.scenario),
          h('div', { class: 'muted' }, `Round ${g.turn}` + (g.winner ? ` · ${teamName(g.winner)} won` : '') + ` · saved ${g.saved.replace('T', ' ')}`)),
        h('div', { class: 'row' },
          h('button', { class: 'primary', onclick: () => guard(async () => { GAME = await call('load_game', g.id); enterGame(); }) }, 'Resume'),
          h('button', { class: 'danger', title: 'Delete', onclick: () => guard(async () => {
            if (confirm(`Delete saved game "${g.scenario}" (round ${g.turn})?`)) { await call('delete_game', g.id); showHome(); }
          }) }, '🗑')))))));
}

async function startGame(name) {
  GAME = await call('new_game', name);
  enterGame();
}

function enterGame() {
  viewTF = GAME.active_tf;
  lastEvents = [];
  renderGame();
}

// ------------------------------------------------------------------ game screen
const U = id => GAME.units[id];
const activeTF = () => GAME.task_forces[GAME.active_tf];
const myUnits = () => activeTF().units.map(U).filter(u => u.alive);
const enemyTeam = () => (activeTF().team === 'blue' ? 'red' : 'blue');

// Living units of a team (in task forces that are in play), grouped by task force for a <select>.
function teamGroups(team, filter = () => true, text = u => `${u.name} (${u.hp}/${u.max_hp} HP)`) {
  return GAME.task_forces.filter(tf => tf.team === team && tf.in_play).map(tf => ({
    label: tf.name,
    items: tf.units.map(U).filter(u => u.alive && filter(u)).map(u => ({ value: u.id, text: text(u) })),
  }));
}

// Unit+weapon pairs of a kind, as "unitId|weaponKey" options.
function weaponGroups(team, kind, onlyActive) {
  const tfs = onlyActive ? [activeTF()] : GAME.task_forces.filter(tf => tf.team === team && tf.in_play);
  return tfs.map(tf => ({
    label: tf.name,
    items: tf.units.map(U).filter(u => u.alive).flatMap(u => u.weapons.filter(w => w.kind === kind)
      .map(w => ({ value: `${u.id}|${w.key}`, text: `${u.name}: ${w.label} ≤${w.roll} (${left(w)})` }))),
  }));
}

async function act(kind, payload, showResult = true) {
  await guard(async () => {
    const r = await call('action', kind, payload);
    GAME = r.game;
    if (showResult) lastEvents = r.events;
    if (kind === 'end_turn') viewTF = GAME.active_tf;
    renderGame();
  });
}

function renderGame() {
  const tf = activeTF();
  const ini = GAME.initiative;
  const ordering = GAME.phase === 'order' && !GAME.winner;
  const engaging = GAME.phase === 'engage';
  if (!ordering) ORDER_DRAFT = null;
  const shown = GAME.task_forces[viewTF];
  app.replaceChildren(...[
    h('div', { class: 'game-head' },
      h('div', null, h('strong', null, GAME.scenario), GAME.map ? h('span', { class: 'muted' }, ` · ${GAME.map}`) : null),
      h('div', null, `Round ${GAME.turn}`),
      ordering ? h('div', { class: 'active' }, `Choosing the turn order for round ${GAME.turn}`)
        : h('div', { class: `active team-${tf.team}` }, `▶ ${tf.name} has the turn`),
      ordering ? null : h('div', { class: 'phase' }, engaging ? 'Phase 1: Engagements' : 'Phase 2: Resupply',
        engaging && !GAME.winner ? h('button', { onclick: () => act('end_engagements', {}), title: 'Locks combat and opens resupply for this turn' },
          'Engagements done → Resupply') : null),
      h('div', { class: 'initiative', title: 'Initiative track: positive favours Blue, negative favours Red' },
        'Initiative',
        h('button', { class: 'small', onclick: () => act('initiative', { delta: -1 }, false), disabled: !!GAME.winner }, '−'),
        h('span', { class: 'value' }, ini.value),
        h('button', { class: 'small', onclick: () => act('initiative', { delta: 1 }, false), disabled: !!GAME.winner }, '+'),
        h('span', { class: 'muted' }, `Blue wins ≥ ${ini.blue_wins_at} · Red wins ≤ ${ini.red_wins_at}`)),
      h('button', { onclick: () => guard(async () => { GAME = await call('undo'); renderGame(); }), disabled: !GAME.can_undo }, '↶ Undo'),
      ordering ? null : h('button', { class: 'primary', disabled: !!GAME.winner, title: 'Checks initiative, then passes the turn to the next task force',
        onclick: () => act('end_turn', {}) }, 'End turn')),
    GAME.winner ? h('div', { class: `winner team-${GAME.winner}`, style: `background:var(--${GAME.winner}-bg)` },
      `${teamName(GAME.winner)} wins on initiative. Game over.`,
      UMPIRE ? h('button', { style: 'margin-left:12px', onclick: () => umpire('reopen') }, 'Reopen game') : null) : null,
    UMPIRE ? umpireBar() : null,
    ordering ? orderPanel() : null,
    h('div', { class: 'tf-tabs' }, GAME.task_forces.map((t, i) => {
      const alive = t.units.filter(id => U(id).alive).length;
      return h('button', { class: `${t.team} ${i === viewTF ? 'on' : ''}`, onclick: () => { viewTF = i; renderGame(); } },
        `${i === GAME.active_tf && !ordering ? '▶ ' : ''}${t.name} (${alive}/${t.units.length})${t.in_play ? '' : ' · not landed'}`);
    })),
    landingBanner(shown, viewTF),
    h('div', { class: 'game' },
      h('div', { class: 'cards' }, shown.units.map(id => unitCard(U(id)))),
      h('div', { class: 'panel' }, actionPanel(), eventList(lastEvents), logView())),
  ].filter(Boolean));
}

// Umpire-only controls for the game as a whole; unit values are edited on the cards.
function umpireBar() {
  const numberEdit = (label, value, what) => h('label', { class: 'row' }, label,
    h('input', { type: 'number', value, onchange: e => umpire(what, { value: e.target.value }) }));
  return h('div', { class: 'umpire-bar' },
    h('strong', null, 'Umpire'),
    numberEdit('Round', GAME.turn, 'turn'),
    numberEdit('Initiative', GAME.initiative.value, 'initiative'),
    h('label', { class: 'row' }, 'Turn belongs to',
      h('select', { value: String(GAME.active_tf), onchange: e => { viewTF = Number(e.target.value); umpire('active_tf', { value: e.target.value }); } },
        GAME.task_forces.map((t, i) => h('option', { value: String(i) }, t.name)))),
    h('label', { class: 'row' }, 'Phase',
      h('select', { value: GAME.phase || 'engage', onchange: e => umpire('phase', { value: e.target.value }) },
        h('option', { value: 'order' }, 'Choose turn order'), h('option', { value: 'engage' }, 'Engagements'),
        h('option', { value: 'resupply' }, 'Resupply'))),
    h('span', { class: 'muted' }, 'HP and supply are editable on every card, including destroyed units.'),
    GAME.phase === 'order' ? null : turnOrderEditor());
}

// ------------------------------------------------------------------ round turn order
// At the start of every round the players drag the task forces into order. Playing task forces
// must alternate Red/Blue until one team runs out (mirrors engine.check_alternation).
let ORDER_DRAFT = null;  // task force indexes in the order being arranged; kept across re-renders
let dragFrom = null;

function alternationError(indexes) {
  const teams = indexes.map(i => GAME.task_forces[i].team);
  for (let k = 1; k < teams.length; k++) {
    if (teams[k] === teams[k - 1] && teams.slice(k).some(t => t !== teams[k])) {
      return `Two ${teamName(teams[k])} task forces in a row while ${teamName(teams[k] === 'blue' ? 'red' : 'blue')} still has one to place.`;
    }
  }
  return null;
}

// Interleave the teams, keeping each team's own order, starting with whoever is first now.
function makeAlternate(indexes) {
  const first = GAME.task_forces[indexes[0]].team;
  const a = indexes.filter(i => GAME.task_forces[i].team === first);
  const b = indexes.filter(i => GAME.task_forces[i].team !== first);
  const out = [];
  while (a.length || b.length) {
    if (a.length) out.push(a.shift());
    if (b.length) out.push(b.shift());
  }
  return out;
}

function orderPanel() {
  const tfs = GAME.task_forces;
  const playing = tfs.map((_, i) => i).filter(i => tfs[i].playable);
  const sitting = tfs.map((_, i) => i).filter(i => !tfs[i].playable);
  if (!ORDER_DRAFT || ORDER_DRAFT.length !== playing.length || ORDER_DRAFT.some(i => !tfs[i].playable)) ORDER_DRAFT = playing;
  const draft = ORDER_DRAFT;
  const moveTo = (from, to) => {
    if (to < 0 || to >= draft.length || from === to) return;
    const [item] = draft.splice(from, 1);
    draft.splice(to, 0, item);
    renderGame();
  };
  const error = alternationError(draft);
  const chooser = GAME.chooser;
  const items = draft.map((i, pos) => {
    const t = tfs[i];
    const alive = t.units.filter(id => U(id).alive).length;
    const li = h('li', { class: `order-item ${t.team}`, draggable: 'true' },
      h('span', { class: 'grip', title: 'Drag to reorder' }, '⠿'),
      h('span', { class: 'pos' }, `${pos + 1}`),
      h('strong', null, t.name),
      h('span', { class: 'muted' }, `${teamName(t.team)} · ${alive} unit(s)`),
      h('span', { class: 'spacer' }),
      h('button', { class: 'small', title: 'Move up', disabled: pos === 0, onclick: () => moveTo(pos, pos - 1) }, '▲'),
      h('button', { class: 'small', title: 'Move down', disabled: pos === draft.length - 1, onclick: () => moveTo(pos, pos + 1) }, '▼'));
    li.addEventListener('dragstart', e => { dragFrom = pos; e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', String(pos)); li.classList.add('dragging'); });
    li.addEventListener('dragend', () => li.classList.remove('dragging'));
    li.addEventListener('dragover', e => { e.preventDefault(); li.classList.add('drop-target'); });
    li.addEventListener('dragleave', () => li.classList.remove('drop-target'));
    li.addEventListener('drop', e => { e.preventDefault(); if (dragFrom != null) moveTo(dragFrom, pos); dragFrom = null; });
    return li;
  });
  return h('div', { class: 'panel order-panel' },
    h('h2', null, `Round ${GAME.turn}: set the turn order`),
    h('p', null, chooser
      ? h('span', null, h('strong', { class: `team-${chooser}` }, teamName(chooser)),
          ' did not go last in the previous round, so ', h('strong', { class: `team-${chooser}` }, teamName(chooser)),
          ' chooses which task force goes first.')
      : 'Players choose the order for the first round.'),
    h('p', { class: 'hint' }, 'Drag task forces (or use ▲ ▼). Red and Blue must alternate; once one team has no task forces left, the other team\'s remaining ones go back to back.'),
    h('ol', { class: 'order-list' }, items),
    sitting.length ? h('p', { class: 'muted' }, 'Not playing this round: ',
      sitting.map(i => `${tfs[i].name} (${tfs[i].in_play ? 'no units left' : 'not landed'})`).join(', ')) : null,
    h('div', { class: `order-status ${error ? 'bad' : 'good'}` }, error ? `✗ ${error}` : '✓ Red and Blue alternate'),
    h('div', { class: 'row' },
      error ? h('button', { onclick: () => { ORDER_DRAFT = makeAlternate(draft); renderGame(); } }, 'Make it alternate') : null,
      h('button', { class: 'primary', disabled: !!error, onclick: () => act('round_order', { order: [...draft, ...sitting] }) },
        `Start round ${GAME.turn}`)));
}

// Umpire reorders task forces mid-game; the one with the turn keeps it.
function turnOrderEditor() {
  const tfs = GAME.task_forces;
  const move = (i, d) => {
    const order = tfs.map((_, k) => k);
    [order[i], order[i + d]] = [order[i + d], order[i]];
    viewTF = order.indexOf(viewTF);  // keep showing the same task force
    umpire('order', { value: order });
  };
  return h('div', { class: 'turn-order' }, h('span', null, 'Turn order:'),
    tfs.map((t, i) => h('span', { class: `order-chip ${t.team}` },
      h('button', { class: 'small', title: 'Earlier', disabled: i === 0, onclick: () => move(i, -1) }, '◀'),
      `${i + 1}. ${t.name}`,
      h('button', { class: 'small', title: 'Later', disabled: i === tfs.length - 1, onclick: () => move(i, 1) }, '▶'))));
}

function landingBanner(t, i) {
  if (t.in_play && !(UMPIRE && t.requires_landing)) return null;
  if (t.in_play) {
    return h('div', { class: 'landing' }, `${t.name} has landed.`,
      h('button', { onclick: () => umpire('landed', { tf: i, value: false }) }, 'Mark not landed'));
  }
  return h('div', { class: 'landing' },
    `${t.name} has not landed. Until it does, it skips its turn and its units cannot act, be targeted or be resupplied.`,
    UMPIRE ? h('button', { class: 'primary', onclick: () => umpire('landed', { tf: i, value: true }) }, `Mark ${t.name} landed`)
      : h('span', { class: 'muted' }, 'Only the umpire can mark it landed.'));
}

function unitCard(u) {
  // Players see supply and HP as values; supply changes through combat and the resupply menu.
  // The umpire gets −/+ on everything, including destroyed units.
  const value = (field, v, cap) => h('div', { class: 'val' },
    UMPIRE ? h('button', { class: 'small', disabled: v <= 0, onclick: () => umpire('unit', { unit: u.id, field, value: v - 1 }) }, '−') : null,
    `${v}/${cap}`,
    UMPIRE ? h('button', { class: 'small', disabled: v >= cap, onclick: () => umpire('unit', { unit: u.id, field, value: v + 1 }) }, '+') : null);
  const cell = (label, body, empty) => h('div', { class: `stat${empty ? ' empty' : ''}` }, h('div', { class: 'label', title: label }, label), body);
  return h('div', { class: `card ${u.team}${u.alive ? '' : ' dead'}` },
    h('div', { class: 'name' }, u.name),
    h('div', { class: 'type' }, u.type_label + (u.asw ? ' · ASW' : '')),
    h('div', { class: 'stats' },
      cell('Health points', value('hp', u.hp, u.max_hp), u.hp === 0),
      u.supplies.map(s => cell(`Supply: ${s.label}`, value(s.key, s.value, s.cap), s.value === 0)),
      u.weapons.map(w => cell(`Roll: ${w.label}`, h('div', { class: 'val' }, `≤ ${w.roll}`, h('span', { class: 'muted' }, left(w))))),
      u.detect != null ? cell('Detect (ASW finds on ≤)', h('div', { class: 'val' }, `≤ ${u.detect}`)) : null),
    u.alive ? h('ul', { class: 'msgs' }, u.messages.map(m => h('li', null, m))) : h('div', { class: 'dead-banner' }, 'UNIT DEAD'));
}

function eventList(events) {
  if (!events.length) return null;
  return h('div', { class: 'events' }, h('h3', null, 'Result'), events.map(e => h('div', { class: `ev ${e.kind}` }, e.text)));
}

function logView() {
  return h('div', { class: 'log' }, h('h3', null, 'Game log'),
    GAME.log.slice().reverse().map(entry => h('details', null,
      h('summary', null, `R${entry.turn} · ${entry.tf}: ${entry.title}`),
      entry.events.map(e => h('div', { class: `ev ${e.kind}` }, e.text)))));
}

// ------------------------------------------------------------------ action panels
const TABS = [['lrs', 'Long-range strike'], ['close', 'Close combat'], ['sub', 'Subs / ASW']];

function actionPanel() {
  if (GAME.winner) return h('p', { class: 'muted' }, 'Game over. Use Undo if the last result was a mistake.');
  if (GAME.phase === 'order') return h('p', { class: 'muted' }, 'Set the turn order above to start the round.');
  if (GAME.phase === 'resupply') return supplyPanel();
  const panels = { lrs: lrsPanel, close: closePanel, sub: subPanel };
  return h('div', null,
    h('div', { class: 'tabs' }, TABS.map(([k, label]) =>
      h('button', { class: tab === k ? 'on' : '', onclick: () => { tab = k; lastEvents = []; renderGame(); } }, label))),
    panels[tab](),
    h('p', { class: 'hint' }, 'Resupply opens after "Engagements done".'));
}

// A list of form rows with "+ add" and per-row remove. makeRow() returns {el, read}.
function rowList(makeRow, addLabel) {
  const rows = [];
  const box = h('div');
  const add = () => {
    const r = makeRow();
    const line = h('div', { class: 'form-line' }, r.el, h('button', { class: 'small', title: 'Remove', onclick: () => {
      rows.splice(rows.indexOf(r), 1); line.remove();
    } }, '×'));
    rows.push(r);
    box.append(line);
  };
  add();
  return { el: h('div', null, box, h('button', { onclick: add }, addLabel)), read: () => rows.map(r => r.read()) };
}

function lrsPanel() {
  const shooters = weaponGroups(activeTF().team, 'lrs', true);
  if (!shooters.some(g => g.items.length)) return h('p', { class: 'muted' }, 'No living unit in this task force has a long-range strike weapon.');
  const foe = enemyTeam();
  const attacks = rowList(() => {
    const s = groupedSelect(shooters), t = groupedSelect(teamGroups(foe)), n = num(1, 1);
    return {
      el: h('span', { class: 'form-line attack-line', style: 'flex:1' }, s, '→', t, n),
      read: () => { const [shooter, weapon] = s.value.split('|'); return { shooter, weapon, target: t.value, shots: n.value }; },
    };
  }, '+ add shot line');
  const interceptGroups = weaponGroups(foe, 'intercept', false);
  const intercepts = rowList(() => {
    const d = groupedSelect(interceptGroups), n = num(0, 0);
    return {
      el: h('span', { class: 'form-line', style: 'flex:1' }, d, n),
      read: () => { const [unit, weapon] = d.value.split('|'); return { unit, weapon, attempts: n.value }; },
    };
  }, '+ add interceptor');
  return h('div', null,
    h('h3', null, `Attacker (${teamName(activeTF().team)}): shooter → target, shots`), attacks.el,
    h('h3', null, `Defender (${teamName(foe)}): intercept attempts`),
    interceptGroups.some(g => g.items.length) ? intercepts.el : h('p', { class: 'muted' }, 'Defender has no intercept units left.'),
    h('p', { class: 'hint' }, 'Every intercept attempt entered here costs supply, even if it is not needed. Each shot on target uses the best remaining attempt.'),
    h('button', { class: 'primary', onclick: () => act('lrs', {
      attacks: attacks.read(),
      intercepts: interceptGroups.some(g => g.items.length) ? intercepts.read().filter(i => i.unit) : [],
    }) }, 'Resolve strike'));
}

function closePanel() {
  const mine = [{ label: activeTF().name, items: myUnits().filter(u => u.weapons.some(w => w.kind === 'close')).map(u => {
    const w = u.weapons.find(x => x.kind === 'close');
    return { value: u.id, text: `${u.name}: ≤${w.roll} (${left(w)})` };
  }) }];
  if (!mine[0].items.length) return h('p', { class: 'muted' }, 'No living unit in this task force can close assault.');
  const attackers = rowList(() => {
    const s = groupedSelect(mine), n = num(1, 1);
    return { el: h('span', { class: 'form-line', style: 'flex:1' }, s, n), read: () => ({ unit: s.value, shots: n.value }) };
  }, '+ add attacker');
  const def = groupedSelect(teamGroups(enemyTeam()));
  const defShots = num(0, 0);
  const defHint = h('p', { class: 'hint' });
  const updateHint = () => {
    const u = U(def.value);
    const w = u && u.weapons.find(x => x.kind === 'close');
    defHint.textContent = !u ? '' : w ? `${u.name} returns fire at ≤${w.roll} (${left(w)}).` : `${u.name} has no close assault weapon and cannot return fire.`;
  };
  def.onchange = updateHint;
  updateHint();
  return h('div', null,
    h('h3', null, 'Attacking units and shots'), attackers.el,
    h('h3', null, 'Defending unit and return shots'), h('div', { class: 'form-line' }, def, defShots), defHint,
    h('p', { class: 'hint' }, 'Fought in rounds until one side is destroyed or all shots are spent. The defender fires at attackers in turn. Every shot entered costs supply, even if the fight ends first.'),
    h('button', { class: 'primary', onclick: () => act('close', { attackers: attackers.read(), defender: { unit: def.value, shots: defShots.value } }) }, 'Resolve assault'));
}

function subPanel() {
  const foe = enemyTeam();
  const hunters = [{ label: activeTF().name, items: myUnits().filter(u => u.asw).map(u => ({ value: u.id, text: u.name })) }];
  const enemySubs = teamGroups(foe, u => u.category === 'sub', u => `${u.name} (detect ≤${u.detect})`);
  const subs = [{ label: activeTF().name, items: myUnits().filter(u => u.category === 'sub').map(u => ({ value: u.id, text: `${u.name} (${u.supply.s1} supply)` })) }];
  const ships = teamGroups(foe, u => u.category === 'ship', u => `${u.name}${u.asw ? ' · ASW' : ''} (${u.hp}/${u.max_hp} HP)`);
  const has = g => g.some(x => x.items.length);

  let asw = h('p', { class: 'muted' }, 'Needs an ASW-capable unit here and a living enemy submarine.');
  if (has(hunters) && has(enemySubs)) {
    const hs = groupedSelect(hunters), ss = groupedSelect(enemySubs);
    asw = h('div', null, h('div', { class: 'form-line' }, hs, '→', ss),
      h('button', { class: 'primary', onclick: () => act('asw', { hunter: hs.value, sub: ss.value }) }, 'ASW attack'));
  }
  let torp = h('p', { class: 'muted' }, 'Needs a submarine here and a living enemy ship.');
  if (has(subs) && has(ships)) {
    const ss = groupedSelect(subs), ts = groupedSelect(ships), dist = num(1, 0);
    torp = h('div', null, h('div', { class: 'form-line' }, ss, '→', ts),
      h('div', { class: 'form-line' }, 'Distance (hexes)', dist),
      h('button', { class: 'primary', onclick: () => act('torpedo', { sub: ss.value, target: ts.value, distance: dist.value }) }, 'Fire torpedo'));
  }
  return h('div', null,
    h('h3', null, 'ASW hunt'), asw,
    h('p', { class: 'hint' }, 'Detect roll ≤ sub\'s detect rating, then ASW roll ≤ 10 sinks it.'),
    h('h3', null, 'Torpedo (range ≤ 2)'), torp,
    h('p', { class: 'hint' }, 'ASW-capable targets get an ASW check first. Submarine long-range strikes are in the Long-range strike tab.'));
}

// Resupply phase: draw down a supply unit of the active task force to refill any unit on the team.
function supplyPanel() {
  const head = h('h3', null, `Resupply phase: ${activeTF().name}`);
  const sources = myUnits().filter(u => u.category === 'logistics' && u.supply.s1 > 0);
  if (!sources.length) return h('div', null, head, h('p', { class: 'muted' }, 'No supply unit with supply left in this task force. End the turn when ready.'));
  const needy = teamGroups(activeTF().team, u => u.supplies.some(s => s.value < s.cap), u => u.name);
  if (!needy.some(g => g.items.length)) return h('div', null, head, h('p', { class: 'muted' }, 'Every unit on your team is fully supplied.'));

  const from = groupedSelect([{ label: activeTF().name, items: sources.map(u => ({ value: u.id, text: `${u.name} (${u.supply.s1} supply)` })) }]);
  const to = groupedSelect(needy);
  const slot = h('select');
  const amount = h('select', { size: 1 });
  const fillAmounts = () => {
    const s = U(to.value).supplies.find(x => x.key === slot.value);
    const max = Math.min(U(from.value).supply.s1, s.cap - s.value);
    amount.replaceChildren(...Array.from({ length: max }, (_, k) => h('option', { value: String(k + 1) }, `${k + 1}`)));
    amount.value = String(max);  // default: fill it up as far as possible
    submit.disabled = to.value === from.value || max < 1;
  };
  const fillSlots = () => {
    const short = U(to.value).supplies.filter(s => s.value < s.cap);
    slot.replaceChildren(...short.map(s => h('option', { value: s.key }, `${s.label} ${s.value}/${s.cap}`)));
    fillAmounts();
  };
  const submit = h('button', { class: 'primary', onclick: () => act('resupply', {
    from: from.value, to: to.value, slot: slot.value, amount: amount.value }) }, 'Resupply');
  from.onchange = fillAmounts;
  to.onchange = fillSlots;
  slot.onchange = fillAmounts;
  fillSlots();
  return h('div', null, head,
    h('div', { class: 'form-line' }, 'From', from),
    h('div', { class: 'form-line' }, 'To', to),
    h('div', { class: 'form-line' }, slot, 'Amount', amount),
    h('p', { class: 'hint' }, 'Draws from the supply unit, one point per roll. Any unit on your team can be refilled, up to its starting supply. Repeat for more units, then End turn.'),
    submit);
}

// ------------------------------------------------------------------ situation editor
function showEditor(original) {
  const draft = original ? structuredClone(original) : {
    name: '', map: '', preset: false,
    initiative: { start: 0, blue_wins_at: 10, red_wins_at: -10 },
    task_forces: [{ name: 'TF 1', team: 'blue', units: [] }, { name: 'TF 2', team: 'red', units: [] }],
  };
  const openGroups = new Map();  // task force object -> open unit-type groups; follows the TF when reordered
  const move = (i, d) => {
    const tfs = draft.task_forces;
    [tfs[i], tfs[i + d]] = [tfs[i + d], tfs[i]];
    render();
  };

  const render = () => {
    const owner = {};  // unit id -> task force name, to grey out units already used
    draft.task_forces.forEach(tf => tf.units.forEach(id => { owner[id] = tf.name; }));
    const field = (label, obj, key, type = 'text') => h('label', { class: 'row' }, label,
      h('input', { type, value: obj[key], oninput: e => { obj[key] = e.target.value; } }));

    app.replaceChildren(h('div', { class: 'editor panel' },
      h('h2', null, original ? `Edit situation: ${original.name}` : 'New custom situation'),
      h('div', { class: 'row' }, field('Name', draft, 'name'), field('Map', draft, 'map')),
      h('div', { class: 'row' }, 'Initiative:',
        field('start', draft.initiative, 'start', 'number'),
        field('Blue wins at ≥', draft.initiative, 'blue_wins_at', 'number'),
        field('Red wins at ≤', draft.initiative, 'red_wins_at', 'number')),
      h('p', { class: 'hint' }, 'Task forces take their turns in the order listed. Use ▲ ▼ to change it.'),
      draft.task_forces.map((tf, i) => taskForceEditor(tf, i)),
      h('div', { class: 'row', style: 'margin-top:12px' },
        h('button', { onclick: () => { draft.task_forces.push({ name: `TF ${draft.task_forces.length + 1}`, team: 'red', units: [] }); render(); } }, '+ Add task force'),
        h('button', { class: 'primary', title: 'Save', onclick: () => guard(async () => {
          await call('save_scenario', draft, original ? original.name : null);
          toast('Situation saved', true);
          showHome();
        }) }, '💾 Save'),
        original ? h('button', { class: 'danger', title: 'Delete', onclick: () => guard(async () => {
          if (confirm(`Delete situation "${original.name}"? Saved games are kept.`)) { await call('delete_scenario', original.name); showHome(); }
        }) }, '🗑 Delete') : null,
        h('button', { onclick: () => showHome() }, 'Cancel'))));

    function taskForceEditor(tf, i) {
      const types = CAT.types.filter(t => t.team === tf.team);
      const last = draft.task_forces.length - 1;
      if (!openGroups.has(tf)) openGroups.set(tf, new Set());
      const open = openGroups.get(tf);
      return h('div', { class: 'panel tf-edit' },
        h('div', { class: 'row' },
          h('strong', { title: 'Turn order' }, `#${i + 1}`),
          h('button', { class: 'small', title: 'Move earlier in the turn order', disabled: i === 0, onclick: () => move(i, -1) }, '▲'),
          h('button', { class: 'small', title: 'Move later in the turn order', disabled: i === last, onclick: () => move(i, 1) }, '▼'),
          h('input', { value: tf.name, oninput: e => { tf.name = e.target.value; } }),
          h('select', { value: tf.team, onchange: e => { tf.team = e.target.value; tf.units = []; render(); } },
            h('option', { value: 'blue' }, 'Blue'), h('option', { value: 'red' }, 'Red')),
          h('span', { class: 'muted' }, `${tf.units.length} unit(s)`),
          h('label', { class: 'row', title: 'Skipped in turn order and untouchable until the umpire marks it landed during the game' },
            h('input', { type: 'checkbox', checked: !!tf.requires_landing, onchange: e => { tf.requires_landing = e.target.checked; } }),
            'Must land before it plays'),
          draft.task_forces.length > 2 ? h('button', { class: 'danger', onclick: () => { draft.task_forces.splice(i, 1); render(); } }, 'Remove task force') : null),
        types.map(t => {
          const ids = t.units.map(n => `${t.team}:${n}`);
          const mine = ids.filter(id => tf.units.includes(id)).length;
          const det = h('details', { class: 'type-group', open: open.has(t.id) },
            h('summary', null, `${t.label} (${mine}/${ids.length})`),
            h('div', { class: 'unit-checks' }, ids.map(id => {
              const takenBy = owner[id] && !tf.units.includes(id) ? owner[id] : null;
              return h('label', { class: takenBy ? 'taken' : '', title: takenBy ? `In ${takenBy}` : '' },
                h('input', { type: 'checkbox', checked: tf.units.includes(id), disabled: !!takenBy, onchange: e => {
                  if (e.target.checked) tf.units.push(id); else tf.units.splice(tf.units.indexOf(id), 1);
                  render();
                } }), ' ', CAT.units.find(u => u.id === id).name);
            })));
          det.addEventListener('toggle', () => { det.open ? open.add(t.id) : open.delete(t.id); });
          return det;
        }));
    }
  };
  render();
}

// ------------------------------------------------------------------ boot
guard(async () => {
  CAT = await call('catalog');
  setUmpire(await call('umpire_status'));
  await showHome();
});
