'use strict';

/* =========================================================================
 * app.js — оболочка кампании sh2tw (бриф C, ТЗ 07 §7.5).
 * Ванильный ES6+ без сборщика и внешних библиотек (офлайн-игра).
 *
 * Имена полей сверены по коду бэка:
 *   api.py          — роуты, форма ошибок {"error": msg}, derived-поля;
 *   scene_client.py — prepare_battle (attacker_strength, defender_strength,
 *                     p_win_autoresolve, estimated_minutes, transitions,
 *                     battle_type), fight_scene (ok, scene_id, instruction,
 *                     reason, fallback), develop_region (applied, reason);
 *   season.py       — next_season (season, season_name, offers, events,
 *                     warnings), execute_attack/autoresolve (winner,
 *                     p_win_att, losses, survivors, applied.outcome/captured/
 *                     region), apply_battle_result;
 *   state.py        — структуру campaign_state (treasury, counters,
 *                     armies, diplomacy.pairs "a|b", pending_scenes[].map).
 * Все POST несут уникальный request_id — идемпотентность API.
 * ========================================================================= */

/* ------------------------------------------------------------- константы */

/* pacing.max_transitions_total API не отдаёт — заглушка из брифа C */
const MAX_TRANSITIONS_FALLBACK = 15;

const OWNER_COLORS = {
  player: '#2e5d34',    /* владения игрока — тёмно-зелёный  */
  ai: '#8b1a1a',        /* владения ИИ — красный акцент     */
  neutral: '#8a8070'    /* нейтральные — серый неактив      */
};

/* маппинг имён юнитов на русский (бриф C, экран 2) */
const UNITS_RU = {
  armedpeasant: 'крестьянин',
  spearman: 'копейщик',
  archer: 'лучник',
  maceman: 'пехотинец',
  crossbowman: 'арбалетчик',
  pikeman: 'пикинёр',
  swordsman: 'мечник',
  knight: 'рыцарь',
  catapult: 'катапульта',
  trebuchet: 'требюшет',
  ballista: 'баллиста',
  mangonel: 'мангонель',
  fireballista: 'огненная баллиста',
  burningcart: 'огненная повозка'
};

/* краткие формы для росписей: «18 лучн., 6 коп.» */
const UNITS_SHORT = {
  armedpeasant: 'крест.',
  spearman: 'коп.',
  archer: 'лучн.',
  maceman: 'пех.',
  crossbowman: 'арб.',
  pikeman: 'пик.',
  swordsman: 'мечн.',
  knight: 'рыц.',
  catapult: 'катап.',
  trebuchet: 'треб.',
  ballista: 'балл.',
  mangonel: 'манг.',
  fireballista: 'огн. балл.',
  burningcart: 'огн. повозка'
};

/* юниты с известной ценой (реестр ref/unit_types.csv) — селект найма */
const RECRUIT_UNITS = ['spearman', 'archer', 'maceman', 'crossbowman',
  'pikeman', 'swordsman', 'knight'];

const DIPLOMACY_RU = { war: 'война', peace: 'мир', alliance: 'союз' };

const OUTCOME_RU = {
  win_attacker: 'победа атакующего',
  win_defender: 'победа обороняющегося',
  draw: 'ничья',
  aborted: 'бой прерван (милосердие)'
};

const SCENE_TYPE_RU = {
  siege: 'штурм',
  field: 'полевой бой',
  defense: 'оборона',
  development: 'развитие'
};

const BATTLE_TYPE_RU = { siege: 'штурм замка', field: 'полевой бой' };

/* --------------------------------------------------------------- модель */

let model = null;          /* ответ GET /api/state: {state, derived}   */
let currentRegionId = null;
let battlePrep = null;     /* {target, data} — ответ /api/battle/prepare */
let lastReport = null;     /* панель итогов на экране 4                 */
let busy = false;          /* защита от двойных нажатий                 */

const $ = (sel) => document.querySelector(sel);

function st() { return model ? model.state : {}; }

function derived() {
  return model ? model.derived : {
    regions: [], treasury: {}, pending_offers: [], pending_scenes: [],
    victory: null
  };
}

/* id лорда-игрока: владелец армии, которого нет в ai_treasury
 * (state.py держит казны ИИ отдельно от игрока) */
function playerId() {
  const ai = new Set(Object.keys(st().ai_treasury || {}));
  const armies = Object.values(st().armies || {});
  for (const a of armies) {
    if (a && a.owner && !ai.has(a.owner)) return a.owner;
  }
  return 'player';
}

function regionById(id) {
  return (derived().regions || []).find((r) => r.id === id) || null;
}

function regionName(id) {
  const r = regionById(id);
  return r ? r.name : id;
}

