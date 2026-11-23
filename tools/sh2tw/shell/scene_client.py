"""scene_client.py — клиент генератора сцен (05 §5) с честной деградацией.

Собирает scene_spec (03 §3.3) из состояния кампании и вызывает генератор
(build_scene + template_for_role); провижининг сторон выравнивается
budget_gold слабейшей стороны до ±10 % (03 §3.9). Ошибка шаблона/генератора
(нет карт игры) НЕ роняет оболочку: {"ok": False, "reason", "fallback"} —
бои уходят в авто-резолв, развитие применяется мгновенно (бриф К1).
"""
from __future__ import annotations

import math
from pathlib import Path

from ..honesty.accounting import (HonestyError, load_unit_values,
                                  provision_balance_detail,
                                  side_provision_value)
from ..scenes.event_dsl import scene_events
from ..scenes.generator import GeneratorError, build_scene
from ..scenes.templates import TemplateError, template_for_role
from . import agenda_ai as agenda
from . import autoresolve as ar
from . import season
from . import state as st

SCENE_DURATION_MONTHS = 40      # боевая сцена (03 §3.3)
DEVELOPMENT_DURATION_MONTHS = 30  # сцена развития (бриф К1)
BALANCE_TOLERANCE = 0.10        # ±10 % провижининга (03 §3.9)
MAX_DEVELOP_NEIGHBORS = 4       # ControlLordsAI: соседи-ИИ до 4 (бриф К1)
DEV_REWARD_POINTS = 20          # эффект сцены развития = действию ИИ (07 §7.3)

_SCENE_ERRORS = (TemplateError, GeneratorError, HonestyError,
                 FileNotFoundError, OSError)


def _estimated_minutes(config: dict) -> int:
    """Оценка длительности сцены: середина field_scene_minutes, к 5 мин."""
    lo, hi = config["pacing"]["field_scene_minutes"]
    return int(round((float(lo) + float(hi)) / 2.0 / 5.0) * 5)


def _battle_context(state: dict, config: dict, target_region: str) -> dict:
    """Общий контекст боя: атакующий (игрок), оборона цели, прогноз."""
    player = st.human_lord_id(config)
    rs = state["regions"].get(target_region)
    if rs is None:
        raise st.ConfigError(f"регион {target_region!r} не существует")
    att_roster = st.attack_force_roster(state, player)
    def_roster = st.defense_force_roster(state, target_region)
    castle_level = int(rs.get("castle_level", 0))
    forecast = ar.battle_forecast(config, att_roster, def_roster, castle_level)
    return {"player": player, "region_state": rs, "att_roster": att_roster,
            "def_roster": def_roster, "castle_level": castle_level,
            "forecast": forecast}


def prepare_battle(state: dict, config: dict, target_region: str) -> dict:
    """Прогноз похода без обязательств («цена боя до входа», 07 §7.5)."""
    ctx = _battle_context(state, config, target_region)
    forecast = ctx["forecast"]
    used = int(state["counters"].get("transitions_used", 0))
    limit = int(config["pacing"]["max_transitions_total"])
    return {"target": target_region,
            "attacker_strength": int(round(forecast["s_att"])),
            "defender_strength": int(round(forecast["s_def"])),
            "p_win_autoresolve": round(forecast["p_win_att"], 3),
            "estimated_minutes": _estimated_minutes(config),
            "transitions": f"{used}/{limit}",
            "battle_type": forecast["battle_type"]}


def _balance_sides(spec: dict, unit_values: dict) -> None:
    """Провижининг сторон ±10 %: budget_gold слабейшей стороне (03 §3.9)."""
    detail = provision_balance_detail(spec, unit_values)
    if detail.ok:
        return
    values = {i: side_provision_value(s, unit_values)
              for i, s in enumerate(spec["sides"])}
    hi = max(values.values())
    lo_i = min(values, key=lambda i: values[i])
    need = math.ceil(hi / (1.0 + BALANCE_TOLERANCE) - values[lo_i])
    if need > 0:                       # слабейшей стороне — военная казна
        side = spec["sides"][lo_i]
        side["budget_gold"] = int(side.get("budget_gold", 0) or 0) + need


