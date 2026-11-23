"""season.py — машина состояний сезона (07 §7.2) и применение итогов (07 §7.7).

Цикл: SEASON_START → EVENTS → AI_TURNS → PLAYER_ACTIONS → RESOLUTION →
SEASON_END. next_season() доводит текущий сезон до конца (RESOLUTION +
SEASON_END: слепок history/state_<season>_end.json + events.jsonl) и
прогоняет следующий до остановки в PLAYER_ACTIONS — это и делает
POST /api/season/next. Штрафы дохода/зимы, выпавшие в EVENTS, сбрасываются
на SEASON_START следующего сезона (доход текущего сезона уже уплачен —
порядок фаз 07 §7.2). RNG: сид = (rng_seed + season + stream) & 0xFFFFFFFF.
"""
from __future__ import annotations

import random
from pathlib import Path

from . import agenda_ai as agenda
from . import autoresolve as ar
from . import diplomacy as dip
from . import economy
from . import events_catalog
from . import state as st

PHASES = ("SEASON_START", "EVENTS", "AI_TURNS", "PLAYER_ACTIONS",
          "RESOLUTION", "SEASON_END")
LOYALTY_AFTER_CAPTURE = 30    # лояльность захваченного региона (07 §7.7)
VET_STEP = 0.5                # ветеран победного боя: vet += 0.5 (07 §7.7)
VET_MAX = 1.0
DESERTION_SHARE = 0.2         # 3 aborted подряд → «дезертирство» −20 % армии
DESERTION_STREAK = 3
AI_DEV_BASE = 10              # развитие ИИ: += round(10 × persona.builder)


# -------------------------------------------------------------- фазы сезона
def _season_start(state: dict, config: dict) -> None:
    """SEASON_START: доход в казны, дань, сброс штрафов прошлого сезона,
    время года (07 §7.2 п.1). Штрафы ещё действуют на это начисление."""
    state["season"] = int(state["season"]) + 1
    state["season_name"] = st.season_name(state["season"])
    state["phase"] = "SEASON_START"
    for lord in config["lords"]:
        income = economy.season_income(state, config, lord["id"])
        st.add_gold(state, lord["id"], income)
        st.logf(state, f"доход {lord['id']}: +{income} золота")
    dip.process_tributes(state, config)
    for rs in state["regions"].values():     # сброс штрафов прошлого сезона
        rs.pop("income_penalty", None)
    state["flags"]["harsh_winter"] = False


def _ai_growth(state: dict, config: dict) -> None:
    """AI_TURNS: развитие ИИ «план .aic + время»: development_points
    += round(10 × persona.builder), пересчёт уровня замка (бриф К1)."""
    for lord_id in st.ai_lord_ids(config):
        if not st.owned_region_ids(state, lord_id):
            continue
        persona = (st.lord_entry(config, lord_id) or {}).get("persona") or {}
        gain = round(AI_DEV_BASE * float(persona.get("builder", 0.0)))
        if gain <= 0:
            continue
        for rid in st.owned_region_ids(state, lord_id):
            if st.region_config(config, rid)["type"] != "castle":
                continue
            rs = state["regions"][rid]
            rs["development_points"] = int(rs.get("development_points", 0)) + gain
            st.recalc_castle_level(state, config, rid)


