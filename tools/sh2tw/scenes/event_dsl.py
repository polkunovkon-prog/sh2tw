"""event_dsl.py — компилятор mission_events → записи ScenarioEvent (S3.4).

Вход — DSL scene_spec.map_header_overrides.mission_events (03 §3.3):

  {"after_months": N, "action": "Invasion", params}            — таймер старта
  {"trigger": {"type": T, "params": {...}}, "actions": [...]}   — триггер+цепочка

Поддерживаемый минимум — таблица 05 §5.4 (действия) + Приложения A/B (13):
имена триггеров/действий сверяются с подтверждёнными списками sd2
(проверено 23.11.2026, реестр F6); неизвестное имя — EventDslError,
никаких «близких» автоподстановок (антигаллюцинационный протокол 00 §0.4).

Выход — канонический IR записи ScenarioEvent:
  {"record_id", "trigger", "actions": [...]} — детерминированный JSON
  (golden-тесты пар «spec → IR»).

БАЙТОВОЕ кодирование записей ScenarioEvent — UNKNOWN(G18: дока OpenSH2
расходится с payload'ами exe 2020-11-04; кодирование ID — живые hexdiff'ы
V8/V9, процедура 05 §5.4). IR стабильна: когда hexdiff'ы закроют формат,
компилятор дополнится emits-функцией без смены входа. Компиляция в байты
СЕЙЧАС возможна только через якорные патчи манифеста шаблона (L1):
поле patch_manifest в IR ссылается на патч-библиотеку S3.3.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

SCHEMA_VERSION = "1.0"
MAX_MONTHS = 600          # 50 игровых лет — потолок таймеров сцены
MAX_TROOPS_PER_TYPE = 500  # лимит юнитов на сторону ~550 (G6), росписи ≤200
MARKER_MIN, MARKER_MAX = 1, 8  # маркеры-баннеры 1–8 (05 §5.4)

# Подтверждённые действия (Прил. B, sd2 23.11.2026). Ключ — DSL-имя.
ACTIONS: dict[str, dict] = {
    # имя: {params-схема: {ключ: (тип-проверка, обязателен)}}
    # типы: int, nonneg_int (>=0), float01, bool, str, marker, lord_ref,
    # lord_list, troops
    "Win": {"params": {}},
    "Lose": {"params": {}},
    "Invasion": {"params": {
        "owner": ("lord_ref", True), "from_marker": ("marker", True),
        "attack_marker": ("marker", False), "troops": ("troops", True),
        "repeat": ("bool", False)}},
    "StopInvasions": {"params": {"owner": ("lord_ref", False)}},
    "ControlLordsAI": {"params": {"lords": ("lord_list", True),
                                  "enabled": ("bool", True)}},
    "PauseSieges": {"params": {"enabled": ("bool", False)}},
    "TakeEnemyCastle": {"params": {"lord": ("lord_ref", False)}},
    "ConvertEstateToVillage": {"params": {"estate": ("nonneg_int", False)}},
    "GiveGold": {"params": {"lord": ("lord_ref", True),
                             "gold": ("nonneg_int", True)}},
    "GiveResources": {"params": {"lord": ("lord_ref", True),
                                 "resource": ("str", True),
                                 "amount": ("nonneg_int", True)}},
    "GiveHonour": {"params": {"lord": ("lord_ref", True),
                              "honour": ("nonneg_int", True)}},
    "SetAllies": {"params": {"lords": ("lord_list", True)}},
    "TimeUntilFinalInvasion": {"params": {"months": ("nonneg_int", True)}},
    "MaxOutPeasants": {"params": {"lord": ("lord_ref", False)}},
    "SetRank": {"params": {"lord": ("lord_ref", True),
                            "rank": ("nonneg_int", True)}},
    "AITroopRetreat": {"params": {"threshold": ("float01", False)}},
    "SuperAggressiveTroops": {"params": {"enabled": ("bool", False)}},
    "BadWeather": {"params": {}},
    "BumperHarvest": {"params": {}},
}

# Подтверждённые триггеры (Прил. A, sd2 23.11.2026) — проектный минимум.
TRIGGERS: dict[str, dict] = {
    "Always": {"params": {}},
    "EnemyLordDead": {"params": {"lord": ("lord_ref", True)}},
    "LordDies": {"params": {"lord": ("lord_ref", True)}},
    "ControlNumEstates": {"params": {"n": ("nonneg_int", True)}},
    "NoEnemyOrInvasionsLeft": {"params": {}},
    "NoEnemyOnMap": {"params": {}},
    "NoEnemyTroopsOnMap": {"params": {}},
    "AllYourTroopsDead": {"params": {}},
    "GoldAcquired": {"params": {"gold": ("nonneg_int", True)}},
    "HonourAcquired": {"params": {"honour": ("nonneg_int", True)}},
    "PopulationReached": {"params": {"population": ("nonneg_int", True)}},
    "PercentTroopsKilled": {"params": {"percent": ("nonneg_int", True)}},
    "MultipleLordsDead": {"params": {}},
}

# ВАЖНО (13 §C): триггеры убийств с конкретными парами лордов
# (PlayerKillsLordX и др.) — ТОЛЬКО через таблицы ref/enums (V8): в DSL они
# НЕ включены до заполнения таблиц (запрет ТЗ 13 §C).
_LORD_REF_RE = re.compile(r"^[a-z][a-z0-9_]*$")  # snake_case ASCII (03 §0.5)


class EventDslError(Exception):
    """Некорректный mission_events DSL: описание в сообщении."""


# --------------------------------------------------------------- проверки
def _check_param(kind: str, value, where: str):
    if kind == "int":
        if not isinstance(value, int) or isinstance(value, bool):
            raise EventDslError(f"{where}: ожидалось целое, факт {value!r}")
        return value
    if kind == "nonneg_int":
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise EventDslError(f"{where}: ожидалось целое ≥ 0, факт {value!r}")
        return value
    if kind == "float01":
        if not isinstance(value, (int, float)) or not 0.0 <= float(value) <= 1.0:
            raise EventDslError(f"{where}: ожидалось число 0..1, факт {value!r}")
        return float(value)
    if kind == "bool":
        if not isinstance(value, bool):
            raise EventDslError(f"{where}: ожидалось true/false, факт {value!r}")
        return value
    if kind == "str":
        if not isinstance(value, str) or not value:
            raise EventDslError(f"{where}: ожидалась непустая строка")
        return value
    if kind == "marker":
        if not isinstance(value, int) or not MARKER_MIN <= value <= MARKER_MAX:
            raise EventDslError(
                f"{where}: маркер {value!r} вне {MARKER_MIN}..{MARKER_MAX} (05 §5.4)")
        return value
    if kind == "lord_ref":
        if not isinstance(value, str) or not _LORD_REF_RE.match(value):
            raise EventDslError(
                f"{where}: ссылка на лорда {value!r} не snake_case ASCII (03 §0.5)")
        return value
    if kind == "lord_list":
        if not isinstance(value, list) or not value:
            raise EventDslError(f"{where}: ожидался непустой список лордов")
        for v in value:
            _check_param("lord_ref", v, where)
        return value
    if kind == "troops":
        if not isinstance(value, dict) or not value:
            raise EventDslError(f"{where}: ожидалась роспись войск {{тип: число}}")
        for utype, count in value.items():
            if not isinstance(utype, str) or not _LORD_REF_RE.match(utype):
                raise EventDslError(f"{where}: тип юнита {utype!r} не snake_case")
            if not isinstance(count, int) or count < 0 or count > MAX_TROOPS_PER_TYPE:
                raise EventDslError(
                    f"{where}: число юнитов {count!r} вне 0..{MAX_TROOPS_PER_TYPE} (G6)")
        return value
    raise EventDslError(f"{where}: неизвестный тип параметра {kind}")  # pragma: no cover


def _validate_action(action: dict, where: str) -> dict:
    if not isinstance(action, dict):
        raise EventDslError(f"{where}: действие — объект")
    name = action.get("action")
    if name not in ACTIONS:
        raise EventDslError(
            f"{where}: действие {name!r} не в подтверждённом списке (05 §5.4, "
            f"Прил. B). Доступны: {', '.join(sorted(ACTIONS))}")
    schema = ACTIONS[name]["params"]
    params_in = action.get("params") or {}
    if not isinstance(params_in, dict):
        raise EventDslError(f"{where}.params: ожидался объект")
    unknown = set(params_in) - set(schema)
    if unknown:
        raise EventDslError(f"{where}.params: неизвестные ключи {sorted(unknown)} "
                            f"для {name} (антигаллюцинационный протокол)")
    params_out: dict = {}
    for key, (kind, required) in schema.items():
        pw = f"{where}.params.{key}"
        if key not in params_in:
            if required:
                raise EventDslError(f"{pw}: обязательный параметр {name}")
            continue
        params_out[key] = _check_param(kind, params_in[key], pw)
    # запретил бы и пустой params при обязательных — уже покрыто выше
    return {"action": name, "params": params_out}


def compile_record(event: dict, index: int) -> dict:
    """Один элемент DSL → каноническая IR-запись ScenarioEvent.

    Форма 1: {"after_months": N, "action": A, "params": {...}} — отложенное
    действие (нативно Always + тайминг, 05 §5.4).
    Форма 1b: {"action": A, "params": {...}} — немедленное действие старта
    сцены (after_months = 0): PauseSieges, TimeUntilFinalInvasion и др.
    (таблица 05 §5.4 перечисляет их без таймера).
    Форма 2: {"trigger": {...}, "actions": [A, ...]} — триггер и цепочка.
    """
    where = f"mission_events[{index}]"
    if not isinstance(event, dict):
        raise EventDslError(f"{where}: элемент DSL — объект")
    has_timer = "after_months" in event
    has_trigger = "trigger" in event
    has_action = "action" in event
    if has_trigger and (has_timer or has_action):
        raise EventDslError(
            f"{where}: форма «trigger+actions» не смешивается с "
            f"after_months/action (05 §5.4)")
    if not has_trigger and not has_action:
        raise EventDslError(
            f"{where}: нужна форма {{after_months, action, params}} / "
            f"{{action, params}} ИЛИ {{trigger, actions}} (05 §5.4)")

    if has_action:
        months = 0
        if has_timer:
            months = _check_param("nonneg_int", event["after_months"],
                                  f"{where}.after_months")
            if months > MAX_MONTHS:
                raise EventDslError(
                    f"{where}.after_months: {months} вне 0..{MAX_MONTHS}")
        action = _validate_action(event, where)
        return {
            "record_id": f"me_{index:03d}",
            "trigger": {"type": "Always", "params": {},
                        "after_months": months},
            "actions": [action],
        }

    trig_in = event["trigger"]
    if not isinstance(trig_in, dict) or "type" not in trig_in:
        raise EventDslError(f"{where}.trigger: {{type, params}}")
    ttype = trig_in["type"]
    if ttype not in TRIGGERS:
        raise EventDslError(
            f"{where}.trigger.type: {ttype!r} не в подтверждённом списке "
            f"(Прил. A). Доступны: {', '.join(sorted(TRIGGERS))}")
    tschema = TRIGGERS[ttype]["params"]
    tp_in = trig_in.get("params") or {}
    if not isinstance(tp_in, dict):
        raise EventDslError(f"{where}.trigger.params: ожидался объект")
    unknown = set(tp_in) - set(tschema)
    if unknown:
        raise EventDslError(f"{where}.trigger.params: неизвестные {sorted(unknown)} "
                            f"для {ttype}")
    tp_out: dict = {}
    for key, (kind, required) in tschema.items():
        pw = f"{where}.trigger.params.{key}"
        if key not in tp_in:
            if required:
                raise EventDslError(f"{pw}: обязательный параметр {ttype}")
            continue
        tp_out[key] = _check_param(kind, tp_in[key], pw)
    actions_in = event.get("actions")
    if not isinstance(actions_in, list) or not actions_in:
        raise EventDslError(f"{where}.actions: непустой список действий")
    actions = [_validate_action(a, f"{where}.actions[{i}]")
               for i, a in enumerate(actions_in)]
    return {"record_id": f"me_{index:03d}",
            "trigger": {"type": ttype, "params": tp_out},
            "actions": actions}


@dataclass
class EventProgram:
    """Скомпилированный набор записей сцены."""
    records: list[dict]

    def as_dict(self) -> dict:
        return {"schema_version": SCHEMA_VERSION, "records": self.records}

    def json(self) -> str:
        return json.dumps(self.as_dict(), ensure_ascii=False, indent=2,
                          sort_keys=True)

    def summary(self) -> dict:
        by_action: dict[str, int] = {}
        for r in self.records:
            for a in r["actions"]:
                by_action[a["action"]] = by_action.get(a["action"], 0) + 1
        return {"records": len(self.records), "actions": dict(sorted(by_action.items()))}


def compile_events(mission_events: list) -> EventProgram:
    """Список DSL-элементов → EventProgram (валидация + канонизация)."""
    if not isinstance(mission_events, list):
        raise EventDslError("mission_events: ожидался список")
    return EventProgram([compile_record(e, i) for i, e in enumerate(mission_events)])


# ------------------------------------------------------- шаблоны сцен (05 §5.4)
def scene_events(scene_type: str, sides: list[dict],
                 duration_months: int = 40,
                 invasion_plan: list[dict] | None = None) -> list[dict]:
    """Стандартный набор mission_events для типа сцены (основа S3.8).

    scene_type ∈ field | siege | defense | development (03 §3.3):
    - field/siege: победа = смерть лорда-обороняющегося (EnemyLordDead),
      поражение = смерть лорда игрока (LordDies); атакующие волны —
      invasion_plan (хореография доктрины, 08 §8.4);
    - defense: наоборот (игрок обороняется);
    - development: мирная сцена — PauseSieges, ControlLordsAI на ИИ-соседей,
      мягкий конец TimeUntilFinalInvasion (B4: границы по таймеру).
    """
    if scene_type not in ("field", "siege", "defense", "development"):
        raise EventDslError(f"тип сцены {scene_type!r} ∉ 4 известных (03 §3.3)")
    if not isinstance(sides, list) or len(sides) < 2:
        raise EventDslError("sides: нужны ≥2 стороны")
    if not 0 <= duration_months <= MAX_MONTHS:
        raise EventDslError(f"duration_months {duration_months} вне 0..{MAX_MONTHS}")

    def lord(side: dict) -> str:
        return str(side.get("lord") or "")

    attacker = next((s for s in sides if s.get("role") == "attacker"), sides[0])
    defender = next((s for s in sides if s.get("role") == "defender"), sides[1])
    events: list[dict] = []

    if scene_type in ("field", "siege"):
        events.append({"after_months": 1, "action": "ControlLordsAI",
                       "params": {"lords": [lord(defender)],
                                  "enabled": defender.get("is_human") is not True}})
        events.append({"trigger": {"type": "EnemyLordDead",
                                   "params": {"lord": lord(defender)}},
                       "actions": [{"action": "Win"}]})
        events.append({"trigger": {"type": "LordDies",
                                   "params": {"lord": lord(attacker)}},
                       "actions": [{"action": "Lose"}]})
        events.append({"action": "TimeUntilFinalInvasion",
                       "params": {"months": duration_months}})
        # хореография вторжений атакующего (канал B, 02 §2.4)
        for wave in invasion_plan or []:
            events.append({"after_months": int(wave.get("after_months", 0)),
                           "action": "Invasion",
                           "params": {"owner": lord(attacker),
                                      "from_marker": int(wave.get("from_marker", 1)),
                                      "attack_marker": int(wave.get("attack_marker", 2)),
                                      "troops": dict(wave.get("troops") or {}),
                                      "repeat": bool(wave.get("repeat", False))}})
    elif scene_type == "defense":
        events.append({"after_months": 1, "action": "ControlLordsAI",
                       "params": {"lords": [lord(attacker)], "enabled": True}})
        events.append({"trigger": {"type": "EnemyLordDead",
                                   "params": {"lord": lord(attacker)}},
                       "actions": [{"action": "Win"}]})
        events.append({"trigger": {"type": "LordDies",
                                   "params": {"lord": lord(defender)}},
                       "actions": [{"action": "Lose"}]})
        events.append({"action": "TimeUntilFinalInvasion",
                       "params": {"months": duration_months}})
        for wave in invasion_plan or []:
            events.append({"after_months": int(wave.get("after_months", 0)),
                           "action": "Invasion",
                           "params": {"owner": lord(attacker),
                                      "from_marker": int(wave.get("from_marker", 1)),
                                      "attack_marker": int(wave.get("attack_marker", 2)),
                                      "troops": dict(wave.get("troops") or {}),
                                      "repeat": bool(wave.get("repeat", False))}})
    else:  # development — театр/развитие (02 §2.6)
        ai_lords = [lord(s) for s in sides if not s.get("is_human")]
        if ai_lords:
            events.append({"after_months": 0, "action": "ControlLordsAI",
                           "params": {"lords": ai_lords, "enabled": True}})
        events.append({"action": "PauseSieges", "params": {"enabled": True}})
        events.append({"action": "TimeUntilFinalInvasion",
                       "params": {"months": duration_months}})
    return events
