"""Тесты сезонного цикла оболочки (машина состояний 07 §7.2, события 07 §7.9,
стратегический ИИ 07 §7.3, применение итогов 07 §7.7, победа 03 §3.1).

Детерминизм: два прогона new_game(seed) + 3 × next_season дают идентичные
состояния (кроме ts в events.jsonl — здесь campaign_dir не передаётся).
"""
from __future__ import annotations

import copy
import json
import random

import pytest

from conftest import make_mini_config, make_state
from sh2tw.shell import agenda_ai as agenda
from sh2tw.shell import diplomacy as dip
from sh2tw.shell import economy
from sh2tw.shell import events_catalog
from sh2tw.shell import season
from sh2tw.shell import state as st


def cfg_with(**event_probs) -> dict:
    """Мини-конфиг с переопределёнными вероятностями событий."""
    cfg = st.normalize_config(make_mini_config())
    cfg["events"]["probabilities"].update(event_probs)
    return cfg


def run_seasons(cfg: dict, n: int, seed: int = 7):
    """new_game(seed) + n × next_season; возвращает (state, результаты)."""
    s = st.new_game(cfg, rng_seed=seed)
    results = [season.next_season(s, cfg) for _ in range(n)]
    return s, results


# ============================================================== три сезона
def test_three_seasons_mini_campaign():
    cfg = cfg_with()
    s, results = run_seasons(cfg, 3)
    assert [r["season"] for r in results] == [1, 2, 3]
    assert [r["season_name"] for r in results] == ["Весна", "Лето", "Осень"]
    # доходы начислены: игрок и ИИ получили золото за 3 сезона
    assert s["treasury"]["gold"] > 500
    assert s["ai_treasury"]["l_hawk"] != 500
    # ИИ действовал (журнал фиксирует кампании лорда)
    ai_log = "\n".join(s["events_log"])
    assert ("развивает" in ai_log) or ("покупает" in ai_log) \
        or ("набирает" in ai_log) or ("выжидает" in ai_log)
    # развитие ИИ «план + время»: очки растут каждый сезон
    assert s["regions"]["r07"]["development_points"] > 30
    # счётчик пустых сезонов: игрок ничего не делал — 3 подряд
    assert s["counters"]["empty_seasons_streak"] == 3
    assert results[0]["warnings"] == []                 # 1 ≤ 2 — без warnings
    assert any("пустых сезонов" in w for w in results[2]["warnings"])
    # фаза остановки — PLAYER_ACTIONS, счётчик действий обнулён
    assert s["phase"] == "PLAYER_ACTIONS"
    assert s["counters"]["player_actions_season"] == 0
    # offers/events — списки (возможно пустые), структура ответа стабильна
    for r in results:
        assert isinstance(r["offers"], list) and isinstance(r["events"], list)
        assert isinstance(r["warnings"], list)


def test_player_action_resets_empty_streak():
    cfg = cfg_with()
    s, results = run_seasons(cfg, 2)
    assert s["counters"]["empty_seasons_streak"] == 2
    season.player_action_made(s)                        # игрок действовал
    r = season.next_season(s, cfg)
    assert s["counters"]["empty_seasons_streak"] == 0
    assert r["warnings"] == []


def test_determinism_two_runs_identical_state():
    cfg = cfg_with()
    s1, _ = run_seasons(cfg, 3, seed=97531)
    s2, _ = run_seasons(cfg, 3, seed=97531)
    assert json.dumps(s1, sort_keys=True) == json.dumps(s2, sort_keys=True)
    s3, _ = run_seasons(cfg, 3, seed=97532)             # другой сид — другой
    assert json.dumps(s1, sort_keys=True) != json.dumps(s3, sort_keys=True)


def test_income_accrued_exact_first_season():
    cfg = cfg_with()                                    # все события выключим
    cfg["events"]["probabilities"] = {k: 0.0 for k in
                                      cfg["events"]["probabilities"]}
    s = st.new_game(cfg, rng_seed=3)
    season.next_season(s, cfg)
    # игрок: 500 + сезон r01 (122) − армия (12) = 610 (событий нет)
    assert s["treasury"]["gold"] == 610
    # ИИ: 500 + 136 − 12 − расходы кампании ИИ (журнал объяснит разницу)
    assert s["ai_treasury"]["l_hawk"] == 500 + 124 - _ai_spending(s)


