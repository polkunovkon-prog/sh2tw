"""state.py — конфигурация/состояние кампании, история, undo, журнал (03 §3.1–3.2).

campaign_config.json валидируется и нормализуется дефолтами брифа К1;
campaign_state.json меняется только оболочкой, атомарно (tmp+rename), со
слепками history/state_<season>_<n>.json (undo ≤3 шагов) и журналом
events.jsonl. Казна/честь лордов — economy.py; росписи/силы — autoresolve.py.
Детерминизм: любой RNG выводится из rng_seed + season.
"""
from __future__ import annotations

import json
import os
import random
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "1.0"
CONFIG_NAME = "campaign_config.json"
STATE_NAME = "campaign_state.json"
HISTORY_DIR = "history"
EVENTS_JL = "events.jsonl"
STATIC_DIR = "static"
SEASONS_RU = ("Весна", "Лето", "Осень", "Зима")
DIPLOMACY_STATES = ("war", "peace", "alliance")
VICTORY_TYPES = ("eliminate_lords", "control_regions")
REGION_TYPES = ("castle", "village")
PERSONA_TRAITS = ("aggression", "greed", "builder", "loyal")
UNDO_MAX_STEPS = 3
# старт новой партии (бриф К1; игрок и ИИ равны — честность 07 §7.10)
START_GOLD = 500
START_HONOUR = 100
START_RANK = 1
START_LOYALTY = 60
START_DEV_POINTS = 30              # → castle_level 1 по порогам 07 §7.7
START_GARRISON = {"spearman": 10, "archer": 6}
START_ARMY = {"spearman": 12, "archer": 8}
DEV_THRESHOLDS = (25, 60, 120, 200, 300)   # очки → уровни замка 1..5
VILLAGE_COST_HONOUR = 100          # покупка деревни за честь (G1)
# дефолты блоков конфига (образец 03 §3.1; кампания уточняет поля)
DEFAULT_ECONOMY = {"village_tax_gold_per_month": 50,
                   "army_upkeep_gold_per_unit_month": 0.2,
                   "honour_festival_income": 8}
DEFAULT_PACING = {"seasons_per_year": 4, "max_transitions_total": 15,
                  "theater_cooldown_seasons": 3, "max_empty_seasons_streak": 2,
                  "field_scene_minutes": [20, 45], "theater_months": [24, 36]}
DEFAULT_AUTORESOLVE = {"unit_value_source": "ref/unit_types.csv",
                       "wall_bonus_per_castle_level": 0.15, "logit_k": 3.0}
DEFAULT_EVENT_PROBS = {"harvest_failure": 0.08, "plague": 0.05, "rats": 0.07,
                       "fair": 0.10, "mercenaries": 0.08, "harsh_winter": 0.06,
                       "embassy": 0.07, "hunt": 0.09, "feast": 0.06,
                       "rebellion": 0.0}

_SNAP_RE = re.compile(r"^state_(\d+)_(\d+)\.json$")
_END_RE = re.compile(r"^state_(\d+)_end\.json$")


class ConfigError(Exception):
    """Некорректная конфигурация кампании (campaign_config.json)."""


class TransitionError(Exception):
    """Запрещённый переход состояния (фаза сезона, кулдаун, бюджет)."""