def apply_resolution(state: dict, config: dict, rng: random.Random,
                     campaign_dir: Path | str | None = None) -> dict:
    """RESOLUTION + SEASON_END: нерешённые бои, союзники, лояльность,
    победа, пустые сезоны, автосейв и журнал (07 §7.2 п.5–6)."""
    if state["phase"] != "PLAYER_ACTIONS":
        raise st.TransitionError(f"RESOLUTION доступен только из "
                                 f"PLAYER_ACTIONS (сейчас {state['phase']})")
    state["phase"] = "RESOLUTION"
    dip.process_pending_ally_joins(state, config)
    resolved = []
    for offer in list(state.get("pending_offers") or []):
        if offer.get("offer") == "battle":
            st.logf(state, f"бой за {offer['target_region']} не принят "
                           f"игроком — авто-резолв (07 §7.2)")
            resolved.append(execute_attack(state, config, offer["attacker"],
                                           offer["target_region"], rng))
        else:
            st.logf(state, f"предложение {offer.get('offer')} от "
                           f"{offer.get('from', offer.get('attacker', '?'))} "
                           f"истекло (сезон кончился)")
    state["pending_offers"] = []
    for scene in list(state.get("pending_scenes") or []):
        if scene.get("type") in ("field", "siege", "defense"):
            st.logf(state, f"сцена {scene['scene_id']} без итога — "
                           f"авто-резолв боя")
            resolved.append(execute_attack(state, config, scene["attacker_lord"],
                                           scene["target_region"], rng))
        else:
            st.logf(state, f"сцена развития {scene['scene_id']} не завершена — "
                           f"эффекта нет (переход списан)")
        state["pending_scenes"].remove(scene)
    warnings = []
    counters = state["counters"]
    if int(counters.get("player_actions_season", 0)) == 0:
        counters["empty_seasons_streak"] = int(
            counters.get("empty_seasons_streak", 0)) + 1
    else:
        counters["empty_seasons_streak"] = 0
    streak = int(counters["empty_seasons_streak"])
    if streak > int(config["pacing"]["max_empty_seasons_streak"]):
        warnings.append(f"пустых сезонов подряд: {streak} "
                        f"(анти-афк, 07 §7.2)")
        st.logf(state, f"предупреждение: {streak} пустых сезонов подряд")
    check_victory(state, config)
    state["phase"] = "SEASON_END"
    if campaign_dir is not None:
        st.snapshot_season_end(state, campaign_dir)
        st.append_event(campaign_dir, state["season"], "season_end",
                        f"Сезон {state['season']} ({state['season_name']}) "
                        f"завершён")
    return {"warnings": warnings, "resolved_battles": resolved}


def finish_player_actions(state: dict, config: dict, rng: random.Random,
                          campaign_dir: Path | str | None = None) -> dict:
    """Синоним apply_resolution (экран «Завершить сезон», 07 §7.5)."""
    return apply_resolution(state, config, rng, campaign_dir)


def next_season(state: dict, config: dict,
                campaign_dir: Path | str | None = None) -> dict:
    """Полный прогон: RESOLUTION+SEASON_END текущего сезона, затем следующий
    сезон до PLAYER_ACTIONS; возвращает {state, season, season_name, offers,
    events, warnings} (бриф К1)."""
    if state["phase"] != "PLAYER_ACTIONS":
        raise st.TransitionError(f"завершение сезона доступно только из "
                                 f"PLAYER_ACTIONS (сейчас {state['phase']})")
    resolution = apply_resolution(state, config, st.season_rng(state, 3),
                                  campaign_dir)
    _season_start(state, config)
    state["phase"] = "EVENTS"
    events = events_catalog.apply_events(state, config, st.season_rng(state, 0))
    state["phase"] = "AI_TURNS"
    agenda.ai_turn(state, config, st.season_rng(state, 1),
                   set(state.get("attacked_regions") or []))
    _ai_growth(state, config)
    state["phase"] = "PLAYER_ACTIONS"
    state["counters"]["player_actions_season"] = 0
    state["attacked_regions"] = []
    if campaign_dir is not None:
        st.save_state(Path(campaign_dir) / st.STATE_NAME, state)
    return {"state": state, "season": state["season"],
            "season_name": state["season_name"],
            "offers": state["pending_offers"], "events": events,
            "warnings": resolution["warnings"]}


# ------------------------------------------------------------- итоги боёв
def _roster_minus(roster: dict | None, losses: dict | None) -> dict:
    """Роспись минус потери {unit: n} (итог без survivors)."""
    out: dict[str, dict] = {}
    for unit, rec in (roster or {}).items():
        count = int(rec.get("count", 0)) - int((losses or {}).get(unit, 0))
        if count > 0:
            out[unit] = {"count": count,
                         "vet": round(float(rec.get("vet", 0.0) or 0.0), 4)}
    return out


def _promote_veterans(roster: dict) -> None:
    """Ветераны победителя: vet += 0.5, потолок 1.0 (07 §7.7)."""
    for rec in roster.values():
        if int(rec.get("count", 0)) > 0:
            rec["vet"] = min(VET_MAX,
                             round(float(rec.get("vet", 0.0)) + VET_STEP, 4))


