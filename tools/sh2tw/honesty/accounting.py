"""accounting.py — протокол честности матча (S2.8; контракт 03 §3.9, ТЗ 04 §4.5).

Две проверки, разделённые по моменту применения:

1. provision_balance(spec) — ДО запуска сцены: стартовый провижининг сторон
   равен по стоимости ±10 % (генератор обязан вызывать, 05 §5.2).
   Стоимость провижининга стороны (единая валюта — золото, 02 §2.4):
     - канал estate_troops / invasion: Σ count × unit_value × (1 + 0.25 × vet)
       (ветеран ×1.25 к unit_value — 07 §7.7; формула выслуги — 07 §7.4);
     - канал aic_template: та же формула по garrison_roster;
     - budget_gold + budget_honour × 10 (честь конвертируется по весу
       формулы unit_value = золото + честь×10 + снаряжение×2, Прил. D).

2. honesty_report(start, end, spec) — ПОСЛЕ матча: бюджет дохода стороны
   (03 §3.9): consumption ≤ (Σ доход эстейтов × месяцы × k_trade +
   стартовое золото) × 1.10; превышение > 10 % — нарушение, матч бракуется.

Честная деградация (принцип ТЗ 00 UNKNOWN): поля lords/owner_lord в реальных
снимках сейчас null (G18/G20 — декодеров нет). Если лорды недоступны —
verdict «insufficient_data», violations пуст, причина — в поле reasons;
это НЕ нарушение. Полный расчёт работает на синтетических/будущих снимках,
где lords заполнены (контракт 03 §3.5 допускает).

Единица стоимости — unit_value из ref/unit_types.csv (Прил. D, стартовые
веса; финальные — после живых замеров V7c, задача S2.0-pending).
"""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
UNIT_TYPES_CSV = REPO_ROOT / "ref" / "unit_types.csv"

SCHEMA_VERSION = "1.0"
BALANCE_TOLERANCE = 0.10        # ±10 % (03 §3.9)
VET_BONUS = 0.25                # ветеран: ×(1+0.25×vet) (07 §7.4/§7.7)
HONOUR_TO_GOLD = 10             # unit_value = золото + честь×10 (Прил. D)
K_TRADE_DEFAULT = 1.3           # потолок торговли (03 §3.9, калибруется)
VILLAGE_TAX_GOLD = 50           # +50 золота/месяц с эстейта-деревни (G1)
BUDGET_TOLERANCE = 0.10         # потребление сверх бюджета > 10 % = нарушение
PROVISION_CHANNELS = ("estate_troops", "invasion", "war_chest", "aic_template")


class HonestyError(Exception):
    """Некорректный вход протокола честности (битый spec/снимок)."""


# ---------------------------------------------------------------- ref-данные
def load_unit_values(csv_path: Path | None = None) -> dict[str, float]:
    """ref/unit_types.csv → {unit_id: unit_value}.

    Ключи нормализуются в нижний регистр (контракты 03 используют snake_case
    ids: "archer", "spearman"; CSV хранит class_name OpenSH2: "Archer").
    Строки с unit_value=UNKNOWN (цены наёмного поста — живой замер V7c,
    задача S2.0-pending) в реестр не входят: цена неизвестна → не считаем.
    Бросает HonestyError, если пригодных строк нет (ref-контракт S2.0).
    """
    path = Path(csv_path) if csv_path else UNIT_TYPES_CSV
    if not path.exists():
        raise HonestyError(f"нет реестра юнитов: {path}")
    values: dict[str, float] = {}
    with path.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            name = (row.get("class_name") or "").strip().lower()
            raw = (row.get("unit_value") or "").strip()
            if not name or not raw or raw.upper() == "UNKNOWN":
                continue
            try:
                values[name] = float(raw)
            except ValueError:
                continue
    if not values:
        raise HonestyError(f"{path}: пустой реестр unit_value")
    return values


# ------------------------------------------------------------- росписи/цены
def roster_value(roster: dict, unit_values: dict[str, float]) -> float:
    """Стоимость росписи {тип: {count, vet}} в золоте (02 §2.4: стоимость
    росписи = Σ цена найма; ветераны ×(1+0.25×vet))."""
    total = 0.0
    for unit_type, rec in (roster or {}).items():
        if rec is None:
            continue
        count = int(rec.get("count", 0))
        vet = float(rec.get("vet", 0.0) or 0.0)
        price = unit_values.get(unit_type)
        if price is None:
            raise HonestyError(
                f"тип юнита «{unit_type}» отсутствует в ref/unit_types.csv — "
                f"цена неизвестна, стоимость не считаем (принцип 00 §0.4)")
        if count < 0 or not 0.0 <= vet <= 1.0:
            raise HonestyError(f"роспись {unit_type}: count={count}, vet={vet} вне диапазонов")
        total += count * price * (1.0 + VET_BONUS * vet)
    return total