# ------------------------------------------------------------- конфигурация
def validate_config(config: dict) -> None:
    """Правила 03 §3.1: связность BFS, симметрия соседств, уникальность id,
    castle_levels/map_template у замков, persona ИИ, victory.short.type.
    Бросает ConfigError с указанием места нарушения."""
    if not isinstance(config, dict):
        raise ConfigError("campaign_config: ожидался объект JSON")
    for key in ("schema_version", "campaign_id", "title"):
        if not config.get(key):
            raise ConfigError(f"campaign_config.{key}: обязательное поле")
    regions = config.get("regions")
    if not isinstance(regions, list) or not regions:
        raise ConfigError("regions: непустой список")
    region_ids = [r.get("id") for r in regions]
    if any(not rid for rid in region_ids):
        raise ConfigError("region.id: обязателен у всех регионов")
    if len(set(region_ids)) != len(region_ids):
        raise ConfigError(f"regions: дубликат id в {region_ids}")
    by_id = {r["id"]: r for r in regions}
    for r in regions:
        if r.get("type") not in REGION_TYPES:
            raise ConfigError(f"region {r['id']}: type ∉ {REGION_TYPES}")
        if r["type"] == "castle":
            if not (r.get("castle_levels") or {}):
                raise ConfigError(f"region {r['id']}: castle без castle_levels")
            if not r.get("map_template"):
                raise ConfigError(f"region {r['id']}: castle без map_template")
        for nb in r.get("neighbors") or []:
            if nb not in by_id:
                raise ConfigError(f"region {r['id']}: сосед {nb!r} не существует")
            if nb == r["id"]:
                raise ConfigError(f"region {r['id']}: соседствует сам с собой")
            if r["id"] not in (by_id[nb].get("neighbors") or []):
                raise ConfigError(f"соседство несимметрично: {r['id']} → {nb}, "
                                  f"но {nb} не называет {r['id']}")
    seen, queue = {regions[0]["id"]}, [regions[0]["id"]]   # связность (BFS)
    while queue:
        for nb in by_id[queue.pop()].get("neighbors") or []:
            if nb not in seen:
                seen.add(nb)
                queue.append(nb)
    if seen != set(region_ids):
        raise ConfigError(f"граф регионов несвязен: недостижимы "
                          f"{sorted(set(region_ids) - seen)}")
    lords = config.get("lords")
    if not isinstance(lords, list) or not lords:
        raise ConfigError("lords: непустой список")
    lord_ids = [l.get("id") for l in lords]
    if any(not lid for lid in lord_ids):
        raise ConfigError("lord.id: обязателен у всех лордов")
    if len(set(lord_ids)) != len(lord_ids):
        raise ConfigError(f"lords: дубликат id в {lord_ids}")
    if not any(l.get("is_human") for l in lords):
        raise ConfigError("lords: нужен лорд-человек (is_human)")
    for l in lords:
        if l.get("start_region") not in by_id:
            raise ConfigError(f"lord {l['id']}: start_region "
                              f"{l.get('start_region')!r} не существует")
        if l.get("is_human"):
            continue
        persona = l.get("persona") or {}
        for trait in PERSONA_TRAITS:
            v = persona.get(trait)
            if not isinstance(v, (int, float)) or not 0.0 <= float(v) <= 1.0:
                raise ConfigError(f"lord {l['id']}: persona.{trait} = {v!r} "
                                  f"вне 0..1")
        if not persona.get("doctrine_pool"):
            raise ConfigError(f"lord {l['id']}: persona.doctrine_pool пуст")
    short = (config.get("victory") or {}).get("short") or {}
    if short.get("type") not in VICTORY_TYPES:
        raise ConfigError(f"victory.short.type {short.get('type')!r} "
                          f"∉ {VICTORY_TYPES}")
    if short.get("type") == "eliminate_lords":
        for lid in short.get("lords") or []:
            if lid not in lord_ids:
                raise ConfigError(f"victory.short.lords: {lid!r} не существует")
    for block in ("economy", "pacing", "autoresolve", "events"):
        if config.get(block) is not None and not isinstance(config[block], dict):
            raise ConfigError(f"{block}: ожидался объект")


def normalize_config(config: dict) -> dict:
    """Копия конфига с дефолтами блоков economy/pacing/autoresolve/events."""
    out = json.loads(json.dumps(config, ensure_ascii=False))
    for block, defaults in (("economy", DEFAULT_ECONOMY),
                            ("pacing", DEFAULT_PACING),
                            ("autoresolve", DEFAULT_AUTORESOLVE)):
        merged = dict(defaults)
        merged.update(out.get(block) or {})
        out[block] = merged
    probs = dict(DEFAULT_EVENT_PROBS)
    probs.update((out.get("events") or {}).get("probabilities") or {})
    out["events"] = {"probabilities": probs}
    return out