function armyOfPlayer() {
  return Object.values(st().armies || {})
    .find((a) => a && a.owner === playerId()) || null;
}

function rosterTotal(roster) {
  let n = 0;
  Object.values(roster || {}).forEach((rec) => {
    n += (typeof rec === 'object') ? (rec.count || 0) : rec;
  });
  return n;
}

/* роспись → «18 лучн., 6 коп.» */
function rosterLines(roster, short) {
  const entries = Object.entries(roster || {})
    .map(([unit, rec]) => [unit, (typeof rec === 'object')
      ? (rec.count || 0) : rec])
    .filter(([, n]) => n > 0);
  if (!entries.length) return '—';
  return entries.map(([unit, n]) => {
    const name = short ? (UNITS_SHORT[unit] || unit) : (UNITS_RU[unit] || unit);
    return n + ' ' + name;
  }).join(', ');
}

/* потери {lord: {unit: n}} → «вы: 3 лучн.; l_hawk: 8 коп.» */
function lossesLines(losses) {
  const out = [];
  Object.entries(losses || {}).forEach(([lord, l]) => {
    const parts = Object.entries(l || {})
      .map(([u, n]) => n + ' ' + (UNITS_SHORT[u] || u));
    if (parts.length) {
      out.push((lord === playerId() ? 'вы' : lord) + ': ' + parts.join(', '));
    }
  });
  return out.length ? out.join('; ') : 'без потерь';
}

/* ключ пары дипломатии — лорды по алфавиту через «|» (state.pair_key) */
function pairKey(a, b) { return [a, b].sort().join('|'); }

function pairStatus(lord) {
  const pairs = (st().diplomacy || {}).pairs || {};
  return pairs[pairKey(playerId(), lord)] || 'peace';
}

function lordLabel(lord) { return lord === playerId() ? 'вы' : lord; }

/* --------------------------------------------------------------- утилиты */

function esc(v) {
  return String(v == null ? '' : v)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function uuid() {
  if (window.crypto && typeof window.crypto.randomUUID === 'function') {
    return window.crypto.randomUUID();
  }
  return 'req-' + Date.now().toString(16) + '-' +
    Math.random().toString(16).slice(2) + Math.random().toString(16).slice(2);
}

async function readError(res) {
  let msg = 'HTTP ' + res.status;
  try {
    const data = await res.json();
    /* бэк отвечает {"error": msg} (api.py), фреймворк — {"detail": msg} */
    msg = (data && (data.error || data.detail)) || msg;
  } catch (e) { /* тело не JSON — оставляем код статуса */ }
  return new Error(msg);
}

async function apiGet(path) {
  const res = await fetch(path);
  if (!res.ok) throw await readError(res);
  return res.json();
}

async function apiPost(path, body) {
  const payload = Object.assign({ request_id: uuid() }, body || {});
  const res = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });
  if (!res.ok) throw await readError(res);
  return res.json();
}

/* ---------------------------------------------------------------- тосты */

function toast(message, kind) {
  const box = document.createElement('div');
  box.className = 'toast ' + (kind === 'error' ? 'toast-error' : 'toast-ok');
  box.textContent = message;
  $('#toasts').appendChild(box);
  setTimeout(() => box.classList.add('toast-hide'), 4000);
  setTimeout(() => box.remove(), 4500);
}

/* ---------------------------------------------------------- экраны/вкладки */

function showScreen(name) {
  document.querySelectorAll('main .screen').forEach((sec) => {
    sec.classList.toggle('active', sec.id === name);
  });
  document.querySelectorAll('#tabs .tab').forEach((t) => {
    t.classList.toggle('active', t.dataset.screen === name);
  });
}

/* ------------------------------------------------------------ шапка/карта */

function renderHeader() {
  const s = st();
  const d = derived();
  const used = (s.counters || {}).transitions_used || 0;
  const army = armyOfPlayer();
  $('#season-line').textContent =
    'Сезон ' + (s.season != null ? s.season : '?') +
    ' (' + (s.season_name || '—') + ') · фаза: ' + (s.phase || '—');
  $('#stats-bar').innerHTML =
    '<span class="stat">Казна: <b>' + esc((d.treasury || {}).gold) +
    '</b> з.</span>' +
    '<span class="stat">Честь: <b>' + esc((d.treasury || {}).honour) + '</b></span>' +
    '<span class="stat">Ранг: <b>' + esc((d.treasury || {}).rank) + '</b></span>' +
    '<span class="stat">Переходы: <b>' + used + '/' + MAX_TRANSITIONS_FALLBACK +
    '</b></span>' +
    '<span class="stat">Армия: <b>' + rosterTotal(army && army.roster) +
    '</b> (' + esc(army && army.located_region || '—') + ')</span>';
}

