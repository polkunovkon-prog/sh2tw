"""Тесты честности (S2.8; контракт 03 §3.9, 04 §4.5/§4.7).

Приёмка 04 §4.7 «Честность»: синтетические пары снимков — чистый матч →
pass; «+3000 золота из ниоткуда» → violation. Реальные снимки (lords=null,
G18) → честная деградация insufficient_data.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from sh2tw.honesty.accounting import (
    HonestyError,
    honesty_report,
    load_unit_values,
    provision_balance,
    provision_balance_detail,
    roster_value,
    side_provision_value,
)

REPO = Path(__file__).resolve().parents[1]

# Цены из ref/unit_types.csv (Прил. D): лучник 30, копейщик 20
UV = load_unit_values()


# --------------------------------------------------------------- цены/росписи
def test_unit_values_loaded_from_ref_csv():
    assert UV["archer"] == 30.0 and UV["spearman"] == 20.0


def test_roster_value_plain_and_veterans():
    # 24 лучника × 30 = 720
    assert roster_value({"archer": {"count": 24, "vet": 0.0}}, UV) == 720.0
    # ветераны: 0.25 → множитель 1.0625: 24×30×1.0625 = 765
    assert roster_value({"archer": {"count": 24, "vet": 0.25}}, UV) == 765.0


def test_roster_value_unknown_unit_raises():
    with pytest.raises(HonestyError):
        roster_value({"spacemarine": {"count": 1, "vet": 0.0}}, UV)


def test_side_provision_value_channels():
    side_a = {"lord": "player", "provision": {"channel": "estate_troops",
               "roster": {"archer": {"count": 10, "vet": 0.0},
                          "spearman": {"count": 10, "vet": 0.0}}},
              "budget_gold": 100, "budget_honour": 2}
    # 10×30 + 10×20 + 100 + 2×10 = 620
    assert side_provision_value(side_a, UV) == 620.0
    side_b = {"lord": "l_hawk", "provision": {"channel": "aic_template",
               "garrison_roster": {"spearman": {"count": 31, "vet": 0.0}}}}
    assert side_provision_value(side_b, UV) == 620.0


# ---------------------------------------------------------- баланс ДО матча
def spec_2_sides(a_value: float, b_value: float) -> dict:
    def side(lord, gold):
        return {"role": "attacker" if lord == "player" else "defender",
                "lord": lord, "is_human": lord == "player",
                "provision": {"channel": "war_chest",
                              "roster": {"archer": {"count": gold // 30 or 1, "vet": 0.0}}},
                "budget_gold": 0, "budget_honour": 0}
    # точная настройка стоимости через budget_gold
    sa = side("player", 0); sa["provision"]["roster"] = {}
    sa["budget_gold"] = a_value
    sb = side("l_hawk", 0); sb["provision"]["roster"] = {}
    sb["budget_gold"] = b_value
    return {"schema_version": "1.0", "scene_id": "sc_t", "type": "field",
            "sides": [sa, sb], "duration_months": 10}


def test_provision_balance_true_when_equal():
    assert provision_balance(spec_2_sides(1000, 1000)) is True


def test_provision_balance_true_at_10pct_boundary():
    # ровно +10 % — ещё допустимо (допуск ≤ 1.10)
    assert provision_balance(spec_2_sides(1000, 909.1)) is True


def test_provision_balance_false_when_imbalanced():
    det = provision_balance_detail(spec_2_sides(1000, 500))
    assert det.ok is False and det.ratio == pytest.approx(2.0)
    assert provision_balance(spec_2_sides(1000, 500)) is False


def test_provision_balance_both_zero_is_trivially_ok():
    assert provision_balance(spec_2_sides(0, 0)) is True


def test_provision_balance_requires_two_sides():
    with pytest.raises(HonestyError):
        provision_balance({"sides": [{"lord": "player"}]})


# ------------------------------------------------- синтетические матчи
def snap_with_lords(lords: list[dict], estates: list[dict] | None = None) -> dict:
    return {"schema_version": "1.0",
            "source": {"file": "synthetic", "sha256": "0" * 64},
            "map": {"name": "S2TW_test"},
            "lords": lords,
            "estates": estates or [],
            "buildings": [], "actors": []}


def war_spec(months: int = 10) -> dict:
    return {"schema_version": "1.0", "scene_id": "sc_0001", "type": "siege",
            "duration_months": months,
            "sides": [
                {"role": "attacker", "lord": "player", "is_human": True,
                 "lord_snapshot_index": 0,
                 "provision": {"channel": "estate_troops",
                               "roster": {"archer": {"count": 20, "vet": 0.0},
                                          "spearman": {"count": 15, "vet": 0.0}}}},
                {"role": "defender", "lord": "l_hawk", "is_human": False,
                 "lord_snapshot_index": 1,
                 "provision": {"channel": "aic_template",
                               "garrison_roster": {"spearman": {"count": 30, "vet": 0.0}}}},
            ]}


def test_honesty_clean_match_pass():
    start = snap_with_lords([
        {"index": 0, "name": "player", "alive": True, "gold": 500,
         "troops": {"archer": 20, "spearman": 15}},
        {"index": 1, "name": "l_hawk", "alive": True, "gold": 500,
         "troops": {"spearman": 30}},
    ], estates=[{"marker_slot": 1, "type": "village", "owner_lord": 0},
                {"marker_slot": 2, "type": "village", "owner_lord": 1}])
    # чистый матч: игрок потерял часть войск и золота, лорд ИИ пал
    end = snap_with_lords([
        {"index": 0, "name": "player", "alive": True, "gold": 260,
         "troops": {"archer": 14, "spearman": 11}},
        {"index": 1, "name": "l_hawk", "alive": False, "gold": 0,
         "troops": {}},
    ], estates=[{"marker_slot": 1, "type": "village", "owner_lord": 0},
                {"marker_slot": 2, "type": "village", "owner_lord": 0}])
    rep = honesty_report(start, end, war_spec())
    assert rep["verdict"] == "pass", rep
    assert rep["violations"] == []
    # бюджет игрока: 1 деревня × 50 × 10 × 1.3 + 500 = 1150; потребление 0
    assert rep["accounting"]["player"]["income_expected_max"] == pytest.approx(1150.0)
    assert rep["accounting"]["l_hawk"]["income_observed"] == 0.0


def test_honesty_gold_from_nowhere_violation():
    start = snap_with_lords([
        {"index": 0, "name": "player", "alive": True, "gold": 500,
         "troops": {"archer": 20}},
    ], estates=[])
    # +3000 золота из ниоткуда: доходов нет (нет деревень), потребление 3000
    end = snap_with_lords([
        {"index": 0, "name": "player", "alive": True, "gold": 3500,
         "troops": {"archer": 20}},
    ], estates=[])
    spec = war_spec()
    spec["sides"] = [spec["sides"][0]]
    rep = honesty_report(start, end, spec)
    assert rep["verdict"] == "fail"
    v = rep["violations"][0]
    assert v["lord"] == "player" and v["consumption"] == pytest.approx(3000.0)


def test_honesty_real_snapshots_lords_null_insufficient_data():
    """Реальные снимки S2.6: lords=null (G18) — честная деградация."""
    real_like = {"schema_version": "1.0", "source": {"file": "sample_save.sh2"},
                 "map": {"name": "X"}, "lords": None, "estates": [],
                 "buildings": [], "actors": [], "game_time_months": None}
    rep = honesty_report(real_like, real_like, war_spec())
    assert rep["verdict"] == "insufficient_data"
    assert rep["violations"] == [] and rep["reasons"]


def test_honesty_duration_from_snapshots_when_spec_silent():
    start = snap_with_lords([{"index": 0, "name": "player", "alive": True,
                              "gold": 100, "troops": {}}])
    start["game_time_months"] = 5
    end = snap_with_lords([{"index": 0, "name": "player", "alive": True,
                            "gold": 100, "troops": {}}])
    end["game_time_months"] = 25
    spec = war_spec()
    spec.pop("duration_months")  # spec не задал: возьмём из снимков (20 мес)
    spec["sides"] = [spec["sides"][0]]  # одна сторона — как в снимках
    rep = honesty_report(start, end, spec)
    assert rep["verdict"] == "pass"
    assert rep["accounting"]["player"]["income_expected_min"] == 0.0


def test_honesty_report_json_deterministic():
    start = snap_with_lords([{"index": 0, "name": "player", "alive": True,
                              "gold": 100, "troops": {}}])
    end = snap_with_lords([{"index": 0, "name": "player", "alive": True,
                            "gold": 100, "troops": {}}])
    from sh2tw.honesty.accounting import report_json
    s1 = report_json(honesty_report(start, end, war_spec()))
    s2 = report_json(honesty_report(start, end, war_spec()))
    assert s1 == s2 and json.loads(s1)["schema_version"] == "1.0"


def test_provision_balance_on_contract_example_spec():
    """Пример 03 §3.3: провижининг сторон совпадает по стоимости → True."""
    md = (REPO / "spec" / "sh2_tz" / "03_kontrakty_dannyh.md").read_text(encoding="utf-8")
    blocks = [b.split("```")[0] for b in md.split("```json")[1:]]
    spec = json.loads(next(b for b in blocks if '"scene_id"' in b))
    # attacker: 24×30×1.0625 + 12×20 = 1005; defender: 22×20 = 440 — НЕ равно
    # (пример контракта демонстрирует форму, не баланс) → проверяем расчёт:
    det = provision_balance_detail(spec)
    assert det.sides["player"] == pytest.approx(1005.0)
    assert det.sides["l_hawk"] == pytest.approx(440.0)
    assert det.ratio == pytest.approx(1005.0 / 440.0)
    assert det.ok is False  # дисбаланс ~2.28 — честно ловится