def load_config(path: Path | str) -> dict:
    """Чтение + валидация + нормализация campaign_config.json;
    бросает ConfigError, если файла нет или JSON битый."""
    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        raise ConfigError(f"нет конфигурации кампании: {path}") from e
    except json.JSONDecodeError as e:
        raise ConfigError(f"{path}: битый JSON — {e}") from e
    validate_config(raw)
    return normalize_config(raw)


# ---------------------------------------------------------- новое состояние
def new_game(config: dict, rng_seed: int | None = None,
             campaign_dir: Path | str | None = None) -> dict:
    """Начальное состояние по контракту 03 §3.2: сезон 0, стартовые регионы
    (castle_level 1, dev 30, loyalty 60, гарнизон 10+6), армии 12+8 vet 0,
    казны 500/100 у всех, мир. campaign_dir задан — состояние сохранено."""
    if rng_seed is None:
        rng_seed = random.getrandbits(32)
    lords = config["lords"]
    state: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "campaign_id": config["campaign_id"],
        "season": 0,
        "season_name": SEASONS_RU[0],
        "rng_seed": int(rng_seed),
        "phase": "PLAYER_ACTIONS",
        "treasury": {"gold": START_GOLD, "honour": START_HONOUR,
                     "rank": START_RANK},
        "ai_treasury": {l["id"]: START_GOLD for l in lords
                        if not l.get("is_human")},
        "ai_honour": {l["id"]: START_HONOUR for l in lords
                      if not l.get("is_human")},
        "ai_start_regions": {l["id"]: [l["start_region"]] for l in lords
                             if not l.get("is_human")},
        "regions": {},
        "armies": {},
        "diplomacy": {"pairs": {}, "tributes": [], "pending_ally_joins": []},
        "counters": {"transitions_used": 0, "scenes_played": 0, "battles_auto": 0,
                     "battles_manual": 0, "empty_seasons_streak": 0,
                     "theater_last_season": None, "aborted_streak": 0,
                     "player_actions_season": 0, "scene_counter": 0},
        "pending_offers": [],
        "pending_scenes": [],
        "events_log": [],
        "attacked_regions": [],
        "flags": {"coalition_against_leader_active": False, "victory": None,
                  "sandbox": False, "harsh_winter": False},
    }
    owners = {l["start_region"]: l["id"] for l in lords}
    for rc in config["regions"]:
        owner = owners.get(rc["id"])
        entry: dict[str, Any] = {
            "owner": owner, "castle_level": 0, "loyalty": START_LOYALTY,
            "development_points": 0, "garrison": {},
            "last_theater_snapshot": None}
        if owner:
            entry["development_points"] = START_DEV_POINTS
            entry["garrison"] = {u: {"count": n, "vet": 0.0}
                                 for u, n in START_GARRISON.items()}
            if rc["type"] == "castle":
                entry["castle_level"] = 1
        state["regions"][rc["id"]] = entry
    for i, l in enumerate(lords, start=1):
        state["armies"][f"army_{i:02d}"] = {
            "owner": l["id"], "located_region": l["start_region"],
            "lord_present": True,
            "roster": {u: {"count": n, "vet": 0.0}
                       for u, n in START_ARMY.items()}}
    ids = [l["id"] for l in lords]
    for a in range(len(ids)):
        for b in range(a + 1, len(ids)):
            state["diplomacy"]["pairs"][pair_key(ids[a], ids[b])] = "peace"
    if campaign_dir is not None:
        save_state(Path(campaign_dir) / STATE_NAME, state)
    return state