def _next_scene_id(state: dict) -> tuple[str, int]:
    """Следующий идентификатор сцены: sc_<сезон:02><счётчик:03> (бриф К1);
    счётчик расходуется только при успешной генерации."""
    count = int((state.get("counters") or {}).get("scene_counter", 0)) + 1
    return f"sc_{int(state['season']):02d}{count:03d}", count


def _check_transition_budget(state: dict, config: dict) -> None:
    """Лимит переходов в игру (pacing.max_transitions_total, 07 §7.2)."""
    used = int(state["counters"].get("transitions_used", 0))
    limit = int(config["pacing"]["max_transitions_total"])
    if used >= limit:
        raise st.TransitionError(f"лимит переходов в игру исчерпан: "
                                 f"{used}/{limit}")


def _build_scene_spec(state: dict, config: dict, scene_id: str, scene_type: str,
                      sides: list[dict], region_id: str,
                      duration_months: int) -> dict:
    """scene_spec по контракту 03 §3.3 (+ балансировка провижининга)."""
    spec = {
        "schema_version": "1.0", "scene_id": scene_id, "type": scene_type,
        "created_by": "shell", "region": region_id,
        "duration_months": duration_months, "sides": sides,
        "map_source": {"kind": "template"},
        "map_header_overrides": {
            "estate_markers": "inherit",
            "mission_events": scene_events(scene_type, sides,
                                           duration_months)},
        "honesty": {"snapshot_points": ["start", "end"], "enabled": True},
    }
    _balance_sides(spec, load_unit_values())
    return spec


def _emit_scene(state: dict, config: dict, spec: dict, scene_type: str,
                target_region: str, attacker_lord: str, defender_lord: str | None,
                out_dir: Path, template_role: str) -> dict:
    """Генерация карты; успех — запись в pending_scenes, ошибка — fallback."""
    try:
        template = template_for_role(template_role)
        report = build_scene(spec, template, Path(out_dir))
    except _SCENE_ERRORS as e:
        return {"ok": False, "reason": str(e), "fallback": "autoresolve"}
    counters = state["counters"]
    counters["scene_counter"] = int(counters.get("scene_counter", 0)) + 1
    counters["transitions_used"] = int(counters.get("transitions_used", 0)) + 1
    record = {"scene_id": spec["scene_id"], "target_region": target_region,
              "type": scene_type, "attacker_lord": attacker_lord,
              "defender_lord": defender_lord,
              "map": report.map_path.name}
    state.setdefault("pending_scenes", []).append(record)
    st.logf(state, f"сцена {spec['scene_id']} ({scene_type}) собрана: "
                   f"{report.map_path.name}")
    return {"ok": True, "map": str(report.map_path),
            "scene_id": spec["scene_id"],
            "instruction": f"Запустите Stronghold 2 → выберите карту "
                           f"{report.map_path.stem}",
            "scene": record}


def fight_scene(state: dict, config: dict, target_region: str,
                out_dir: Path | str) -> dict:
    """Сцена похода игрока: field (castle_level 0) или siege (≥1)."""
    ctx = _battle_context(state, config, target_region)
    rs = ctx["region_state"]
    if not rs.get("owner") or rs["owner"] == ctx["player"]:
        raise st.TransitionError(f"бой возможен только с чужим регионом "
                                 f"{target_region}")
    _check_transition_budget(state, config)
    scene_type = "siege" if ctx["castle_level"] >= 1 else "field"
    defender = rs["owner"]
    if ctx["castle_level"] >= 1:
        aic_key = (st.region_config(config, target_region)
                   .get("castle_levels") or {}).get(str(ctx["castle_level"]))
        provision = {"channel": "aic_template", "aic_key": aic_key,
                     "garrison_roster": ctx["def_roster"]}
    else:
        provision = {"channel": "estate_troops",
                     "roster": ctx["def_roster"]}
    sides = [
        {"role": "attacker", "lord": ctx["player"], "is_human": True,
         "provision": {"channel": "estate_troops",
                       "roster": ctx["att_roster"]}},
        {"role": "defender", "lord": defender, "is_human": False,
         "provision": provision}]
    scene_id, _count = _next_scene_id(state)
    spec = _build_scene_spec(state, config, scene_id, scene_type, sides,
                             target_region, SCENE_DURATION_MONTHS)
    result = _emit_scene(state, config, spec, scene_type, target_region,
                         ctx["player"], defender, out_dir,
                         "siege" if scene_type == "siege" else "field")
    result["p_win_autoresolve"] = round(ctx["forecast"]["p_win_att"], 3)
    return result