def execute_attack(state: dict, config: dict, attacker_lord: str,
                   target_region: str, rng: random.Random) -> dict:
    """Поход на регион: сбор ударной силы, авто-резолв, применение итогов.
    Атака = акт войны (07 §7.3: мир не обязателен, но война следует)."""
    rs = state["regions"].get(target_region)
    if rs is None:
        raise st.ConfigError(f"регион {target_region!r} не существует")
    defender = rs.get("owner")
    if not defender:
        raise st.TransitionError(f"атака на нейтральный регион {target_region}: "
                                 f"деревни покупают за честь (07 §7.3)")
    if defender == attacker_lord:
        raise st.TransitionError("атака на собственный регион")
    army = st.army_of(state, attacker_lord)
    if army is None or st.roster_total(army.get("roster")) <= 0:
        raise st.TransitionError(f"у {attacker_lord} нет армии для похода")
    if dip.get_pair(state, attacker_lord, defender) != "war":
        dip.declare_war(state, config, attacker_lord, defender)
    located = state["regions"].get(army["located_region"]) or {}
    if located.get("owner") == attacker_lord:      # армия подбирает гарнизон
        army["roster"] = st.merge_rosters(army.get("roster"),
                                          located.get("garrison"))
        located["garrison"] = {}
    def_army = st.army_of(state, defender)         # армия обороны — в замок
    if def_army is not None and def_army.get("located_region") == target_region:
        rs["garrison"] = st.merge_rosters(rs.get("garrison"),
                                          def_army.get("roster"))
        def_army["roster"] = {}
    result = ar.autoresolve(
        {"lord": attacker_lord, "roster": army["roster"]},
        {"lord": defender, "roster": rs["garrison"],
         "castle_level": int(rs.get("castle_level", 0))},
        config, rng)
    outcome = ("win_attacker" if result["winner"] == attacker_lord
               else "win_defender" if result["winner"] == defender else "draw")
    summary = apply_battle_result(state, config, {
        "attacker_lord": attacker_lord, "defender_lord": defender,
        "target_region": target_region, "outcome": outcome,
        "survivors": result["survivors"], "losses": result["losses"]})
    state["counters"]["battles_auto"] = int(
        state["counters"].get("battles_auto", 0)) + 1
    result["applied"] = summary
    return result


def _desertion(state: dict, config: dict, lord_id: str) -> None:
    """«Дезертирство» после 3 aborted подряд: −20 % армии (07 §7.7)."""
    army = st.army_of(state, lord_id)
    if army is None:
        return
    strength = ar.roster_strength(army.get("roster"))
    if strength <= 0:
        return
    survivors, losses = ar.apply_loss_value(
        army["roster"], ar.unit_values_cached(),
        DESERTION_SHARE * strength)
    army["roster"] = survivors
    st.logf(state, f"дезертирство: армия {lord_id} теряет "
                   f"{sum(losses.values())} юнитов (3 aborted подряд)")


def apply_battle_result(state: dict, config: dict, result: dict) -> dict:
    """Правила применения итогов (07 §7.7): росписи, захват, ветераны,
    смерти лордов. result = {attacker_lord, defender_lord, target_region,
    outcome, survivors?, losses?, honour_delta?}."""
    attacker = result["attacker_lord"]
    defender = result["defender_lord"]
    region_id = result["target_region"]
    outcome = result["outcome"]
    rs = state["regions"].get(region_id)
    if rs is None:
        raise st.ConfigError(f"регион {region_id!r} не существует")
    army_att = st.army_of(state, attacker)
    army_def = st.army_of(state, defender)
    survivors = result.get("survivors") or {}
    att_surv = survivors.get(attacker) or _roster_minus(
        (army_att or {}).get("roster"), (result.get("losses") or {}).get(attacker))
    def_surv = survivors.get(defender) or _roster_minus(
        rs.get("garrison"), (result.get("losses") or {}).get(defender))
    if outcome == "aborted":                       # милосердие (07 §7.7)
        counters = state["counters"]
        counters["aborted_streak"] = int(counters.get("aborted_streak", 0)) + 1
        st.logf(state, f"бой за {st.region_config(config, region_id)['name']} "
                       f"прерван — армия без потерь (милосердие)")
        if int(counters["aborted_streak"]) >= DESERTION_STREAK:
            _desertion(state, config, st.human_lord_id(config))
            counters["aborted_streak"] = 0
        return {"outcome": outcome, "captured": False, "region": region_id}
    state["counters"]["aborted_streak"] = 0
    captured = outcome == "win_attacker" and rs.get("owner") == defender
    if army_att is not None:
        army_att["roster"] = att_surv
    def_army_in_region = army_def is not None \
        and army_def.get("located_region") == region_id
    if captured:                                   # разграбление (07 §7.7)
        rs["owner"] = attacker
        rs["castle_level"] = max(0, int(rs.get("castle_level", 0)) - 1)
        rs["loyalty"] = LOYALTY_AFTER_CAPTURE
        rs["garrison"] = {}
        if army_att is not None:
            army_att["located_region"] = region_id
        if def_army_in_region:
            army_def["roster"] = def_surv          # остатки обороны отступают
    elif outcome == "win_defender":
        rs["garrison"] = def_surv
        if def_army_in_region:
            army_def["roster"] = {}                # армия встала в гарнизон
    else:                                          # draw / ничья
        rs["garrison"] = def_surv
    if outcome == "win_attacker" and army_att is not None:
        _promote_veterans(army_att["roster"])
    if outcome == "win_defender":
        _promote_veterans(rs["garrison"])
    honour = int(result.get("honour_delta") or 0)
    if honour:
        st.add_honour(state, st.human_lord_id(config), honour)
    state.setdefault("attacked_regions", []).append(region_id)
    st.logf(state, f"бой за {st.region_config(config, region_id)['name']}: "
                   f"{attacker} против {defender} — {outcome}"
                   + ("; регион захвачен" if captured else ""))
    _handle_lord_deaths(state, config)
    return {"outcome": outcome, "captured": captured, "region": region_id}


