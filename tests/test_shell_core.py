"""Тесты ядра оболочки: конфиг/состояние, экономика, дипломатия, авто-резолв.

Формула авто-резолва — 07 §7.4 (дословно); экономика — 07 §7.10 (единый код
игрока и ИИ); дипломатия — 07 §7.8; контракты данных — 03 §3.1/§3.2.
"""
from __future__ import annotations

import copy
import random

import pytest

from conftest import make_mini_config, make_state
from sh2tw.shell import autoresolve as ar
from sh2tw.shell import diplomacy as dip
from sh2tw.shell import economy as eco
from sh2tw.shell import state as st

ROSTER_S10 = {"spearman": {"count": 10, "vet": 0.0}}


# ================================================================ конфигурация
def test_config_valid_and_normalized(mini_config):
    st.validate_config(mini_config)
    cfg = st.normalize_config(mini_config)
    assert cfg["economy"]["village_tax_gold_per_month"] == 50
    assert cfg["pacing"]["max_transitions_total"] == 15
    assert cfg["autoresolve"]["logit_k"] == 3.0
    assert cfg["events"]["probabilities"]["harvest_failure"] == 0.08


def test_config_duplicate_region_id(mini_config):
    mini_config["regions"].append(copy.deepcopy(mini_config["regions"][0]))
    with pytest.raises(st.ConfigError, match="дубликат"):
        st.validate_config(mini_config)


def test_config_disconnected_graph(mini_config):
    mini_config["regions"].append(
        {"id": "r09", "name": "Одинокий форт", "type": "castle",
         "neighbors": [], "map_template": "tpl_x", "product": "iron",
         "base_income": 30, "castle_levels": {"1": "aic_wood_keep"},
         "garrison_cap": 40})
    with pytest.raises(st.ConfigError, match="несвязен"):
        st.validate_config(mini_config)


def test_config_asymmetric_neighbors(mini_config):
    # r07 забывает про соседство с r01, а r01 — помнит: несимметрично
    mini_config["regions"][2]["neighbors"].remove("r01")
    with pytest.raises(st.ConfigError, match="несимметричн"):
        st.validate_config(mini_config)


def test_config_castle_without_levels_and_template(mini_config):
    del mini_config["regions"][0]["castle_levels"]
    with pytest.raises(st.ConfigError, match="castle_levels"):
        st.validate_config(mini_config)
    mini_config["regions"][0]["castle_levels"] = {"1": "aic_wood_keep"}
    del mini_config["regions"][0]["map_template"]
    with pytest.raises(st.ConfigError, match="map_template"):
        st.validate_config(mini_config)


def test_config_persona_and_start_region(mini_config):
    mini_config["lords"][1]["persona"]["aggression"] = 1.5
    with pytest.raises(st.ConfigError, match="persona.aggression"):
        st.validate_config(mini_config)
    mini_config["lords"][1]["persona"]["aggression"] = 0.5
    del mini_config["lords"][1]["persona"]["loyal"]       # черта отсутствует
    with pytest.raises(st.ConfigError, match="persona.loyal"):
        st.validate_config(mini_config)
    mini_config["lords"][1]["persona"]["loyal"] = 0.2
    mini_config["lords"][1]["persona"]["doctrine_pool"] = []
    with pytest.raises(st.ConfigError, match="doctrine_pool"):
        st.validate_config(mini_config)
    mini_config["lords"][1]["persona"]["doctrine_pool"] = ["doc_x"]
    mini_config["lords"][1]["start_region"] = "r99"
    with pytest.raises(st.ConfigError, match="start_region"):
        st.validate_config(mini_config)


def test_config_bad_victory_type(mini_config):
    mini_config["victory"]["short"]["type"] = "domination"
    with pytest.raises(st.ConfigError, match="victory.short.type"):
        st.validate_config(mini_config)


def test_new_game_contract(mini_config):
    s = make_state(mini_config, rng_seed=7)
    assert s["season"] == 0 and s["phase"] == "PLAYER_ACTIONS"
    assert s["season_name"] == "Весна"
    assert s["treasury"] == {"gold": 500, "honour": 100, "rank": 1}
    assert s["ai_treasury"] == {"l_hawk": 500}          # плоские казны ИИ
    assert s["ai_honour"] == {"l_hawk": 100}
    assert s["ai_start_regions"] == {"l_hawk": ["r07"]}
    r01 = s["regions"]["r01"]
    assert r01["owner"] == "player" and r01["castle_level"] == 1
    assert r01["loyalty"] == 60 and r01["development_points"] == 30
    assert r01["garrison"]["spearman"]["count"] == 10
    assert r01["garrison"]["archer"]["count"] == 6
    assert s["regions"]["r02"]["owner"] is None
    assert s["regions"]["r07"]["owner"] == "l_hawk"
    assert s["diplomacy"]["pairs"]["l_hawk|player"] == "peace"
    army = st.army_of(s, "player")
    assert st.roster_total(army["roster"]) == 20        # spearman 12 + archer 8
    assert s["counters"]["player_actions_season"] == 0
    assert s["flags"]["victory"] is None and s["flags"]["harsh_winter"] is False