def defend_scene(state: dict, config: dict, target_region: str,
                 out_dir: Path | str) -> dict:
    """Сцена обороны: игрок защищает свой регион от нападения (07 §7.2 п.3)."""
    rs = state["regions"].get(target_region)
    if rs is None:
        raise st.ConfigError(f"регион {target_region!r} не существует")
    player = st.human_lord_id(config)
    if rs.get("owner") != player:
        raise st.TransitionError(f"оборона возможна только своего региона "
                                 f"{target_region}")
    attacker = _strongest_enemy(state, config, target_region)
    if not attacker:
        raise st.TransitionError(f"у региона {target_region} нет "
                                 f"нападающего соседа")
    _check_transition_budget(state, config)
    att_roster = st.attack_force_roster(state, attacker)
    sides = [
        {"role": "attacker", "lord": attacker, "is_human": False,
         "provision": {"channel": "estate_troops", "roster": att_roster}},
        {"role": "defender", "lord": player, "is_human": True,
         "provision": {"channel": "estate_troops",
                       "roster": st.defense_force_roster(state,
                                                         target_region)}}]
    scene_id, _count = _next_scene_id(state)
    spec = _build_scene_spec(state, config, scene_id, "defense", sides,
                             target_region, SCENE_DURATION_MONTHS)
    return _emit_scene(state, config, spec, "defense", target_region,
                       attacker, player, out_dir, "defense")


def _strongest_enemy(state: dict, config: dict,
                     region_id: str) -> str | None:
    """Сильнейший сосед-враг региона (для сцены обороны)."""
    best, best_strength = None, -1.0
    for nb in st.region_config(config, region_id).get("neighbors") or []:
        owner = (state["regions"].get(nb) or {}).get("owner")
        if not owner or owner == st.human_lord_id(config):
            continue
        strength = ar.roster_strength(st.attack_force_roster(state, owner))
        if strength > best_strength:
            best, best_strength = owner, strength
    return best


def develop_region(state: dict, config: dict, region_id: str,
                   out_dir: Path | str) -> dict:
    """Сцена развития (театр, 30 мес): соседи-ИИ до 4 (ControlLordsAI);
    кулдаун театра pacing.theater_cooldown_seasons (07 §7.2 п.4)."""
    rc = st.region_config(config, region_id)
    rs = state["regions"].get(region_id) or {}
    player = st.human_lord_id(config)
    if rs.get("owner") != player or rc["type"] != "castle":
        raise st.TransitionError(f"развивать можно только свой замковый "
                                 f"регион {region_id}")
    cooldown = int(config["pacing"]["theater_cooldown_seasons"])
    last = state["counters"].get("theater_last_season")
    if last is not None and int(state["season"]) - int(last) < cooldown:
        raise st.TransitionError(f"кулуар театра: следующий доступен через "
                                 f"{cooldown - (int(state['season']) - int(last))} "
                                 f"сезон(ов)")
    _check_transition_budget(state, config)
    neighbors: list[str] = []
    for nb in rc.get("neighbors") or []:
        owner = (state["regions"].get(nb) or {}).get("owner")
        if owner and owner != player and owner not in neighbors:
            neighbors.append(owner)
    ai_lords = sorted(neighbors)[:MAX_DEVELOP_NEIGHBORS]
    sides = [{"role": "developer", "lord": player, "is_human": True,
              "provision": {"channel": "estate_troops",
                            "roster": rs.get("garrison") or {}}}]
    for lord_id in ai_lords:
        sides.append({"role": "neighbor", "lord": lord_id, "is_human": False,
                      "provision": {"channel": "aic_template",
                                    "garrison_roster": {}}})
    scene_id, _count = _next_scene_id(state)
    spec = _build_scene_spec(state, config, scene_id, "development", sides,
                             region_id, DEVELOPMENT_DURATION_MONTHS)
    result = _emit_scene(state, config, spec, "development", region_id,
                         player, None, out_dir, "theater")
    if result["ok"]:
        state["counters"]["theater_last_season"] = int(state["season"])
    else:
        # деградация без карт игры: тот же эффект, что у действия ИИ (07 §7.3)
        # — −100 золота, +20 очков развития, без перехода в игру
        result["fallback"] = "instant"
        result["applied"] = _instant_develop(state, config, region_id)
    return result