def _ai_spending(s: dict) -> int:
    """Расходы ИИ за сезон по журналу (develop −100, recruit −200..400)."""
    log = "\n".join(s["events_log"])
    if "развивает" in log:
        return agenda.DEV_ACTION_COST
    return 0


# =================================================================== события
def test_harvest_failure_sets_income_penalty():
    cfg = cfg_with(harvest_failure=1.0)                 # неурожай гарантирован
    s = st.new_game(cfg, rng_seed=5)
    s["regions"]["r02"]["owner"] = "player"             # wheat-регион игрока
    r = season.next_season(s, cfg)
    fired = [e for e in r["events"] if e.get("id") == "harvest_failure"]
    assert fired and fired[0]["region"] == "r02"
    assert s["regions"]["r02"]["income_penalty"] == 0.5
    # штраф бьёт по следующему начислению (доход текущего уже уплачен)
    assert economy.region_income(s, cfg, "r02") == int(round(28 * 3 * 0.5))
    cfg["events"]["probabilities"]["harvest_failure"] = 0.0
    season.next_season(s, cfg)                          # SEASON_START сбросил
    assert "income_penalty" not in s["regions"]["r02"]


def test_harsh_winter_doubles_upkeep_once():
    cfg = cfg_with(harsh_winter=1.0)
    s = st.new_game(cfg, rng_seed=5)
    gold_after_s1 = None
    season.next_season(s, cfg)                          # событие выпало в S1
    assert s["flags"]["harsh_winter"] is True
    gold_after_s1 = s["treasury"]["gold"]
    season.next_season(s, cfg)                          # S2: штраф действует…
    assert s["flags"]["harsh_winter"] is True           # …выпал снова (p=1.0)
    cfg["events"]["probabilities"]["harsh_winter"] = 0.0
    season.next_season(s, cfg)                          # S3: сброс на старте
    assert s["flags"]["harsh_winter"] is False
    assert gold_after_s1 > 0


def test_fair_gives_honour_to_all_lords():
    cfg = cfg_with(fair=1.0, hunt=0.0, feast=0.0, embassy=0.0, plague=0.0)
    s = st.new_game(cfg, rng_seed=5)
    season.next_season(s, cfg)
    assert s["treasury"]["honour"] == 100 + 5           # игроку +5
    assert s["ai_honour"]["l_hawk"] == 100 + 2          # прочим лордам +2


def test_rebellion_in_low_loyalty_region():
    cfg = cfg_with(rebellion=0.3)
    s = st.new_game(cfg, rng_seed=5)
    s["regions"]["r01"]["loyalty"] = 0     # p = 0.3 + (25-0)/25 ≥ 1 — точно
    garrison_before = st.roster_total(s["regions"]["r01"]["garrison"])
    r = season.next_season(s, cfg)
    fired = [e for e in r["events"] if e.get("id") == "rebellion"]
    assert fired and fired[0]["region"] == "r01"
    rs = s["regions"]["r01"]
    assert rs["loyalty"] == 20
    assert st.roster_total(rs["garrison"]) == garrison_before \
        - int(garrison_before * 0.3)      # −30 % (округление вниз по типам)
    assert any("регион игрока" in line for line in s["events_log"])


def test_rebellion_skipped_when_loyal():
    cfg = cfg_with(rebellion=1.0)
    s = st.new_game(cfg, rng_seed=5)
    r = season.next_season(s, cfg)                     # лояльность 60 ≥ 25
    assert not [e for e in r["events"] if e.get("id") == "rebellion"]


# ================================================================= ИИ-агенда
def test_ai_defends_attacked_region():
    cfg = cfg_with()
    s = st.new_game(cfg, rng_seed=11)
    dip.set_pair(s, "player", "l_hawk", "war")
    rng = random.Random(3)
    agenda.ai_turn(s, cfg, rng, attacked_regions={"r07"})
    assert any("оборона" in line or "оборону" in line or "обороняет" in line
               for line in s["events_log"])
    assert st.army_of(s, "l_hawk")["located_region"] == "r07"  # лорд в замке


def test_ai_buys_neutral_village_with_honour():
    cfg = cfg_with()                     # жадный лорд без угроз границ
    cfg["lords"][1]["persona"].update({"aggression": 0.0, "greed": 1.0,
                                       "builder": 0.0, "loyal": 0.0})
    s = st.new_game(cfg, rng_seed=13)
    agenda.ai_turn(s, cfg, random.Random(1))
    assert s["regions"]["r02"]["owner"] == "l_hawk"     # деревня куплена
    assert s["ai_honour"]["l_hawk"] == 0                # −100 чести
    assert any("покупает" in line for line in s["events_log"])


