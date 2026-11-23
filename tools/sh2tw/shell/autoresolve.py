"""autoresolve.py — авто-резолв боёв (формула v1, 07 §7.4 — дословно).

S(сторона) = Σ count × unit_value × (1 + 0.25 × vet);
att_eff = S_att × terrain_mod;  def_eff = S_def × (1 + wall_bonus × level) ×
terrain_mod;  P(win_att) = 1/(1 + exp(−k × (att_eff − def_eff)/max)), k = 3.0.
Штурм замка без осадных юнитов → att_eff × 0.5; осадный парк ×(1+0.1×n) до
×1.5. Потери: проигравший 60–100 % стоимости (рулетка), победитель —
0.25 × S_loser стоимости; распределение пропорционально составу, ветераны
гибнут последними. Калибровка: бин {тип боя}×{терциль сил} с ≥5 живыми боями
→ P = 0.5×P_model + 0.5×P_emp. Обе силы нулевые → fallback_strongest, ничья.
"""
from __future__ import annotations

import math
import random

from ..honesty.accounting import load_unit_values

SIEGE_UNITS = ("catapult", "trebuchet", "ballista", "mangonel",
               "fireballista", "burningcart")
# Цены осадных юнитов в ref/unit_types.csv — UNKNOWN (живой замер V7c,
# задача S2.0-pending); для расчёта СИЛЫ принята константа 150 (бриф К1).
SIEGE_UNIT_VALUE = 150.0
VET_BONUS = 0.25            # ветеран: ×(1 + 0.25 × vet) (07 §7.4)
LOSER_LOSS_MIN, LOSER_LOSS_MAX = 0.6, 1.0
WINNER_LOSS_SHARE = 0.25    # победитель теряет 0.25 × S_loser стоимости
CALIBRATION_MIN_BATTLES = 5
SIEGE_NO_PARK_PENALTY = 0.5
SIEGE_PARK_BONUS_PER_UNIT = 0.1
SIEGE_PARK_BONUS_CAP = 1.5

_UNIT_VALUES: dict[str, float] | None = None


def unit_values_cached() -> dict[str, float]:
    """Реестр цен ref/unit_types.csv (ключи — нижний регистр; кэш модуля)."""
    global _UNIT_VALUES
    if _UNIT_VALUES is None:
        _UNIT_VALUES = load_unit_values()
    return _UNIT_VALUES


def unit_price(unit_id: str, unit_values: dict[str, float] | None = None) -> float:
    """Цена юнита: осадные — константа 150, прочие — из CSV (0, если нет)."""
    uv = unit_values if unit_values is not None else unit_values_cached()
    if unit_id in SIEGE_UNITS:
        return SIEGE_UNIT_VALUE
    return float(uv.get(unit_id, 0.0))


def roster_strength(roster: dict | None,
                    unit_values: dict[str, float] | None = None) -> float:
    """S(стороны) = Σ count × unit_value × (1 + 0.25 × vet)."""
    uv = unit_values if unit_values is not None else unit_values_cached()
    total = 0.0
    for unit_id, rec in (roster or {}).items():
        count = int(rec.get("count", 0))
        vet = float(rec.get("vet", 0.0) or 0.0)
        total += count * unit_price(unit_id, uv) * (1.0 + VET_BONUS * vet)
    return total


def siege_units_count(roster: dict | None) -> int:
    """Число осадных юнитов в росписи."""
    return sum(int(rec.get("count", 0)) for u, rec in (roster or {}).items()
               if u in SIEGE_UNITS)


def tercile(att_eff: float, def_eff: float) -> int:
    """Терциль соотношения сил att/def: <0.8 → 0; 0.8–1.25 → 1; >1.25 → 2."""
    if def_eff <= 0:
        return 2
    ratio = att_eff / def_eff
    if ratio < 0.8:
        return 0
    if ratio <= 1.25:
        return 1
    return 2