function nodeColor(owner) {
  if (!owner) return OWNER_COLORS.neutral;
  return owner === playerId() ? OWNER_COLORS.player : OWNER_COLORS.ai;
}

/* детерминированный хэш строки (FNV-1a) — для позиций узлов */
function hash32(s) {
  let h = 2166136261 >>> 0;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619) >>> 0;
  }
  return h >>> 0;
}

/* псевдо-география: цикличная сетка с jitter по хэшу id + расталкивание
 * (реальных координат API не даёт — бриф C) */
function layoutNodes(regions) {
  const W = 900, H = 560, MX = 105, MY = 72, MIN_DIST = 90;
  const n = regions.length;
  if (!n) return [];
  const cols = Math.max(1, Math.ceil(Math.sqrt(n * W / H)));
  const rows = Math.ceil(n / cols);
  const cw = (W - 2 * MX) / cols;
  const ch = (H - 2 * MY) / rows;
  const nodes = regions.map((r, i) => {
    const h = hash32(r.id);
    const col = i % cols;
    const row = Math.floor(i / cols);
    return {
      id: r.id,
      region: r,
      x: MX + cw * (col + 0.5) + (((h % 1000) / 1000) - 0.5) * cw * 0.55,
      y: MY + ch * (row + 0.5) + ((((h >>> 10) % 1000) / 1000) - 0.5) * ch * 0.55
    };
  });
  for (let it = 0; it < 60; it++) {
    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        const a = nodes[i], b = nodes[j];
        let dx = b.x - a.x;
        let dy = b.y - a.y;
        const d = Math.hypot(dx, dy) || 0.01;
        if (d >= MIN_DIST) continue;
        const push = (MIN_DIST - d) / 2;
        dx = (dx / d) * push;
        dy = (dy / d) * push;
        a.x -= dx; a.y -= dy;
        b.x += dx; b.y += dy;
      }
    }
    nodes.forEach((nd) => {
      nd.x = Math.min(W - MX, Math.max(MX, nd.x));
      nd.y = Math.min(H - MY, Math.max(MY, nd.y));
    });
  }
  return nodes;
}

function renderMap() {
  const host = $('#map-canvas');
  if (!model) return;
  const regions = derived().regions || [];
  const nodes = layoutNodes(regions);
  const byId = {};
  nodes.forEach((nd) => { byId[nd.id] = nd; });

  const edges = [];
  regions.forEach((r) => {
    (r.neighbors || []).forEach((nb) => {
      if (byId[nb] && r.id < nb) edges.push([byId[r.id], byId[nb]]);
    });
  });

  let svg = '<svg viewBox="0 0 900 560" role="img" aria-label="Карта кампании">' +
    '<rect x="4" y="4" width="892" height="552" rx="14" class="map-bg"/>';
  edges.forEach(([a, b]) => {
    svg += '<line x1="' + a.x.toFixed(1) + '" y1="' + a.y.toFixed(1) +
      '" x2="' + b.x.toFixed(1) + '" y2="' + b.y.toFixed(1) +
      '" class="map-edge"/>';
  });
  nodes.forEach((nd) => {
    const r = nd.region;
    const radius = r.type === 'castle' ? 21 : 14;
    const x = nd.x.toFixed(1);
    const y = nd.y.toFixed(1);
    const lv = (r.type === 'castle' && r.castle_level > 0)
      ? '<text class="map-lv" x="' + x + '" y="' +
        (nd.y + radius + 30).toFixed(1) + '">♦' + r.castle_level + '</text>'
      : '';
    svg += '<g class="map-node" data-action="open-region" data-region="' +
      esc(r.id) + '">' +
      '<title>' + esc(r.name) + ' · ' +
      (r.type === 'castle' ? 'замок' : 'деревня') + ' · владелец: ' +
      esc(r.owner || 'нейтральный') + ' · гарнизон: ' + r.garrison_total +
      '</title>' +
      '<circle cx="' + x + '" cy="' + y + '" r="' + (radius + 7) +
      '" fill="transparent"/>' +
      '<circle cx="' + x + '" cy="' + y + '" r="' + radius +
      '" fill="' + nodeColor(r.owner) + '" class="map-node-body"/>' +
      (r.type === 'castle'
        ? '<circle cx="' + x + '" cy="' + y + '" r="' + (radius - 6) +
          '" class="map-ring"/>'
        : '') +
      '<text class="map-name" x="' + x + '" y="' +
      (nd.y + radius + 17).toFixed(1) + '">' + esc(r.name) + '</text>' +
      lv + '</g>';
  });
  svg += '</svg>';
  host.innerHTML = svg;
}