def side_provision_value(side: dict, unit_values: dict[str, float]) -> float:
    """Стоимость стартового провижининга одной стороны scene_spec (03 §3.3)."""
    if not isinstance(side, dict):
        raise HonestyError("side spec: ожидался объект")
    prov = side.get("provision") or {}
    channel = prov.get("channel")
    if channel not in PROVISION_CHANNELS:
        raise HonestyError(f"side.provision.channel {channel!r} ∉ {PROVISION_CHANNELS}")
    value = 0.0
    roster = prov.get("roster") or prov.get("garrison_roster") or {}
    if roster:
        value += roster_value(roster, unit_values)
    budget_gold = float(side.get("budget_gold", 0) or 0)
    budget_honour = float(side.get("budget_honour", 0) or 0)
    value += budget_gold + budget_honour * HONOUR_TO_GOLD
    return value


# ------------------------------------------------------- проверка ДО матча
@dataclass
class ProvisionBalance:
    ok: bool
    sides: dict[str, float] = field(default_factory=dict)
    ratio: float | None = None
    detail: str = ""

    def as_dict(self) -> dict:
        return {"ok": self.ok, "sides": self.sides,
                "ratio": self.ratio, "detail": self.detail}


def provision_balance_detail(spec: dict,
                             unit_values: dict[str, float] | None = None,
                             tolerance: float = BALANCE_TOLERANCE) -> ProvisionBalance:
    """Полный расчёт баланса провижининга сторон (±10 % по умолчанию)."""
    uv = unit_values or load_unit_values()
    sides = spec.get("sides") or []
    if len(sides) < 2:
        raise HonestyError("spec.sides: нужно ≥2 стороны для баланса")
    values = {str(s.get("lord", s.get("role", i))): side_provision_value(s, uv)
              for i, s in enumerate(sides)}
    hi = max(values.values())
    lo = min(values.values())
    if hi == 0.0 and lo == 0.0:
        # обе стороны без провижининга (сцена без войск, только казна 0:0)
        return ProvisionBalance(True, values, 1.0, "обе стороны 0 — баланс тривиален")
    ratio = hi / lo if lo > 0 else float("inf")
    ok = ratio <= 1.0 + tolerance
    detail = (f"max={hi:.0f} min={lo:.0f} ratio={ratio:.3f} "
              f"(допуск ≤{1.0 + tolerance:.2f})")
    return ProvisionBalance(ok, values, ratio if ratio != float("inf") else None, detail)


def provision_balance(spec: dict) -> bool:
    """Сигнатура ТЗ 04 §4.5/§4.5: provision_balance(spec) -> bool."""
    return provision_balance_detail(spec).ok


# --------------------------------------------------- сопоставление лордов
def _lord_entries(snap: dict) -> list[dict]:
    lords = snap.get("lords")
    return lords if isinstance(lords, list) else []


def _match_lord(snap: dict, side: dict) -> dict | None:
    """Лорд стороны в снимке: по lord_snapshot_index (подсказка scene_client),
    затем по имени (lords[].name). Нет данных → None (честная деградация)."""
    lords = _lord_entries(snap)
    if not lords:
        return None
    idx = side.get("lord_snapshot_index")
    if isinstance(idx, int) and 0 <= idx < len(lords):
        return lords[idx]
    name = str(side.get("lord", ""))
    for entry in lords:
        if entry and entry.get("name") == name:
            return entry
    return None


def _lord_troops_value(entry: dict | None, unit_values: dict[str, float]) -> float:
    """Стоимость войск лорда из снимка: troops {тип: count} (без ветеранов —
    ветеранство ведёт оболочка, в снимке его нет)."""
    if not entry:
        return 0.0
    troops = entry.get("troops") or {}
    return roster_value({t: {"count": c, "vet": 0.0} for t, c in troops.items()
                         if isinstance(c, (int, float))}, unit_values)


def _lord_estates_income(entry: dict | None, snap: dict) -> float:
    """Доход эстейтов лорда в месяц: деревни × 50 з/мес (G1, подтверждено
    fandom). Замковые эстейты доход в месяц не документирован → 0 (не гадаем)."""
    if not entry:
        return 0.0
    idx = entry.get("index")
    income = 0.0
    for est in snap.get("estates") or []:
        if est.get("owner_lord") == idx and est.get("type") == "village":
            income += VILLAGE_TAX_GOLD
    return income