def _handle_lord_deaths(state: dict, config: dict) -> None:
    """Смерть ИИ (0 регионов → армии распускаются); игрок без земель —
    поражение кампании (07 §7.7)."""
    player = st.human_lord_id(config)
    if not st.owned_region_ids(state, player) \
            and not state["flags"].get("victory"):
        state["flags"]["victory"] = {"level": "defeat",
                                     "season": int(state["season"])}
        state["flags"]["sandbox"] = True
        st.logf(state, "игрок потерял все регионы — поражение кампании "
                       "(07 §7.7)")
    for lord_id in st.ai_lord_ids(config):
        if st.owned_region_ids(state, lord_id):
            continue
        army_ids = [aid for aid, a in state["armies"].items()
                    if a.get("owner") == lord_id
                    and st.roster_total(a.get("roster")) > 0]
        if not army_ids:
            continue
        for aid in army_ids:
            del state["armies"][aid]
        name = (st.lord_entry(config, lord_id) or {}).get("name", lord_id)
        st.logf(state, f"лорд {name} погиб: все регионы потеряны, "
                       f"армии распущены")


# ------------------------------------------------------------------ победа
def check_victory(state: dict, config: dict) -> str | None:
    """Условия победы (03 §3.1); после победы кампания — sandbox (бриф К1)."""
    if state["flags"].get("victory"):
        return None
    player = st.human_lord_id(config)
    owned = len(st.owned_region_ids(state, player))
    kind: str | None = None
    if owned == 0:
        kind = "defeat"
    else:
        victory = config.get("victory") or {}
        full = victory.get("full") or {}
        short = victory.get("short") or {}
        if full.get("type") == "control_regions" \
                and owned >= int(full.get("count", 10 ** 9)):
            kind = "full"
        elif short.get("type") == "control_regions" \
                and owned >= int(short.get("count", 10 ** 9)):
            kind = "short"
        elif short.get("type") == "eliminate_lords":
            targets = short.get("lords") or []
            if targets and all(not st.owned_region_ids(state, lid)
                               for lid in targets):
                kind = "short"
    if kind:
        state["flags"]["victory"] = {"level": kind,
                                     "season": int(state["season"])}
        state["flags"]["sandbox"] = kind != "defeat"
        message = "ПОБЕДА" if kind != "defeat" else "ПОРАЖЕНИЕ"
        deadline = (config.get("victory") or {}).get(kind, {}).get("by_season")
        late = f" (срок {deadline} вышел)" if deadline is not None \
            and int(state["season"]) > int(deadline) else ""
        st.logf(state, f"{message}: условие «{kind}» выполнено{late}"
                       + (" — кампания продолжается в sandbox"
                          if kind != "defeat" else ""))
    return kind


def player_action_made(state: dict) -> None:
    """Отметить решение игрока (счётчик пустых сезонов, 07 §7.2)."""
    state["counters"]["player_actions_season"] = int(
        state["counters"].get("player_actions_season", 0)) + 1