/* ------------------------------------------- баннеры: победа, предложения */

function renderVictory() {
  const el = $('#victory-banner');
  const v = derived().victory;
  if (!v) { el.innerHTML = ''; return; }
  if (v.level === 'defeat') {
    el.innerHTML = '<div class="victory victory-defeat">' +
      '<h2>Поражение</h2>' +
      '<p>Все владения потеряны (сезон ' + esc(v.season) +
      '). Кампания продолжается в sandbox.</p></div>';
    return;
  }
  el.innerHTML = '<div class="victory victory-win">' +
    '<h2>Победа!</h2>' +
    '<p>Уровень: <b>' + esc(v.level) + '</b> · сезон ' + esc(v.season) +
    '. Кампания продолжается в sandbox.</p></div>';
}

function offerText(o) {
  if (o.offer === 'battle') {
    return lordLabel(o.attacker) + ' выступает на «' +
      regionName(o.target_region) + '» — ваше решение:';
  }
  if (o.offer === 'peace') {
    return lordLabel(o.from) + ' предлагает мир';
  }
  if (o.offer === 'mercenaries') {
    return 'Наёмники предлагают роспись со скидкой ' +
      Math.round((o.discount || 0) * 100) + ' %';
  }
  return 'Предложение: ' + (o.offer || '?');
}

function renderOffers() {
  const el = $('#offers-banner');
  const offers = derived().pending_offers || [];
  if (!offers.length) { el.innerHTML = ''; return; }
  el.innerHTML = '<h2 class="offers-title">Решения ждут лорда</h2>' +
    offers.map((o, i) =>
      '<div class="card offer-card">' +
      '<div class="offer-text">' + esc(offerText(o)) + '</div>' +
      '<div class="offer-actions">' +
      '<button class="btn btn-ok" type="button" data-action="offer-decide" ' +
      'data-index="' + i + '" data-accept="1">Принять</button>' +
      '<button class="btn btn-danger" type="button" data-action="offer-decide" ' +
      'data-index="' + i + '" data-accept="0">Отказать</button>' +
      '</div></div>').join('');
}

/* --------------------------------------------------- экран 2: регион ---- */

/* достижимая цель атаки: чужой регион-сосед владений игрока (api.py) */
function isReachableTarget(regionId) {
  const pid = playerId();
  const mine = (derived().regions || []).filter((r) => r.owner === pid);
  return mine.some((r) => (r.neighbors || []).includes(regionId));
}

function renderRegion() {
  const panel = $('#region-panel');
  if (!currentRegionId || !model) {
    panel.innerHTML = '<p class="muted">Выберите регион на карте кампании.</p>';
    return;
  }
  const d = regionById(currentRegionId);
  if (!d) {
    panel.innerHTML = '<p class="muted">Регион не найден.</p>';
    return;
  }
  const rs = (st().regions || {})[currentRegionId] || {};
  const pid = playerId();
  const own = d.owner === pid;
  const typeRu = d.type === 'castle' ? 'замок' : 'деревня';

  let html = '<div class="panel-head"><h2>' + esc(d.name) +
    ' <span class="muted">(' + esc(d.id) + ', ' + typeRu + ')</span></h2>' +
    '<button class="btn btn-ghost" type="button" data-action="back-map">← Назад на карту</button></div>';

  html += '<ul class="facts">' +
    '<li>Владелец: <b>' + (d.owner ? esc(d.owner) : 'нейтральный') + '</b></li>' +
    '<li>Застройка: <b>' +
    (d.type === 'castle' ? d.castle_level + '/5' : '—') + '</b></li>' +
    '<li>Лояльность: <b>' + esc(rs.loyalty != null ? rs.loyalty : '—') +
    '</b></li>' +
    '<li>Доход: <b>' + d.income + '</b> з/сезон</li>' +
    '<li>Гарнизон: <b>' + d.garrison_total + '</b> — ' +
    esc(rosterLines(rs.garrison, true)) + '</li>' +
    (d.type === 'castle'
      ? '<li>Очки развития: <b>' + esc(rs.development_points || 0) + '</b></li>'
      : '') +
    '</ul>';

  const neighbors = (d.neighbors || []);

  if (own) {
    html += '<div class="region-actions">';
    if (d.type === 'castle') {
      html += '<button class="btn" type="button" data-action="develop" ' +
        'data-region="' + esc(d.id) + '">Развивать владение (сцена) 🏗</button>';
    }
    html += '<form id="recruit-form" class="inline-form">' +
      '<select id="recruit-unit">' +
      RECRUIT_UNITS.map((u) =>
        '<option value="' + u + '">' + UNITS_RU[u] + '</option>').join('') +
      '</select>' +
      '<input id="recruit-count" type="number" min="1" step="1" value="5" ' +
      'aria-label="Число юнитов">' +
      '<button class="btn" type="submit">Набрать войск</button>' +
      '</form></div>' +
      '<p class="hint">Цена найма — двойная стоимость юнита; армия берёт ' +
      'гарнизон при походе.</p>';

    /* соседние нейтральные деревни — покупка за честь (сервер проверит) */
    const villages = neighbors
      .map((nb) => regionById(nb))
      .filter((nb) => nb && nb.type === 'village' && !nb.owner);
    if (villages.length) {
      html += '<h3>Соседние нейтральные деревни</h3><ul class="sublist">';
      villages.forEach((v) => {
        html += '<li>«' + esc(v.name) + '» (' + esc(v.id) + ') — ' +
          '<button class="btn btn-small" type="button" data-action="buy" ' +
          'data-region="' + esc(v.id) + '">Купить деревню</button></li>';
      });
      html += '</ul>';
    }
  } else if (!d.owner) {
    if (d.type === 'village') {
      html += '<div class="region-actions">' +
        '<button class="btn" type="button" data-action="buy" data-region="' +
        esc(d.id) + '">Купить деревню</button></div>' +
        '<p class="hint">Покупка нейтральной деревни-соседа за честь ' +
        '(сервер проверит соседство и казну чести).</p>';
    } else {
      html += '<p class="muted">Нейтральная земля: атака невозможна, ' +
        'деревни покупают за честь.</p>';
    }
  } else {
    html += '<div class="region-actions">' +
      '<button class="btn btn-primary" type="button" data-action="prepare" ' +
      'data-region="' + esc(d.id) + '">Подготовить поход ▶</button></div>';
    if (!isReachableTarget(d.id)) {
      html += '<p class="hint">Регион не соседствует с вашими владениями — ' +
        'поход будет отклонён.</p>';
    }
  }

  panel.innerHTML = html;
}