# ==================================================================== экономика
def test_region_income_castle(mini_config):
    cfg = st.normalize_config(mini_config)
    s = make_state(mini_config)
    # r01 (castle, product): (40 × 1.1) × 3 − 16 × 0.2 × 3 = 132 − 9.6 → 122
    assert eco.region_income(s, cfg, "r01") == 122
    # r07 (castle, product): (44 × 1.1) × 3 − 9.6 = 145.2 − 9.6 → 136
    assert eco.region_income(s, cfg, "r07") == 136
    # r02 (нейтральная деревня): 28 × 3 = 84
    assert eco.region_income(s, cfg, "r02") == 84


def test_region_income_village_tax_to_castle(mini_config):
    cfg = st.normalize_config(mini_config)
    s = make_state(mini_config)
    s["regions"]["r02"]["owner"] = "player"     # деревня-соседь r01 того же
    # владельца: r01 += 50 × 3 → (132 + 150) − 9.6 = 272.4 → 272
    assert eco.region_income(s, cfg, "r01") == 272
    assert eco.region_income(s, cfg, "r02") == 84


def test_region_income_harsh_winter_doubles_upkeep(mini_config):
    cfg = st.normalize_config(mini_config)
    s = make_state(mini_config)
    s["flags"]["harsh_winter"] = True
    # содержание ×2: 132 − 16 × 0.2 × 3 × 2 = 132 − 19.2 → 113
    assert eco.region_income(s, cfg, "r01") == 113


def test_region_income_event_penalty(mini_config):
    cfg = st.normalize_config(mini_config)
    s = make_state(mini_config)
    s["regions"]["r01"]["income_penalty"] = 0.5        # harvest_failure
    # 132 × 0.5 − 9.6 = 56.4 → 56
    assert eco.region_income(s, cfg, "r01") == 56
    s["regions"]["r01"]["income_penalty"] = 0.8        # rats
    assert eco.region_income(s, cfg, "r01") == 96      # 105.6 − 9.6


def test_season_income_includes_army_upkeep(mini_config):
    cfg = st.normalize_config(mini_config)
    s = make_state(mini_config)
    # игрок: r01 (122) − армия 20 × 0.2 × 3 = 12 → 110
    assert eco.season_income(s, cfg, "player") == 110
    # ИИ: тот же код (честность 07 §7.10): r07 (136) − 12 = 124
    assert eco.season_income(s, cfg, "l_hawk") == 124
    s["flags"]["harsh_winter"] = True
    # регион: 132 − 19.2 → 113; армия: 20 × 0.2 × 3 × 2 = 24 → 89
    assert eco.season_income(s, cfg, "player") == 89


# ================================================================== дипломатия
def test_pair_key_and_validation(mini_config):
    s = make_state(mini_config)
    assert st.pair_key("player", "l_hawk") == "l_hawk|player"
    assert dip.get_pair(s, "player", "l_hawk") == "peace"
    dip.set_pair(s, "player", "l_hawk", "war")
    assert dip.get_pair(s, "l_hawk", "player") == "war"
    with pytest.raises(ValueError):                     # неизвестное состояние
        dip.set_pair(s, "player", "l_hawk", "vassal")
    with pytest.raises(ValueError):                     # неизвестный лорд
        dip.get_pair(s, "player", "l_nobody")


def test_declare_war_pulls_allies_next_season(mini_config):
    cfg = st.normalize_config(mini_config)
    cfg["lords"].append({"id": "l_ox", "name": "Лорд Вол", "is_human": False,
                         "start_region": "r02", "persona": {
                             "aggression": 0.2, "greed": 0.4, "builder": 0.5,
                             "loyal": 0.8, "doctrine_pool": ["doc_turtle_v1"]}})
    s = st.new_game(cfg)
    s["regions"]["r02"]["owner"] = "l_ox"
    s["diplomacy"]["pairs"]["l_hawk|l_ox"] = "alliance"
    joins = dip.declare_war(s, cfg, "player", "l_hawk")
    assert joins == [{"season": 1, "ally": "l_ox", "against": "player"}]
    assert dip.get_pair(s, "player", "l_hawk") == "war"
    assert dip.process_pending_ally_joins(s, cfg) == []  # сезон не настал
    s["season"] = 1
    joined = dip.process_pending_ally_joins(s, cfg)
    assert joined and dip.get_pair(s, "player", "l_ox") == "war"
    assert not s["diplomacy"]["pending_ally_joins"]


