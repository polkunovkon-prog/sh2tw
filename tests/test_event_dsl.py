"""Golden-тесты DSL событий (S3.4; 05 §5.4/§5.9: пары «spec → байты»).

Байтовый слой ScenarioEvent — UNKNOWN(G18, живые hexdiff'ы V8/V9), поэтому
golden здесь — канонический IR: детерминированный JSON записи. Структура
тестов повторяет будущие пары «spec → байты»: вход DSL фиксирован, выход
сравнивается побайтно (строка JSON) с эталоном.
"""
from __future__ import annotations

import json

import pytest

from sh2tw.scenes.event_dsl import (
    ACTIONS,
    TRIGGERS,
    EventDslError,
    compile_events,
    compile_record,
    scene_events,
)

# ------------------------------------------------------------- golden IR
GOLDEN_TIMER = {
    "mission_events": [
        {"after_months": 2, "action": "Invasion", "params": {
            "owner": "player", "from_marker": 1, "attack_marker": 2,
            "troops": {"archer": 24, "spearman": 12}, "repeat": False}},
    ],
}
GOLDEN_TIMER_IR = {
    "records": [
        {"record_id": "me_000",
         "trigger": {"type": "Always", "params": {}, "after_months": 2},
         "actions": [{"action": "Invasion", "params": {
             "owner": "player", "from_marker": 1, "attack_marker": 2,
             "troops": {"archer": 24, "spearman": 12}, "repeat": False}}]},
    ],
}


def test_golden_timer_invasion_ir():
    prog = compile_events(GOLDEN_TIMER["mission_events"])
    assert prog.as_dict()["records"] == GOLDEN_TIMER_IR["records"]
    # побайтовая стабильность canonical JSON (golden)
    assert prog.json() == json.dumps(prog.as_dict(), ensure_ascii=False,
                                     indent=2, sort_keys=True)


GOLDEN_TRIGWIN = [
    {"trigger": {"type": "EnemyLordDead", "params": {"lord": "l_hawk"}},
     "actions": [{"action": "Win"}]},
    {"trigger": {"type": "LordDies", "params": {"lord": "player"}},
     "actions": [{"action": "Lose"}]},
]


def test_golden_trigger_win_lose_ir():
    prog = compile_events(GOLDEN_TRIGWIN)
    assert [r["trigger"]["type"] for r in prog.records] == ["EnemyLordDead", "LordDies"]
    assert prog.records[0]["actions"] == [{"action": "Win", "params": {}}]
    assert prog.records[1]["actions"] == [{"action": "Lose", "params": {}}]
    assert prog.summary() == {"records": 2, "actions": {"Lose": 1, "Win": 1}}


def test_contract_03_scene_spec_example_compiles():
    """Пример mission_events из контракта 03 §3.3 — компилируется целиком."""
    events = [
        {"after_months": 1, "action": "ControlLordsAI",
         "params": {"lords": ["l_hawk"], "enabled": True}},
        {"after_months": 2, "action": "Invasion", "params": {
            "owner": "player", "from_marker": 1, "attack_marker": 2,
            "troops": {"archer": 24, "spearman": 12}, "repeat": False}},
        {"trigger": {"type": "EnemyLordDead", "params": {"lord": "l_hawk"}},
         "actions": [{"action": "Win"}]},
        {"trigger": {"type": "LordDies", "params": {"lord": "player"}},
         "actions": [{"action": "Lose"}]},
    ]
    prog = compile_events(events)
    assert prog.summary() == {"records": 4,
                              "actions": {"ControlLordsAI": 1, "Invasion": 1,
                                          "Lose": 1, "Win": 1}}