/* ------------------------------------------------- экран 3: подготовка -- */

function renderBattle() {
  const panel = $('#battle-panel');
  if (!battlePrep || !model) {
    panel.innerHTML = '<p class="muted">Нет подготовленного похода: выберите ' +
      'чужой регион и нажмите «Подготовить поход».</p>';
    return;
  }
  const target = battlePrep.target;
  const data = battlePrep.data;
  const d = regionById(target);
  const rs = (st().regions || {})[target] || {};
  const army = armyOfPlayer();
  const pWin = Math.round((data.p_win_autoresolve || 0) * 100);

  panel.innerHTML =
    '<div class="panel-head"><h2>Поход на «' + esc(regionName(target)) +
    '» <span class="muted">(' + esc(BATTLE_TYPE_RU[data.battle_type] ||
    data.battle_type) + ')</span></h2>' +
    '<button class="btn btn-ghost" type="button" data-action="back-map">Отмена</button></div>' +
    '<div class="battle-sides">' +
    '<div class="side side-ours"><h3>Наши силы</h3>' +
    '<p>' + esc(rosterLines(army && army.roster)) + '</p>' +
    '<p>Сила: <b>' + data.attacker_strength + '</b></p></div>' +
    '<div class="side side-theirs"><h3>Оборона цели</h3>' +
    '<p>' + esc(rosterLines(rs.garrison)) + '</p>' +
    '<p>Замок: <b>' + esc(d ? d.castle_level : '?') + '</b> · Сила: <b>' +
    data.defender_strength + '</b></p></div>' +
    '</div>' +
    '<p class="forecast">Прогноз авто-резолва: <b>' + pWin + ' %</b> · ' +
    'Цена: ~' + data.estimated_minutes + ' мин, переходы ' +
    esc(data.transitions) + '</p>' +
    '<div class="region-actions">' +
    '<button class="btn btn-primary" type="button" data-action="autoresolve" ' +
    'data-region="' + esc(target) + '">Авто-резолв</button>' +
    '<button class="btn" type="button" data-action="fight-scene" ' +
    'data-region="' + esc(target) + '">Бой в игре (сцена)</button>' +
    '</div>' +
    '<p class="hint">Сцена собирает карту с балансировкой провижининга ' +
    '(±10 %); если карт нет — останется авто-резолв.</p>';
}

/* ---------------------------------------------------- экран 4: итоги ---- */