def _instant_develop(state: dict, config: dict, region_id: str) -> dict:
    """Мгновенное развитие (fallback без карт): −100 золота, +20 очков."""
    cost = agenda.DEV_ACTION_COST
    if st.lord_gold(state, st.human_lord_id(config)) < cost:
        raise st.TransitionError(f"для развития нужно {cost} золота")
    st.add_gold(state, st.human_lord_id(config), -cost)
    rs = state["regions"][region_id]
    rs["development_points"] = int(rs.get("development_points", 0)) \
        + agenda.DEV_POINTS_PER_ACTION
    st.recalc_castle_level(state, config, region_id)
    st.logf(state, f"развитие {st.region_config(config, region_id)['name']} "
                   f"применено мгновенно (−{cost} з, без сцены — нет карт)")
    return {"gold_spent": cost,
            "development_points": agenda.DEV_POINTS_PER_ACTION}


def accept_scene_result(state: dict, config: dict,
                        scene_result: dict) -> dict:
    """Принять итог сцены (раннер или ручной ввод «Исход?», 07 §7.6):
    apply_battle_result для боёв; development → +очки развития; aborted →
    милосердие (07 §7.7). Сцена удаляется из pending_scenes."""
    scene_id = scene_result.get("scene_id")
    scene = next((s for s in state.get("pending_scenes") or []
                  if s.get("scene_id") == scene_id), None)
    if scene is None:
        raise st.TransitionError(f"сцена {scene_id!r} не найдена в "
                                 f"pending_scenes")
    outcome = str(scene_result.get("outcome", "draw"))
    if outcome not in ("win", "loss", "draw", "aborted"):
        raise st.TransitionError(f"исход {outcome!r} ∉ win|loss|draw|aborted")
    counters = state["counters"]
    counters["scenes_played"] = int(counters.get("scenes_played", 0)) + 1
    state["pending_scenes"].remove(scene)
    if scene.get("type") == "development":
        return _apply_development_result(state, config, scene, outcome)
    counters["battles_manual"] = int(counters.get("battles_manual", 0)) + 1
    human = st.human_lord_id(config)
    attacker, defender = scene["attacker_lord"], scene["defender_lord"]
    human_is_attacker = attacker == human
    outcome_map = {"win": "win_attacker" if human_is_attacker
                   else "win_defender",
                   "loss": "win_defender" if human_is_attacker
                   else "win_attacker",
                   "draw": "draw", "aborted": "aborted"}
    survivors = scene_result.get("survivors") or {}
    mapped = {attacker: survivors.get("attacker"),
              defender: survivors.get("defender")}
    mapped = {lord: roster for lord, roster in mapped.items() if roster}
    losses = scene_result.get("losses") or {}
    mapped_losses = {attacker: losses.get("attacker"),
                     defender: losses.get("defender")}
    mapped_losses = {lord: l for lord, l in mapped_losses.items() if l}
    summary = season.apply_battle_result(
        state, config, {"attacker_lord": attacker, "defender_lord": defender,
                        "target_region": scene["target_region"],
                        "outcome": outcome_map[outcome],
                        "survivors": mapped, "losses": mapped_losses,
                        "honour_delta": scene_result.get("honour_delta", 0)})
    st.logf(state, f"итог сцены {scene_id} принят: {outcome}")
    return summary


def _apply_development_result(state: dict, config: dict, scene: dict,
                              outcome: str) -> dict:
    """Итог сцены развития: win → +20 development_points (как действие ИИ,
    07 §7.3); иначе эффекта нет (переход уже списан)."""
    if outcome == "win":
        region_id = scene["target_region"]
        rs = state["regions"][region_id]
        rs["development_points"] = int(rs.get("development_points", 0)) \
            + DEV_REWARD_POINTS
        st.recalc_castle_level(state, config, region_id)
        st.logf(state, f"сцена развития {scene['scene_id']}: "
                       f"+{DEV_REWARD_POINTS} очков развития "
                       f"({st.region_config(config, region_id)['name']})")
        return {"outcome": outcome, "development_points": DEV_REWARD_POINTS,
                "region": region_id}
    st.logf(state, f"сцена развития {scene['scene_id']} не удалась — "
                   f"эффекта нет")
    return {"outcome": outcome, "development_points": 0,
            "region": scene["target_region"]}