def test_tributes_pay_and_expire(mini_config):
    cfg = st.normalize_config(mini_config)
    s = make_state(mini_config)
    s["season"] = 5
    s["diplomacy"]["tributes"] = [
        {"from": "l_hawk", "to": "player", "gold_per_season": 15,
         "until_season": 6}]
    paid = dip.process_tributes(s, cfg)
    assert paid == [{"from": "l_hawk", "to": "player", "gold": 15}]
    assert s["treasury"]["gold"] == 515
    assert s["ai_treasury"]["l_hawk"] == 485
    assert len(s["diplomacy"]["tributes"]) == 1    # платит до сезона 6 включ.
    s["season"] = 6
    dip.process_tributes(s, cfg)
    assert len(s["diplomacy"]["tributes"]) == 1    # последний платёж — запись
    s["season"] = 7                                # ещё жива (season > until)
    dip.process_tributes(s, cfg)                   # только теперь удаляется
    assert s["diplomacy"]["tributes"] == []
    assert s["treasury"]["gold"] == 530            # 515 + 15 (платежи S5 и S6)


def test_make_peace(mini_config):
    cfg = st.normalize_config(mini_config)
    s = make_state(mini_config)
    dip.set_pair(s, "player", "l_hawk", "war")
    rec = dip.make_peace(s, cfg, "player", "l_hawk",
                         {"gold_per_season": 15, "until_season": 9})
    assert rec is not None and dip.get_pair(s, "player", "l_hawk") == "peace"
    assert s["diplomacy"]["tributes"][0]["from"] == "player"
    assert any("заключают мир" in line for line in s["events_log"])


# ================================================================ авто-резолв
def test_autoresolve_symmetric_forces_is_fifty(mini_config):
    cfg = st.normalize_config(mini_config)
    res = ar.autoresolve({"lord": "player", "roster": ROSTER_S10},
                         {"lord": "l_hawk", "roster": ROSTER_S10,
                          "castle_level": 0},
                         cfg, random.Random(1))
    assert res["p_win_att"] == pytest.approx(0.5)
    assert res["bin"] == {"battle_type": "field",
                          "strength_ratio_tercile": 1}
    assert res["model"] == "formula_v1" and res["winner"] in (
        "player", "l_hawk")


def test_stronger_side_wins_more_often(mini_config):
    cfg = st.normalize_config(mini_config)
    strong = {"spearman": {"count": 20, "vet": 0.0}}   # S=400 против S=200
    wins = 0
    for i in range(100):                               # сид-детерминированно
        res = ar.autoresolve({"lord": "player", "roster": strong},
                             {"lord": "l_hawk", "roster": ROSTER_S10,
                              "castle_level": 0}, cfg, random.Random(i))
        wins += res["winner"] == "player"
    assert wins > 60                                   # P ≈ 0.818 при k=3


def test_walls_help_defender(mini_config):
    cfg = st.normalize_config(mini_config)
    att = {"spearman": {"count": 20, "vet": 0.0}}
    p_open = ar.battle_forecast(cfg, att, ROSTER_S10, 0)["p_win_att"]
    p_walls = ar.battle_forecast(cfg, att, ROSTER_S10, 3)["p_win_att"]
    assert p_walls < p_open
    assert ar.battle_forecast(cfg, att, ROSTER_S10, 3)["bin"][
        "battle_type"] == "siege"


def test_siege_without_park_penalty_and_park_bonus(mini_config):
    cfg = st.normalize_config(mini_config)
    att = {"spearman": {"count": 12, "vet": 0.0}}     # S_att = 240
    no_park = ar.battle_forecast(cfg, att, ROSTER_S10, 1)
    with_park = ar.battle_forecast(
        cfg, {**att, "catapult": {"count": 2, "vet": 0.0}},
        ROSTER_S10, 1)                    # парк ×(1+0.1×2) против штрафа ×0.5
    assert with_park["p_win_att"] > no_park["p_win_att"]
    assert no_park["att_eff"] == pytest.approx(240 * 0.5)
    assert with_park["att_eff"] == pytest.approx((240 + 2 * 150) * 1.2)
    # осадный парк можно передать и явно (siege_units_count)
    explicit = ar.battle_forecast(cfg, att, ROSTER_S10, 1, siege_park=2)
    assert explicit["att_eff"] == pytest.approx(240 * 1.2)  # без штрафа стен