# ---------------------------------------------------- отчёт ПОСЛЕ матча
def honesty_report(start: dict, end: dict, spec: dict,
                   k_trade: float = K_TRADE_DEFAULT,
                   unit_values: dict[str, float] | None = None) -> dict:
    """Контракт 03 §3.9: {schema_version, scene_id, sides, accounting,
    verdict, violations}.

    verdict ∈ pass | fail | insufficient_data:
    - fail — потребление какой-то стороны превысило бюджет > 10 %;
    - insufficient_data — лорды в снимках не декодированы (G18) или сторона
      не найдена: расчёт невозможен, это НЕ нарушение;
    - pass — все стороны в бюджете.
    """
    uv = unit_values or load_unit_values()
    scene_id = spec.get("scene_id")
    months = spec.get("duration_months")
    if not isinstance(months, (int, float)) or months <= 0:
        # длительность из снимков (game_time_months), если spec не задал
        ta, tb = start.get("game_time_months"), end.get("game_time_months")
        if isinstance(ta, (int, float)) and isinstance(tb, (int, float)):
            months = max(1, int(tb - ta))
        else:
            months = None

    sides_out: list[dict] = []
    accounting: dict[str, dict] = {}
    violations: list[dict] = []
    reasons: list[str] = []
    data_ok = True

    for side in spec.get("sides") or []:
        lord_id = str(side.get("lord", side.get("role", "?")))
        e0 = _match_lord(start, side)
        e1 = _match_lord(end, side)
        if e0 is None or e1 is None:
            data_ok = False
            reasons.append(
                f"{lord_id}: лорд не найден в снимке "
                f"(start={'есть' if e0 else 'нет'}, end={'есть' if e1 else 'нет'}; "
                f"lords-декодер — G18, сценарий доразбора в 13 §J)")
            sides_out.append({"lord": lord_id, "t0": None, "t_end": None,
                              "provision_value": side_provision_value(side, uv)})
            continue
        t0 = {"gold": e0.get("gold"), "alive": e0.get("alive"),
              "troops_value": _lord_troops_value(e0, uv),
              "estates_income_month": _lord_estates_income(e0, start)}
        t_end = {"gold": e1.get("gold"), "alive": e1.get("alive"),
                 "troops_value": _lord_troops_value(e1, uv),
                 "estates_income_month": _lord_estates_income(e1, end)}
        sides_out.append({"lord": lord_id, "t0": t0, "t_end": t_end,
                          "provision_value": side_provision_value(side, uv)})

        if months is None:
            data_ok = False
            reasons.append(f"{lord_id}: длительность сцены неизвестна")
            continue
        gold0 = t0["gold"] if isinstance(t0["gold"], (int, float)) else None
        gold1 = t_end["gold"] if isinstance(t_end["gold"], (int, float)) else None
        if gold0 is None or gold1 is None:
            data_ok = False
            reasons.append(f"{lord_id}: золото лорда не декодировано (G18)")
            continue

        income_month = t0["estates_income_month"]
        income_expected_min = income_month * months
        income_expected_max = income_month * months * k_trade + gold0
        # наблюдаемое потребление: прирост золота + прирост стоимости войск
        # (только положительные дельты — трата золота потреблением не является)
        gold_gain = max(0.0, gold1 - gold0)
        troops_gain = max(0.0, t_end["troops_value"] - t0["troops_value"])
        consumption = gold_gain + troops_gain
        verdict_side = "ok"
        if consumption > income_expected_max * (1.0 + BUDGET_TOLERANCE):
            verdict_side = "violation"
            violations.append({
                "lord": lord_id, "consumption": round(consumption, 2),
                "budget_max": round(income_expected_max, 2),
                "excess_pct": round(
                    (consumption / income_expected_max - 1.0) * 100.0, 1)
                if income_expected_max > 0 else None,
                "note": "потребление сверх бюджета доходов > 10 % (03 §3.9)"})
        accounting[lord_id] = {
            "income_expected_min": round(income_expected_min, 2),
            "income_expected_max": round(income_expected_max, 2),
            "income_observed": round(consumption, 2),
            "verdict": verdict_side,
        }

    if violations:
        verdict = "fail"
    elif not data_ok:
        verdict = "insufficient_data"
    else:
        verdict = "pass"
    return {
        "schema_version": SCHEMA_VERSION,
        "scene_id": scene_id,
        "sides": sides_out,
        "accounting": accounting,
        "verdict": verdict,
        "violations": violations,
        "reasons": reasons,
    }


def report_json(report: dict) -> str:
    """Канонический JSON отчёта (детерминированный, как snapshot_json S2.6)."""
    return json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