function renderReport() {
  const el = $('#result-report');
  if (!lastReport) {
    el.innerHTML = '<div class="panel report"><div class="panel-head">' +
      '<h2>Итоги</h2></div><p class="muted">Здесь появятся результаты боёв ' +
      'и инструкции по сценам.</p></div>';
    return;
  }
  if (lastReport.kind === 'scene_wait') {
    const d = lastReport.data;
    el.innerHTML = '<div class="panel report">' +
      '<div class="panel-head"><h2>' + esc(lastReport.title ||
      'Сцена собрана') + '</h2></div>' +
      '<p class="instruction">' + esc(d.instruction || '') + '</p>' +
      '<p class="muted">Сыграйте карту в Stronghold 2, затем введите исход ' +
      'в разделе «Незакрытые сцены» ниже.</p></div>';
    return;
  }
  const d = lastReport.data || {};
  const applied = d.applied || {};
  const winner = !d.winner ? 'ничья' : lordLabel(d.winner);
  el.innerHTML = '<div class="panel report">' +
    '<div class="panel-head"><h2>' + esc(lastReport.title || 'Итоги боя') +
    '</h2></div><ul class="facts">' +
    '<li>Победитель: <b>' + esc(winner) + '</b></li>' +
    '<li>Исход: <b>' + esc(OUTCOME_RU[applied.outcome] || applied.outcome ||
    '—') + '</b></li>' +
    '<li>Регион «' + esc(regionName(applied.region)) + '»: <b>' +
    (applied.captured ? 'захвачен' : 'остался у обороняющегося') + '</b></li>' +
    '<li>Потери: ' + esc(lossesLines(d.losses)) + '</li>' +
    '<li>Прогноз был: <b>' + Math.round((d.p_win_att || 0) * 100) +
    ' %</b></li>' +
    '</ul></div>';
}

/* GET /api/scene/pending — незакрытые сцены (ручной ввод исхода) */
async function renderPendingScenes() {
  const el = $('#pending-scenes');
  let scenes = [];
  try {
    scenes = await apiGet('/api/scene/pending');
  } catch (e) {
    el.innerHTML = '<p class="muted">' + esc(e.message) + '</p>';
    return;
  }
  if (!scenes.length) {
    el.innerHTML = '<p class="muted">Незакрытых сцен нет.</p>';
    return;
  }
  el.innerHTML = scenes.map((s) =>
    '<div class="card scene-card">' +
    '<div><b>' + esc(SCENE_TYPE_RU[s.type] || s.type) + '</b> · «' +
    esc(regionName(s.target_region)) + '» · ' + esc(lordLabel(s.attacker_lord)) +
    ' против ' + esc(lordLabel(s.defender_lord)) + '</div>' +
    '<div class="scene-map">Карта: ' + esc(s.map) + '</div>' +
    '<div class="scene-actions">' +
    '<button class="btn btn-ok btn-small" type="button" ' +
    'data-action="scene-outcome" data-scene="' + esc(s.scene_id) + '" ' +
    'data-outcome="win">Победа</button>' +
    '<button class="btn btn-danger btn-small" type="button" ' +
    'data-action="scene-outcome" data-scene="' + esc(s.scene_id) + '" ' +
    'data-outcome="loss">Поражение</button>' +
    '<button class="btn btn-small" type="button" ' +
    'data-action="scene-outcome" data-scene="' + esc(s.scene_id) + '" ' +
    'data-outcome="draw">Ничья</button>' +
    '</div></div>').join('');
}

function renderDiplomacy() {
  const el = $('#diplomacy');
  if (!model) return;
  const pid = playerId();
  const lords = new Set();
  (derived().regions || []).forEach((r) => {
    if (r.owner && r.owner !== pid) lords.add(r.owner);
  });
  if (!lords.size) {
    el.innerHTML = '<p class="muted">Нет известных ИИ-лордов.</p>';
    return;
  }
  el.innerHTML = Array.from(lords).sort().map((lord) => {
    const status = pairStatus(lord);
    return '<div class="dip-row">' +
      '<span class="dip-lord">' + esc(lord) + '</span>' +
      '<span class="dip-status dip-' + status + '">' +
      esc(DIPLOMACY_RU[status] || status) + '</span>' +
      '<button class="btn btn-small" type="button" data-action="diplomacy" ' +
      'data-lord="' + esc(lord) + '" data-dip="peace">Мир</button>' +
      '<button class="btn btn-small" type="button" data-action="diplomacy" ' +
      'data-lord="' + esc(lord) + '" data-dip="alliance">Союз</button>' +
      '</div>';
  }).join('');
}

function renderResults() {
  renderReport();
  renderPendingScenes();
  renderDiplomacy();
}

function renderAll() {
  if (!model) return;
  renderHeader();
  renderVictory();
  renderOffers();
  renderMap();
  renderRegion();
  renderBattle();
  renderResults();
}