# ------------------------------------------------------------- отклонения
@pytest.mark.parametrize("bad,match", [
    ({"trigger": {}, "actions": []}, "форм|trigger|type"),
    ({"after_months": 1, "action": "NukeEveryone", "params": {}}, "не в подтверждённом"),
    ({"after_months": 1, "action": "Invasion", "params": {}}, "обязательный"),
    ({"after_months": 1, "action": "Invasion",
      "params": {"owner": "player", "from_marker": 99, "troops": {}}},
     "маркер 99"),
    ({"after_months": 1, "action": "Invasion",
      "params": {"owner": "player", "from_marker": 1, "troops": {"archer": 100000}}},
     "0..500"),
    ({"after_months": 1, "action": "Invasion",
      "params": {"owner": "PLAYER!", "from_marker": 1, "troops": {"archer": 5}}},
     "snake_case"),
    ({"trigger": {"type": "PlayerKillsLordX", "params": {}},
      "actions": [{"action": "Win"}]}, "не в подтверждённом списке"),
    ({"trigger": {"type": "EnemyLordDead", "params": {"lord": "x"}},
      "actions": []}, "непустой список"),
    ({"after_months": 1, "action": "GiveGold",
      "params": {"lord": "player", "gold": -5}}, "целое ≥ 0"),
    ({"after_months": 1, "action": "GiveGold",
      "params": {"lord": "player", "gold": 100, "extra": 1}}, "неизвестные"),
    ({"trigger": {"type": "EnemyLordDead", "params": {"lord": "x"}},
     "actions": [{"action": "Win"}], "after_months": 3}, "не смешивается"),
])
def test_dsl_rejects_bad_input(bad, match):
    with pytest.raises(EventDslError, match=match):
        compile_record(bad, 0)


def test_kill_triggers_forbidden_until_enums_v8():
    """13 §C: триггеры убийств с парами лордов запрещены до таблиц V8."""
    assert "PlayerKillsLordX" not in TRIGGERS
    assert "SpecificLordKillsLordX" not in TRIGGERS


def test_timeuntilfinalinvasion_immediate_setting():
    """Таблица 05 §5.4: TimeUntilFinalInvasion — немедленная настройка
    тайм-аута (без after_months) → компилируется как Always@0."""
    rec = compile_record({"action": "TimeUntilFinalInvasion",
                          "params": {"months": 40}}, 0)
    assert rec["trigger"] == {"type": "Always", "params": {}, "after_months": 0}
    assert rec["actions"] == [{"action": "TimeUntilFinalInvasion",
                               "params": {"months": 40}}]


# -------------------------------------------------------- шаблоны сцен
def sides_pair() -> list[dict]:
    return [
        {"role": "attacker", "lord": "player", "is_human": True},
        {"role": "defender", "lord": "l_hawk", "is_human": False},
    ]


def test_scene_events_siege_win_lose_and_waves():
    waves = [{"after_months": 14, "troops": {"swordsman": 18, "archer": 12}},
             {"after_months": 22, "troops": {"swordsman": 12, "crossbowman": 8}}]
    events = scene_events("siege", sides_pair(), 40, invasion_plan=waves)
    prog = compile_events(events)  # шаблон сам валиден
    kinds = [a["action"] for r in prog.records for a in r["actions"]]
    assert kinds.count("Invasion") == 2
    assert "Win" in kinds and "Lose" in kinds
    assert "TimeUntilFinalInvasion" in kinds
    # волна 1: таймер Always@14, owner=атакующий
    inv1 = next(r for r in prog.records
                if r["trigger"].get("after_months") == 14
                and r["actions"][0]["action"] == "Invasion")
    assert inv1["actions"][0]["params"]["owner"] == "player"


def test_scene_events_defense_reversed_win_lose():
    events = scene_events("defense", sides_pair(), 30)
    prog = compile_events(events)
    win = next(r for r in prog.records if "Win" in
               [a["action"] for a in r["actions"]])
    lose = next(r for r in prog.records if "Lose" in
                [a["action"] for a in r["actions"]])
    assert win["trigger"]["params"]["lord"] == "player"   # победа = смерть атакующего
    assert lose["trigger"]["params"]["lord"] == "l_hawk"  # поражение = своя смерть


def test_scene_events_development_peaceful():
    sides = sides_pair() + [{"role": "neighbor", "lord": "l_ox", "is_human": False}]
    events = scene_events("development", sides, 30)
    prog = compile_events(events)
    kinds = [a["action"] for r in prog.records for a in r["actions"]]
    assert "PauseSieges" in kinds
    ctrl = next(r for r in prog.records
                if any(a["action"] == "ControlLordsAI" for a in r["actions"]))
    ai_lords = ctrl["actions"][0]["params"]["lords"]
    assert ai_lords == ["l_hawk", "l_ox"]  # только ИИ, не игрок (B4)


def test_scene_events_rejects_unknown_type():
    with pytest.raises(EventDslError):
        scene_events("skirmish", sides_pair(), 30)