def battle_forecast(config: dict, attacker_roster: dict, defender_roster: dict,
                    castle_level: int, terrain_mod: float = 1.0,
                    siege_park: int | None = None,
                    unit_values: dict[str, float] | None = None) -> dict:
    """Прогноз боя без броска: силы, эффективности, P(win_att), бин."""
    uv = unit_values if unit_values is not None else unit_values_cached()
    ar = config["autoresolve"]
    s_att = roster_strength(attacker_roster, uv)
    s_def = roster_strength(defender_roster, uv)
    battle_type = "siege" if int(castle_level) >= 1 else "field"
    park = siege_units_count(attacker_roster) if siege_park is None \
        else int(siege_park)
    att_eff = s_att * float(terrain_mod)
    def_eff = s_def * (1.0 + float(ar["wall_bonus_per_castle_level"])
                       * int(castle_level)) * float(terrain_mod)
    if battle_type == "siege":
        if park <= 0:
            att_eff *= SIEGE_NO_PARK_PENALTY      # штурм без парка — штраф стен
        else:
            att_eff *= min(SIEGE_PARK_BONUS_CAP,
                           1.0 + SIEGE_PARK_BONUS_PER_UNIT * park)
    k = float(ar["logit_k"])
    denom = max(att_eff, def_eff)
    p_win = 0.5 if denom <= 0 else \
        1.0 / (1.0 + math.exp(-k * (att_eff - def_eff) / denom))
    return {"battle_type": battle_type, "s_att": s_att, "s_def": s_def,
            "att_eff": att_eff, "def_eff": def_eff, "p_win_att": p_win,
            "bin": {"battle_type": battle_type,
                    "strength_ratio_tercile": tercile(att_eff, def_eff)}}


# ------------------------------------------------------------------- потери
def _buckets(roster: dict, unit_values: dict[str, float]) -> list[list]:
    """Роспись → корзины [unit_id, is_vet, count, price_per_unit]."""
    out: list[list] = []
    for unit_id, rec in (roster or {}).items():
        count = int(rec.get("count", 0))
        vet = float(rec.get("vet", 0.0) or 0.0)
        if count <= 0:
            continue
        price = unit_price(unit_id, unit_values)
        vet_count = round(count * vet)
        if count - vet_count > 0:
            out.append([unit_id, False, count - vet_count, price])
        if vet_count > 0:
            out.append([unit_id, True, vet_count, price * (1.0 + VET_BONUS)])
    return out


def _remove_value(buckets: list[list], loss_value: float) -> None:
    """Снять loss_value стоимости: сперва обычные корзины пропорционально
    составу, затем (если не хватило) ветеранские — ветераны гибнут последними."""
    for is_vet_phase in (False, True):
        if loss_value <= 0:
            return
        phase = [b for b in buckets if b[1] == is_vet_phase and b[2] > 0]
        phase_value = sum(b[2] * b[3] for b in phase)
        if phase_value <= 0:
            continue
        if loss_value >= phase_value:      # фаза выкашивается целиком
            for b in phase:
                b[2] = 0
            loss_value -= phase_value
            continue
        for b in phase:                    # пропорционально стоимости корзин
            share = (b[2] * b[3]) / phase_value
            n = min(b[2], round(loss_value * share / b[3]))
            b[2] -= n
        return


def apply_loss_value(roster: dict, unit_values: dict[str, float],
                     loss_value: float) -> tuple[dict, dict]:
    """Применить потери стоимостью loss_value → (выжившие, потери {unit: n})."""
    buckets = _buckets(roster, unit_values)
    before = {u: int(r.get("count", 0)) for u, r in (roster or {}).items()}
    _remove_value(buckets, max(0.0, loss_value))
    survivors: dict[str, dict] = {}
    for unit_id, is_vet, count, _price in buckets:
        if count <= 0:
            continue
        rec = survivors.setdefault(unit_id, {"count": 0, "vet": 0.0})
        rec["count"] += count
        if is_vet:
            rec["vet"] = round(rec["vet"] + count, 4)  # временно: число ветеранов
    for rec in survivors.values():          # доля ветеранов среди выживших
        vets = rec["vet"]
        rec["vet"] = round(vets / rec["count"], 4) if rec["count"] else 0.0
    losses = {u: before.get(u, 0) - survivors.get(u, {"count": 0})["count"]
              for u in before}
    losses = {u: n for u, n in losses.items() if n > 0}
    return survivors, losses


