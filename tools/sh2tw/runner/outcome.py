"""outcome.py — лестница детекта исхода сцены (S3.7; ТЗ 05 §5.7 п.1–4).

Лестница каналов (07 §7.6):
  1. bridge  — файл bridge/outcome.json от d3d9-моста (трек 2, опционален);
  2. autosave_parse — snapshot итогового сейва → правила ниже;
  3. ocr     — не реализован (только при точности ≥95 % на 10 тестах V3c);
  4. manual  — ручной ввод (вечный fallback, оболочка показывает кнопки).

Правила autosave_parse (05 §5.7 п.2): win если мёртв вражеский лорд
(или ControlNumEstates ≥ цели) и жив свой; loss наоборот; неоднозначное
(оба живы/оба мертвы, тайм-аут) → draw/aborted по таймеру сцены.

Честная деградация (G18/G20): в реальных снимках lords/owner_lord = null —
правила неприменимы → канал manual с автозаполнением «нет данных»;
это не ошибка, а зафиксированное ограничение (декоды Scenario — V-вечера).
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from ..honesty.accounting import _match_lord  # внутреннее, но тот же пакет

SCHEMA_VERSION = "1.0"
OUTCOMES = ("win", "loss", "draw", "aborted")
CHANNELS = ("bridge", "autosave_parse", "ocr", "manual")


@dataclass
class OutcomeVerdict:
    outcome: str | None            # win|loss|draw|aborted|None (не определён)
    channel: str                   # канал лестницы, который дал ответ
    reason: str
    losses: dict = field(default_factory=dict)
    survivors: dict = field(default_factory=dict)
    anomalies: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"outcome": self.outcome, "channel": self.channel,
                "reason": self.reason, "losses": self.losses,
                "survivors": self.survivors, "anomalies": self.anomalies}


# ------------------------------------------------------------ канал 1: мост
def read_bridge_outcome(bridge_dir: Path) -> dict | None:
    """bridge/outcome.json от d3d9-моста (06 §6.4): {outcome, save, ts}."""
    p = Path(bridge_dir) / "outcome.json"
    if not p.exists():
        return None
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None  # мост не должен ломать конвейер (06 §6.4)
    if d.get("outcome") in ("win", "loss"):
        return d
    return None


# --------------------------------------------------- канал 2: парс автосейва
def _lord_alive(snap: dict, side: dict) -> bool | None:
    entry = _match_lord(snap, side)
    if entry is None:
        return None
    alive = entry.get("alive")
    return bool(alive) if isinstance(alive, bool) else None


def detect_outcome(start: dict, end: dict, spec: dict) -> OutcomeVerdict:
    """Правила 05 §5.7 п.2 по паре снимков + spec сторон.

    Возвращает verdict; при недостающих данных outcome=None, канал
    manual — оболочка предложит ручной ввод (кнопки Win/Loss/Draw).
    """
    sides = spec.get("sides") or []
    if len(sides) < 2:
        return OutcomeVerdict(None, "manual", "spec: <2 сторон — исход вводит человек")
    attacker = next((s for s in sides if s.get("role") == "attacker"), sides[0])
    defender = next((s for s in sides if s.get("role") == "defender"), sides[1])

    att_alive = _lord_alive(end, attacker)
    def_alive = _lord_alive(end, defender)
    if att_alive is None or def_alive is None:
        missing = []
        if att_alive is None:
            missing.append(str(attacker.get("lord", "attacker")))
        if def_alive is None:
            missing.append(str(defender.get("lord", "defender")))
        return OutcomeVerdict(
            None, "manual",
            f"lords не декодированы в снимке (G18): {', '.join(missing)} — "
            f"правила исхода неприменимы, исход вводит человек (05 §5.7 п.4)")

    if def_alive is False and att_alive is True:
        outcome = "win"       # победа атакующего (сторона спека «attacker»)
    elif att_alive is False and def_alive is True:
        outcome = "loss"
    elif att_alive is False and def_alive is False:
        outcome = "draw"
    else:
        # оба живы: тайм-аут сцены → draw (aborted — только краш, watchdog)
        outcome = "draw"
    reason = (f"attacker_alive={att_alive} defender_alive={def_alive} "
              f"(правила 05 §5.7 п.2)")
    # потери/выжившие — из войск лордов, если декодированы
    losses: dict[str, dict] = {}
    survivors: dict[str, dict] = {}
    for side in (attacker, defender):
        lid = str(side.get("lord", side.get("role", "?")))
        e0, e1 = _match_lord(start, side), _match_lord(end, side)
        if e0 is None or e1 is None:
            continue
        t0, t1 = e0.get("troops") or {}, e1.get("troops") or {}
        if isinstance(t0, dict) and isinstance(t1, dict):
            losses[lid] = {u: max(0, int(t0.get(u, 0)) - int(t1.get(u, 0)))
                           for u in t0 if int(t0.get(u, 0)) > int(t1.get(u, 0))}
            survivors[lid] = {u: {"count": int(c), "vet": 0.0}
                              for u, c in t1.items() if int(c) > 0}
    return OutcomeVerdict(outcome, "autosave_parse", reason,
                          losses=losses, survivors=survivors)


def manual_outcome(outcome: str, note: str = "ручной ввод (05 §5.7 п.4)",
                   losses: dict | None = None) -> OutcomeVerdict:
    """Канал 4: ручной ввод (всегда доступен)."""
    if outcome not in OUTCOMES:
        raise ValueError(f"outcome {outcome!r} ∉ {OUTCOMES}")
    return OutcomeVerdict(outcome, "manual", note, losses=losses or {})


# --------------------------------------------------------------- лестница
def resolve_outcome(spec: dict, bridge_dir: Path | None = None,
                    start_snapshot: dict | None = None,
                    end_snapshot: dict | None = None,
                    manual_choice: str | None = None) -> OutcomeVerdict:
    """Полная лестница каналов: bridge → autosave_parse → manual.

    manual_choice — выбор человека (если передан, применяется после
    безуспешных каналов 1–2; это и есть экран «Исход?» 07 §7.6).
    """
    if bridge_dir is not None:
        bridged = read_bridge_outcome(bridge_dir)
        if bridged is not None:
            return OutcomeVerdict(bridged["outcome"], "bridge",
                                  f"мост: {bridged}",
                                  anomalies=[])
    if start_snapshot is not None and end_snapshot is not None:
        verdict = detect_outcome(start_snapshot, end_snapshot, spec)
        if verdict.outcome is not None:
            return verdict
        if manual_choice is None:
            return verdict  # manual_required — человек ещё не выбрал
    if manual_choice is not None:
        return manual_outcome(manual_choice)
    return OutcomeVerdict(None, "manual", "нет данных каналов 1–2, ручной ввод "
                                          "не передан")


# ------------------------------------------------------- scene_result (03 §3.4)
def build_scene_result(scene_id: str, verdict: OutcomeVerdict,
                       duration_real_min: float | None = None,
                       captures: list[str] | None = None,
                       honour_delta: int = 0,
                       development_damage: dict | None = None,
                       snapshot_end: str | None = None,
                       honesty: dict | None = None) -> dict:
    """Контракт 03 §3.4 scene_result.json из вердикта раннера."""
    result = {
        "schema_version": SCHEMA_VERSION,
        "scene_id": scene_id,
        "outcome": verdict.outcome,
        "outcome_channel": verdict.channel,
        "duration_real_min": duration_real_min,
        "losses": verdict.losses,
        "survivors": verdict.survivors,
        "captures": captures or [],
        "honour_delta": honour_delta,
        "development_damage": development_damage or {},
        "snapshot_end": snapshot_end,
        "honesty": honesty or {"pass": None, "report": None},
        "anomalies": verdict.anomalies,
        "reason": verdict.reason,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    return result