/* --------------------------------------------------------- журнал сезона */

function openJournal() {
  const log = st().events_log || [];
  const prefix = 'S' + (st().season != null ? st().season : '') + ':';
  let items = log.filter((line) => line.indexOf(prefix) === 0);
  if (!items.length) items = log.slice(-25);
  $('#journal-list').innerHTML = items.length
    ? items.map((l) => '<li>' + esc(l) + '</li>').join('')
    : '<li class="muted">Журнал пуст.</li>';
  $('#journal-overlay').classList.remove('hidden');
}

function closeJournal() {
  $('#journal-overlay').classList.add('hidden');
}

/* ------------------------------------------------------------ действия -- */

async function refresh() {
  try {
    const res = await fetch('/api/state');
    if (!res.ok) throw await readError(res);
    model = await res.json();
  } catch (e) {
    toast('Не удалось получить состояние: ' + e.message, 'error');
    return;
  }
  renderAll();
}

function guard() {
  if (busy) return false;
  busy = true;
  return true;
}

async function doSeasonNext() {
  if (!guard()) return;
  try {
    const res = await apiPost('/api/season/next', {});
    const parts = ['Сезон ' + res.season + ' (' + res.season_name + ')'];
    const offers = res.offers || [];
    if (offers.length) parts.push('Предложений: ' + offers.length);
    const events = res.events || [];
    if (events.length) {
      parts.push('События: ' + events.map((e) => e.id).join(', '));
    }
    const warns = res.warnings || [];
    if (warns.length) parts.push('Предупреждения: ' + warns.join('; '));
    toast(parts.join('\n'), 'ok');
  } catch (e) {
    toast(e.message, 'error');
  }
  busy = false;
  await refresh();
}

async function doUndo() {
  if (!guard()) return;
  try {
    const res = await apiPost('/api/undo', {});
    toast('Откат: сезон ' + res.season + ', фаза ' + res.phase, 'ok');
  } catch (e) {
    toast(e.message, 'error');
  }
  busy = false;
  await refresh();
}

async function doDevelop(regionId) {
  if (!guard()) return;
  try {
    const res = await apiPost(
      '/api/region/' + encodeURIComponent(regionId) + '/develop', {});
    if (res.ok === false) {
      if (res.applied) {
        toast('Театр недоступен (' + res.reason + '). Применено мгновенно: −' +
          res.applied.gold_spent + ' з, +' +
          res.applied.development_points + ' очков', 'ok');
      } else {
        toast('Развитие не удалось: ' + res.reason, 'error');
      }
    } else {
      lastReport = {
        kind: 'scene_wait',
        data: res,
        title: 'Сцена развития: «' + regionName(regionId) + '»'
      };
      showScreen('screen-results');
      toast(res.instruction || 'Сцена развития собрана', 'ok');
    }
  } catch (e) {
    toast(e.message, 'error');
  }
  busy = false;
  await refresh();
}

async function doRecruit(regionId, unit, n) {
  if (!unit) { toast('Выберите тип юнита', 'error'); return; }
  if (!Number.isInteger(n) || n <= 0) {
    toast('Число юнитов должно быть целым больше нуля', 'error');
    return;
  }
  if (!guard()) return;
  try {
    const res = await apiPost(
      '/api/region/' + encodeURIComponent(regionId) + '/recruit',
      { units: { [unit]: n } });
    toast('Нанято: ' + n + ' × ' + (UNITS_RU[unit] || unit) + ' за ' +
      res.cost + ' з (в казне ' + res.gold + ' з)', 'ok');
  } catch (e) {
    toast(e.message, 'error');
  }
  busy = false;
  await refresh();
}

async function doBuy(regionId) {
  if (!guard()) return;
  try {
    const res = await apiPost(
      '/api/region/' + encodeURIComponent(regionId) + '/buy', {});
    toast('Куплена деревня «' + regionName(res.region) + '» за ' +
      res.cost_honour + ' чести (осталось ' + res.honour + ')', 'ok');
  } catch (e) {
    toast(e.message, 'error');
  }
  busy = false;
  await refresh();
}

async function doPrepare(regionId) {
  if (!guard()) return;
  try {
    const res = await apiPost('/api/battle/prepare',
      { target_region: regionId });
    battlePrep = { target: regionId, data: res };
    showScreen('screen-battle');
    renderBattle();
  } catch (e) {
    toast(e.message, 'error');
  }
  busy = false;
}