def test_siege_unit_value_is_constant_150():
    assert ar.unit_price("catapult") == 150.0
    assert ar.roster_strength({"catapult": {"count": 1, "vet": 0.0}}) == 150.0
    assert ar.siege_units_count({"catapult": {"count": 2, "vet": 0.0},
                                 "archer": {"count": 5, "vet": 0.0}}) == 2


def test_strength_ratio_terciles(mini_config):
    cfg = st.normalize_config(mini_config)
    weak = ar.battle_forecast(cfg, ROSTER_S10, {"spearman": {"count": 20,
                                                             "vet": 0.0}},
                              0)["bin"]["strength_ratio_tercile"]
    even = ar.battle_forecast(cfg, ROSTER_S10, ROSTER_S10, 0)["bin"][
        "strength_ratio_tercile"]
    strong = ar.battle_forecast(cfg, {"spearman": {"count": 20, "vet": 0.0}},
                                ROSTER_S10, 0)["bin"]["strength_ratio_tercile"]
    assert (weak, even, strong) == (0, 1, 2)


def test_veterans_die_last(mini_config):
    _ = mini_config
    # 20 копейщиков, 50 % ветеранов: 10 обычных (200) + 10 вет. (250)
    roster = {"spearman": {"count": 20, "vet": 0.5}}
    surv, losses = ar.apply_loss_value(roster, ar.unit_values_cached(), 300)
    # сначала выкашиваются обычные (все 10), затем 4 ветерана
    assert losses["spearman"] == 14
    assert surv == {"spearman": {"count": 6, "vet": 1.0}}


def test_losses_proportional_and_loser_range(mini_config):
    cfg = st.normalize_config(mini_config)
    res = ar.autoresolve({"lord": "player",
                          "roster": {"spearman": {"count": 20, "vet": 0.0}}},
                         {"lord": "l_hawk",
                          "roster": {"spearman": {"count": 10, "vet": 0.0}},
                          "castle_level": 0},
                         cfg, random.Random(11))
    loser, winner = ("l_hawk", "player") if res["winner"] == "player" \
        else ("player", "l_hawk")
    price = 20.0
    lost_loser = sum(res["losses"][loser].values()) * price
    lost_winner = sum(res["losses"][winner].values()) * price
    s_loser = 200.0
    assert lost_loser >= 0.6 * s_loser - price          # проигравший: 60–100 %
    assert lost_winner <= 0.25 * s_loser + price        # победитель: 0.25×S_l
    # выжившие ветераны победителя получают +0.5 только в apply_battle_result
    assert res["survivors"][winner]                     # победитель уцелел


def test_autoresolve_deterministic_by_seed(mini_config):
    cfg = st.normalize_config(mini_config)
    kw = dict(attacker={"lord": "player",
                        "roster": {"archer": {"count": 15, "vet": 0.2}}},
              defender={"lord": "l_hawk",
                        "roster": {"spearman": {"count": 18, "vet": 0.0}},
                        "castle_level": 2},
              cfg=cfg)
    r1 = ar.autoresolve(rng=random.Random(77), **kw)
    r2 = ar.autoresolve(rng=random.Random(77), **kw)
    assert st.canonical_json(r1) == st.canonical_json(r2)


def test_calibration_mixes_empirical_winrate(mini_config):
    cfg = st.normalize_config(mini_config)
    res = ar.autoresolve({"lord": "player", "roster": ROSTER_S10},
                         {"lord": "l_hawk", "roster": ROSTER_S10,
                          "castle_level": 0},
                         cfg, random.Random(1),
                         calibration={"field_1": {"battles": 10,
                                                  "att_wins": 10}})
    assert res["calibrated"] is True
    assert res["p_win_att"] == pytest.approx(0.75)      # 0.5×0.5 + 0.5×1.0
    assert res["model"] == "formula_v1"


def test_fallback_when_strengths_zero(mini_config):
    cfg = st.normalize_config(mini_config)
    both = ar.autoresolve({"lord": "player", "roster": {}},
                          {"lord": "l_hawk", "roster": {}, "castle_level": 0},
                          cfg, random.Random(1))
    assert both["winner"] is None and both["model"] == "fallback_strongest"
    assert both["warning"]                               # ничья объяснена
    one = ar.autoresolve({"lord": "player", "roster": ROSTER_S10},
                         {"lord": "l_hawk", "roster": {}, "castle_level": 0},
                         cfg, random.Random(1))
    assert one["winner"] == "player" and one["model"] == "fallback_strongest"
    assert one["losses"]["l_hawk"] == {}
    assert one["survivors"]["player"] == ROSTER_S10