# --------------------------------------------------------------------- бой
def _calibrated_p(config: dict, forecast: dict,
                  calibration: dict | None) -> tuple[float, bool]:
    """Калибровка (07 §7.4): бин с ≥5 боями подмешивает эмпирический winrate."""
    p_model = float(forecast["p_win_att"])
    if not calibration:
        return p_model, False
    bin_key = (f"{forecast['bin']['battle_type']}_"
               f"{forecast['bin']['strength_ratio_tercile']}")
    cal = calibration.get(bin_key) or {}
    battles = int(cal.get("battles", 0))
    if battles >= CALIBRATION_MIN_BATTLES:
        p_emp = float(cal.get("att_wins", 0)) / float(battles)
        return 0.5 * p_model + 0.5 * p_emp, True
    return p_model, False


def autoresolve(attacker: dict, defender: dict, cfg: dict,
                rng: random.Random,
                calibration: dict | None = None) -> dict:
    """Авто-резолв боя (07 §7.4). Контракт брифа К1:
    attacker = {lord, roster, siege_units_count?},
    defender = {lord, roster, castle_level}; rng — снаружи (детерминизм)."""
    att_lord = attacker["lord"]
    def_lord = defender["lord"]
    att_roster = attacker.get("roster") or {}
    def_roster = defender.get("roster") or {}
    castle_level = int(defender.get("castle_level", 0))
    uv = unit_values_cached()
    park = attacker.get("siege_units_count")
    forecast = battle_forecast(cfg, att_roster, def_roster, castle_level,
                               siege_park=park, unit_values=uv)
    s_att, s_def = forecast["s_att"], forecast["s_def"]
    result: dict = {
        "winner": None, "p_win_att": forecast["p_win_att"],
        "losses": {}, "survivors": {}, "bin": forecast["bin"],
        "model": "formula_v1", "warning": None, "calibrated": False}
    if s_att <= 0 and s_def <= 0:      # обе силы нулевые — ничья (fallback)
        result.update({"model": "fallback_strongest",
                       "survivors": {att_lord: dict(att_roster),
                                     def_lord: dict(def_roster)},
                       "warning": "обе стороны без силы — ничья"})
        return result
    if s_att <= 0 or s_def <= 0:       # одна сторона пуста — победа сильнейшего
        winner = def_lord if s_att <= 0 else att_lord
        loser = def_lord if winner == att_lord else att_lord
        loser_roster = att_roster if loser == att_lord else def_roster
        win_roster = def_roster if loser == att_lord else att_roster
        result.update({
            "winner": winner, "model": "fallback_strongest",
            "losses": {loser: {u: int(r.get("count", 0))
                               for u, r in loser_roster.items()
                               if int(r.get("count", 0)) > 0}},
            "survivors": {winner: dict(win_roster), loser: {}},
            "warning": f"сторона {loser} без силы — победа сильнейшего"})
        return result
    p_win, calibrated = _calibrated_p(cfg, forecast, calibration)
    result["p_win_att"] = p_win
    result["calibrated"] = calibrated
    winner = att_lord if rng.random() < p_win else def_lord
    loser = def_lord if winner == att_lord else att_lord
    s_winner, s_loser = (s_att, s_def) if winner == att_lord else (s_def, s_att)
    loser_roster = att_roster if loser == att_lord else def_roster
    win_roster = def_roster if loser == att_lord else att_roster
    loser_frac = LOSER_LOSS_MIN + (LOSER_LOSS_MAX - LOSER_LOSS_MIN) * rng.random()
    loser_surv, loser_loss = apply_loss_value(loser_roster, uv,
                                              loser_frac * s_loser)
    win_surv, win_loss = apply_loss_value(win_roster, uv,
                                          WINNER_LOSS_SHARE * s_loser)
    result.update({"winner": winner,
                   "losses": {loser: loser_loss, winner: win_loss},
                   "survivors": {winner: win_surv, loser: loser_surv}})
    return result