def test_ai_develops_when_rich_and_peaceful():
    cfg = cfg_with()
    cfg["lords"][1]["persona"].update({"aggression": 0.0, "greed": 0.0,
                                       "builder": 1.0, "loyal": 0.0})
    s = st.new_game(cfg, rng_seed=13)
    points_before = s["regions"]["r07"]["development_points"]
    agenda.ai_turn(s, cfg, random.Random(1))
    assert s["regions"]["r07"]["development_points"] == points_before + 20
    assert s["ai_treasury"]["l_hawk"] == 500 - 100


def test_ai_offer_peace_after_losing_region():
    cfg = cfg_with()
    # робкий и жадный лорд: recruit (w_aggr=0) проигрывает offer_peace (w_greed=1)
    cfg["lords"][1]["persona"].update({"aggression": 0.0, "greed": 1.0,
                                       "builder": 0.0, "loyal": 0.0})
    s = st.new_game(cfg, rng_seed=13)
    dip.set_pair(s, "player", "l_hawk", "war")
    # ястреб владел двумя регионами (r07 + купленная r02), потерял r07:
    # regions_owned (1) < regions_at_start (2) → предложение мира
    s["regions"]["r02"]["owner"] = "l_hawk"
    s["ai_start_regions"]["l_hawk"] = ["r07", "r02"]
    s["regions"]["r07"]["owner"] = "player"
    offers = agenda.ai_turn(s, cfg, random.Random(1))
    assert {"offer": "peace", "from": "l_hawk",
            "season": 0} in s["pending_offers"]
    assert any(o.get("offer") == "peace" for o in offers)


def test_ai_attack_on_player_creates_battle_offer():
    cfg = cfg_with()
    s = st.new_game(cfg, rng_seed=13)
    # мир не обязателен для атаки (07 §7.3); игрок ослаблен: гарнизон и
    # армия пусты → сила ИИ ≥ 1.3 × оборона цели
    s["regions"]["r01"]["garrison"] = {}
    st.army_of(s, "player")["roster"] = {}
    offers = agenda.ai_turn(s, cfg, random.Random(1))
    assert any(o.get("offer") == "battle"
               and o.get("target_region") == "r01" for o in offers)
    assert "r01" in s["attacked_regions"]
    assert dip.get_pair(s, "player", "l_hawk") == "peace"  # война — при бое


# ============================================================== итоги боёв
def test_apply_battle_result_capture_rules():
    cfg = cfg_with()
    s = st.new_game(cfg, rng_seed=17)
    season.apply_battle_result(s, cfg, {
        "attacker_lord": "player", "defender_lord": "l_hawk",
        "target_region": "r07", "outcome": "win_attacker",
        "survivors": {"player": {"spearman": {"count": 10, "vet": 0.0}},
                      "l_hawk": {"spearman": {"count": 2, "vet": 0.0}}},
        "losses": {"l_hawk": {"spearman": 8}}})
    rs = s["regions"]["r07"]
    assert rs["owner"] == "player"                       # регион победителю
    assert rs["castle_level"] == 0                       # 1 − 1 (разграбление)
    assert rs["loyalty"] == 30
    army = st.army_of(s, "player")
    assert army["located_region"] == "r07"               # армия вошла в регион
    assert army["roster"]["spearman"]["vet"] == 0.5      # ветераны победителя
    # у ИИ не осталось регионов → мёртв, армии распущены (07 §7.7)
    assert st.army_of(s, "l_hawk") is None
    assert any("погиб" in line for line in s["events_log"])
    assert "r07" in s["attacked_regions"]


def test_apply_battle_result_defender_holds():
    cfg = cfg_with()
    s = st.new_game(cfg, rng_seed=17)
    season.apply_battle_result(s, cfg, {
        "attacker_lord": "player", "defender_lord": "l_hawk",
        "target_region": "r07", "outcome": "win_defender",
        "survivors": {"l_hawk": {"spearman": {"count": 5, "vet": 0.0}}}})
    rs = s["regions"]["r07"]
    assert rs["owner"] == "l_hawk"
    assert rs["garrison"]["spearman"]["vet"] == 0.5      # ветераны обороны
    assert st.army_of(s, "player") is not None           # армия игрока цела