async function doAutoresolve(regionId) {
  if (!guard()) return;
  try {
    const res = await apiPost('/api/battle/autoresolve',
      { target_region: regionId });
    lastReport = {
      kind: 'battle',
      data: res,
      title: 'Итоги похода на «' + regionName(regionId) + '»'
    };
    battlePrep = null;
    showScreen('screen-results');
  } catch (e) {
    toast(e.message, 'error');
  }
  busy = false;
  await refresh();
}

async function doFightScene(regionId) {
  if (!guard()) return;
  try {
    const res = await apiPost('/api/battle/scene',
      { target_region: regionId });
    if (res.ok) {
      lastReport = {
        kind: 'scene_wait',
        data: res,
        title: 'Сцена боя: «' + regionName(regionId) + '»'
      };
      battlePrep = null;
      showScreen('screen-results');
      toast(res.instruction || 'Карта собрана', 'ok');
    } else {
      toast('Карта не собралась: ' + res.reason + '. Доступен авто-резолв',
        'error');
    }
  } catch (e) {
    toast(e.message, 'error');
  }
  busy = false;
  await refresh();
}

async function doSceneResult(sceneId, outcome) {
  if (!guard()) return;
  try {
    const res = await apiPost('/api/scene/result',
      { scene_id: sceneId, outcome: outcome });
    let msg = res.summary || 'Итог сцены применён';
    if (res.captured === true) msg += ' — регион захвачен!';
    else if (res.captured === false) msg += ' — регион удержан обороной.';
    toast(msg, 'ok');
  } catch (e) {
    toast(e.message, 'error');
  }
  busy = false;
  await refresh();
}

async function doDiplomacy(action, lord) {
  if (!guard()) return;
  try {
    const res = await apiPost('/api/diplomacy', { action: action, with: lord });
    toast(res.summary || ('Дипломатия: ' + action + ' с ' + lord), 'ok');
  } catch (e) {
    toast(e.message, 'error');
  }
  busy = false;
  await refresh();
}

async function doOfferDecide(index, accept) {
  if (!guard()) return;
  try {
    const res = await apiPost('/api/offer/decide',
      { index: Number(index), accept: accept });
    if (accept && res.offer && res.offer.offer === 'battle' &&
        res.result && typeof res.result === 'object') {
      lastReport = {
        kind: 'battle',
        data: res.result,
        title: 'Итоги обороны (предложение боя)'
      };
      showScreen('screen-results');
    }
    toast(res.summary || 'Решение принято', 'ok');
  } catch (e) {
    toast(e.message, 'error');
  }
  busy = false;
  await refresh();
}

function openRegion(regionId) {
  currentRegionId = regionId;
  showScreen('screen-region');
  renderRegion();
}

/* --------------------------------------------------- делегирование ввода */

function onAction(ev) {
  const btn = ev.target.closest('[data-action]');
  if (!btn) return;
  const action = btn.dataset.action;
  switch (action) {
    case 'open-region': openRegion(btn.dataset.region); break;
    case 'back-map':
      currentRegionId = null;
      battlePrep = null;
      showScreen('screen-map');
      break;
    case 'develop': doDevelop(btn.dataset.region); break;
    case 'buy': doBuy(btn.dataset.region); break;
    case 'prepare': doPrepare(btn.dataset.region); break;
    case 'autoresolve': doAutoresolve(btn.dataset.region); break;
    case 'fight-scene': doFightScene(btn.dataset.region); break;
    case 'scene-outcome':
      doSceneResult(btn.dataset.scene, btn.dataset.outcome);
      break;
    case 'diplomacy': doDiplomacy(btn.dataset.dip, btn.dataset.lord); break;
    case 'offer-decide':
      doOfferDecide(btn.dataset.index, btn.dataset.accept === '1');
      break;
    default: break;
  }
}

function onSubmit(ev) {
  const form = ev.target;
  if (!form || form.id !== 'recruit-form') return;
  ev.preventDefault();
  const unit = $('#recruit-unit').value;
  const n = parseInt($('#recruit-count').value, 10);
  doRecruit(currentRegionId, unit, n);
}

/* ---------------------------------------------------------------- init -- */

function init() {
  $('#btn-undo').addEventListener('click', doUndo);
  $('#btn-season-next').addEventListener('click', doSeasonNext);
  $('#btn-journal').addEventListener('click', openJournal);
  $('#journal-close').addEventListener('click', closeJournal);
  $('#journal-overlay').addEventListener('click', (ev) => {
    if (ev.target.id === 'journal-overlay') closeJournal();
  });
  $('#tabs').addEventListener('click', (ev) => {
    const tab = ev.target.closest('.tab');
    if (tab) showScreen(tab.dataset.screen);
  });
  document.addEventListener('click', onAction);
  document.addEventListener('submit', onSubmit);
  refresh();
}

document.addEventListener('DOMContentLoaded', init);