# -------------------------------------------------------------- сохранение
def canonical_json(obj: Any) -> str:
    """Детерминированный JSON (сортировка ключей, компактно)."""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    """Запись tmp+rename — атомарность (R12)."""
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp_name, path)
    except BaseException:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise


def save_state(path: Path | str, state: dict) -> Path:
    """Атомарная запись состояния (tmp + rename); возвращает путь."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n").encode("utf-8")
    _atomic_write_bytes(path, data)
    return path


def load_state(path: Path | str) -> dict:
    """Чтение campaign_state.json; ConfigError, если нет/битый/не состояние."""
    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        raise ConfigError(f"нет состояния кампании: {path}") from e
    except json.JSONDecodeError as e:
        raise ConfigError(f"{path}: битый JSON — {e}") from e
    if not isinstance(raw, dict) or "regions" not in raw or "season" not in raw:
        raise ConfigError(f"{path}: не похоже на campaign_state (03 §3.2)")
    return raw


# ------------------------------------------------------------------ история
def _history_files(campaign_dir: Path | str) -> list[tuple[tuple[int, int], Path]]:
    """Слепки history/state_*.json с ключом (season, n); _end — после шагов."""
    d = Path(campaign_dir) / HISTORY_DIR
    out: list[tuple[tuple[int, int], Path]] = []
    if not d.exists():
        return out
    for p in sorted(d.glob("state_*.json")):
        m = _SNAP_RE.match(p.name)
        if m:
            out.append(((int(m.group(1)), int(m.group(2))), p))
            continue
        m = _END_RE.match(p.name)
        if m:
            out.append(((int(m.group(1)), 10 ** 9), p))
    return sorted(out)


def snapshot_history(state: dict, campaign_dir: Path | str) -> Path:
    """Слепок ДО изменения: history/state_<season>_<n>.json (03 §3.2)."""
    d = Path(campaign_dir) / HISTORY_DIR
    d.mkdir(parents=True, exist_ok=True)
    same = [k for k, _ in _history_files(campaign_dir)
            if k[0] == state["season"] and k[1] < 10 ** 9]
    n = 1 + max([k[1] for k in same], default=0)
    return save_state(d / f"state_{state['season']}_{n}.json", state)


def snapshot_season_end(state: dict, campaign_dir: Path | str) -> Path:
    """Автосейв конца сезона: history/state_<season>_end.json (07 §7.2 п.6)."""
    return save_state(Path(campaign_dir) / HISTORY_DIR
                      / f"state_{state['season']}_end.json", state)


def undo(state: dict, campaign_dir: Path | str, steps: int = 1) -> dict:
    """Откат к слепку истории (максимум 3 шага); слепок расходуется,
    «будущее» удаляется; TransitionError, если слепков не хватает."""
    if not 1 <= steps <= UNDO_MAX_STEPS:
        raise TransitionError(f"undo: шагов {steps} вне 1..{UNDO_MAX_STEPS}")
    snaps = [(k, p) for k, p in _history_files(campaign_dir) if k[1] < 10 ** 9]
    if len(snaps) < steps:
        raise TransitionError(f"undo: в истории {len(snaps)} слепков — "
                              f"откат на {steps} шагов невозможен")
    target_key, target_path = snaps[-steps]
    restored = load_state(target_path)
    for key, path in _history_files(campaign_dir):
        if key >= target_key:
            path.unlink(missing_ok=True)
    return restored


def append_event(campaign_dir: Path | str, season: int, kind: str,
                 summary: str) -> None:
    """Строка в events.jsonl (append-only, 03 §3.6)."""
    line = json.dumps(
        {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
         "season": season, "kind": kind, "summary": summary},
        ensure_ascii=False)
    path = Path(campaign_dir) / EVENTS_JL
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


# ---------------------------------------------------------------- помощники
def pair_key(a: str, b: str) -> str:
    """Ключ пары дипломатии: лорды по алфавиту через «|» (03 §3.2)."""
    return "|".join(sorted((a, b)))


def human_lord_id(config: dict) -> str:
    """id лорда-человека."""
    return next(l["id"] for l in config["lords"] if l.get("is_human"))


def ai_lord_ids(config: dict) -> list[str]:
    """id всех ИИ-лордов (порядок конфига)."""
    return [l["id"] for l in config["lords"] if not l.get("is_human")]


def lord_entry(config: dict, lord_id: str) -> dict | None:
    """Запись лорда из конфига (None, если нет)."""
    return next((l for l in config["lords"] if l["id"] == lord_id), None)


def region_config(config: dict, region_id: str) -> dict:
    """Конфиг региона; ConfigError, если региона нет."""
    rc = next((r for r in config["regions"] if r["id"] == region_id), None)
    if rc is None:
        raise ConfigError(f"регион {region_id!r} отсутствует в конфиге")
    return rc


def owned_region_ids(state: dict, lord_id: str) -> list[str]:
    """Отсортированные id регионов владельца."""
    return sorted(rid for rid, rs in state["regions"].items()
                  if rs.get("owner") == lord_id)


def army_of(state: dict, lord_id: str) -> dict | None:
    """Армия лорда (у лорда одна армия, 07 §7.5)."""
    return next((a for a in state["armies"].values()
                 if a.get("owner") == lord_id), None)


def known_lords(state: dict) -> list[str]:
    """Лорды, известные состоянию (казны/армии/владения), по алфавиту."""
    lords = {lid for lid, gold in (state.get("ai_treasury") or {}).items()
             if isinstance(gold, int)}
    lords |= {a.get("owner") for a in (state.get("armies") or {}).values()
              if a.get("owner")}
    lords |= {rs.get("owner") for rs in (state.get("regions") or {}).values()
              if rs.get("owner")}
    lords.discard(None)
    return sorted(lords)


def recalc_castle_level(state: dict, config: dict, region_id: str) -> int:
    """Уровень замка по development_points (пороги 25/60/120/200/300 → 1..5,
    потолок castle_levels региона); пишет в состояние и возвращает уровень."""
    rs = state["regions"][region_id]
    rc = region_config(config, region_id)
    if rc["type"] != "castle":
        rs["castle_level"] = 0
        return 0
    points = int(rs.get("development_points", 0))
    level = 0
    for lv, threshold in enumerate(DEV_THRESHOLDS, start=1):
        if points >= threshold:
            level = lv
    max_configured = max(int(k) for k in (rc.get("castle_levels") or {"1": "x"}))
    level = min(level, max_configured)
    rs["castle_level"] = level
    return level


def logf(state: dict, text: str) -> None:
    """Запись в журнал сезона: «S<n>: текст» (без времени — детерминизм)."""
    state.setdefault("events_log", []).append(f"S{state['season']}: {text}")


# --------------------------------------------- хелперы сезонов/росписей/казны
SEASON_NAMES = ("Весна", "Лето", "Осень", "Зима")


def season_name(season: int) -> str:
    """Время года по номеру сезона (1-й = Весна; 0 = до начала)."""
    if season <= 0:
        return "—"
    return SEASON_NAMES[(season - 1) % 4]


def months_per_season(config: dict) -> int:
    """Месяцев в сезоне: 12 / seasons_per_year (минимум 1)."""
    try:
        sps = int((config.get("pacing") or {}).get("seasons_per_year", 4))
    except (TypeError, ValueError):
        sps = 4
    return max(1, 12 // max(1, sps))


def _derive_rng(state: dict, *salts: int) -> random.Random:
    """Детерминированный RNG от сида кампании, сезона и солей назначения."""
    h = (int(state.get("rng_seed", 0)) * 1_000_003
         + int(state.get("season", 0)) * 1009) % (2 ** 32)
    for s in salts:
        h = (h * 65599 + int(s)) % (2 ** 32)
    return random.Random(h)


def season_rng(state: dict, phase_salt: int = 0) -> int | random.Random:
    """RNG фазы сезона (соли: 0=события, 1=ИИ, 3=RESOLUTION). Одинаковые
    входы → одинаковая последовательность (детерминизм 07 §7.12)."""
    return _derive_rng(state, 7, phase_salt)


def battle_rng(state: dict) -> random.Random:
    """RNG боёв сезона (отдельная соль: бои не сдвигают события/ИИ)."""
    return _derive_rng(state, 13)


def roster_total(roster: dict | None) -> int:
    """Суммарная численность росписи ({unit: {count, vet}} или {unit: count})."""
    if not roster:
        return 0
    total = 0
    for rec in roster.values():
        if isinstance(rec, dict):
            total += int(rec.get("count", 0))
        else:
            total += int(rec)
    return total


def _ai_map(state: dict, key: str, lord_id: str) -> dict:
    """Контейнер казны ИИ (создаётся при первом обращении)."""
    m = state.setdefault(key, {})
    return m


def lord_gold(state: dict, lord_id: str) -> int:
    """Золото лорда: ИИ — ai_treasury, игрок — treasury.gold."""
    if lord_id in (state.get("ai_treasury") or {}):
        return int(state["ai_treasury"][lord_id])
    return int((state.get("treasury") or {}).get("gold", 0))


def lord_honour(state: dict, lord_id: str) -> int:
    """Честь лорда: ИИ — ai_honour, игрок — treasury.honour."""
    if lord_id in (state.get("ai_honour") or {}):
        return int(state["ai_honour"][lord_id])
    return int((state.get("treasury") or {}).get("honour", 0))


def add_gold(state: dict, lord_id: str, delta: int) -> None:
    """Изменить золото лорда (ИИ — ai_treasury, игрок — treasury)."""
    delta = int(delta)
    if lord_id in (state.get("ai_treasury") or {}):
        state["ai_treasury"][lord_id] = int(state["ai_treasury"][lord_id]) + delta
    else:
        treasury = state.setdefault("treasury", {})
        treasury["gold"] = int(treasury.get("gold", 0)) + delta


def add_honour(state: dict, lord_id: str, delta: int) -> None:
    """Изменить честь лорда (ИИ — ai_honour, игрок — treasury)."""
    delta = int(delta)
    if lord_id in (state.get("ai_honour") or {}):
        state["ai_honour"][lord_id] = int(state["ai_honour"][lord_id]) + delta
    else:
        treasury = state.setdefault("treasury", {})
        treasury["honour"] = int(treasury.get("honour", 0)) + delta


def merge_rosters(a: dict | None, b: dict | None) -> dict:
    """Сложение росписей {unit: {count, vet}}; vet — взвешенно по численности."""
    out: dict[str, dict] = {}
    for roster in (a or {}, b or {}):
        for unit, rec in (roster or {}).items():
            if isinstance(rec, dict):
                count, vet = int(rec.get("count", 0)), float(rec.get("vet", 0.0))
            else:
                count, vet = int(rec), 0.0
            if count <= 0:
                continue
            if unit in out:
                old = out[unit]
                new_count = old["count"] + count
                out[unit] = {"count": new_count,
                             "vet": round((old["vet"] * old["count"]
                                           + vet * count) / new_count, 4)}
            else:
                out[unit] = {"count": count, "vet": round(vet, 4)}
    return out


def attack_force_roster(state: dict, lord_id: str) -> dict:
    """Роспись походной армии лорда (полевая сила атаки, 07 §7.3)."""
    army = army_of(state, lord_id)
    return dict(army.get("roster") or {}) if army else {}


def defense_force_roster(state: dict, region_id: str) -> dict:
    """Гарнизон региона (сила обороны цели)."""
    rs = (state.get("regions") or {}).get(region_id) or {}
    return dict(rs.get("garrison") or {})