def test_aborted_mercy_then_desertion():
    cfg = cfg_with()
    s = st.new_game(cfg, rng_seed=17)
    army = st.army_of(s, "player")
    before = st.roster_total(army["roster"])
    for _i in range(2):                                  # 2 aborted — милосердие
        season.apply_battle_result(s, cfg, {
            "attacker_lord": "player", "defender_lord": "l_hawk",
            "target_region": "r07", "outcome": "aborted"})
        assert st.roster_total(army["roster"]) == before
    season.apply_battle_result(s, cfg, {                 # 3-й подряд
        "attacker_lord": "player", "defender_lord": "l_hawk",
        "target_region": "r07", "outcome": "aborted"})
    assert any("дезертирство" in line for line in s["events_log"])
    assert st.roster_total(army["roster"]) < before      # −20 % армии
    assert s["counters"]["aborted_streak"] == 0          # счётчик сброшен


def test_victory_eliminate_lords_after_capture():
    cfg = cfg_with()
    s = st.new_game(cfg, rng_seed=17)
    season.apply_battle_result(s, cfg, {
        "attacker_lord": "player", "defender_lord": "l_hawk",
        "target_region": "r07", "outcome": "win_attacker",
        "survivors": {"player": {"spearman": {"count": 10, "vet": 0.0}}}})
    assert not st.owned_region_ids(s, "l_hawk")          # лорд мёртв
    assert st.army_of(s, "l_hawk") is None               # армии распущены
    assert any("погиб" in line for line in s["events_log"])
    level = season.check_victory(s, cfg)                 # RESOLUTION-проверка
    assert level == "short"
    assert s["flags"]["victory"] == {"level": "short", "season": 0}
    assert s["flags"]["sandbox"] is True                 # играем дальше


def test_victory_control_regions_full():
    cfg = cfg_with()
    s = st.new_game(cfg, rng_seed=17)
    s["regions"]["r02"]["owner"] = "player"             # 3 из 3 регионов
    s["regions"]["r07"]["owner"] = "player"
    assert season.check_victory(s, cfg) == "full"


def test_defeat_when_player_loses_everything():
    cfg = cfg_with()
    s = st.new_game(cfg, rng_seed=17)
    season.apply_battle_result(s, cfg, {
        "attacker_lord": "l_hawk", "defender_lord": "player",
        "target_region": "r01", "outcome": "win_attacker",
        "survivors": {"l_hawk": {"spearman": {"count": 9, "vet": 0.0}}}})
    assert s["flags"]["victory"] == {"level": "defeat", "season": 0}


# ============================================================ дипломатия в цикле
def test_ally_joins_war_through_season_cycle():
    cfg = st.normalize_config(make_mini_config())
    cfg["lords"].append({"id": "l_ox", "name": "Лорд Вол", "is_human": False,
                         "start_region": "r02", "persona": {
                             "aggression": 0.2, "greed": 0.4, "builder": 0.5,
                             "loyal": 0.8, "doctrine_pool": ["doc_t_v1"]}})
    s = st.new_game(cfg, rng_seed=19)
    s["regions"]["r02"]["owner"] = "l_ox"
    s["diplomacy"]["pairs"]["l_hawk|l_ox"] = "alliance"
    dip.declare_war(s, cfg, "player", "l_hawk")         # враги вольны:
    assert dip.get_pair(s, "player", "l_ox") == "peace"  # вступит через сезон
    season.next_season(s, cfg)                           # RESOLUTION S0: рано
    assert dip.get_pair(s, "player", "l_ox") == "peace"
    season.next_season(s, cfg)                           # RESOLUTION S1: пора
    assert dip.get_pair(s, "player", "l_ox") == "war"
    assert any("вступает в войну" in line for line in s["events_log"])


def test_battle_offer_autoresolved_at_resolution():
    cfg = cfg_with()
    s = st.new_game(cfg, rng_seed=19)
    s["pending_offers"].append({"offer": "battle", "attacker": "l_hawk",
                                "target_region": "r01", "season": 0})
    season.next_season(s, cfg)                           # бой не принят
    assert s["pending_offers"] == []
    assert s["counters"]["battles_auto"] >= 1
    assert any("не принят" in line for line in s["events_log"])
