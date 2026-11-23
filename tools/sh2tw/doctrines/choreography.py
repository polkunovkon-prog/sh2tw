"""choreography.py — хореография вторжений: план волн под mission_events-DSL (S5.4).

Выход invasion_plan — список элементов двух видов:
- волны {"after_months", "troops", "from_marker", "attack_marker",
  "repeat"} — совместимы с scenes/event_dsl.py (scene_events(...,
  invasion_plan=...) и конвертация в Invasion-события);
- спец-события немедленной формы {"action", "params"} — AITroopRetreat,
  SuperAggressiveTroops (форма 1b DSL, 05 §5.4).
"""
from __future__ import annotations

import random

from .archetypes import ARCHETYPES, DoctrineError

# Пулы состава (08 §8.4); имена — snake_case-формы подтверждённых классов
# ref/unit_types.csv (Spearman/Maceman/Pikeman/Swordsman/Archer/Crossbowman).
MELEE_POOL = ("spearman", "maceman", "pikeman", "swordsman")
RANGED_POOL = ("archer", "crossbowman")

# Осадные юниты в troops — «просто типы в войск» (S5.4). Подтверждённое
# имя — catapult (ref/unit_types.csv: Catapult; бриф: «catapult 1–2»).
# # UNKNOWN(игровые имена ram/tower/ladders для DSL Invasion не
# # подтверждены — в troops не подмешиваем).
SIEGE_TROOP_TYPES = {"siege_catapult": "catapult"}

_FEINT_LEAD_MONTHS = 2  # отвлекающая волна на 2 мес раньше первой (08 §8.3)


def _profile(archetype_id: str) -> dict:
    """Профиль архетипа; неизвестный id — DoctrineError."""
    prof = ARCHETYPES.get(archetype_id)
    if prof is None:
        raise DoctrineError(
            f"неизвестный архетип {archetype_id!r}; доступны: "
            f"{', '.join(sorted(ARCHETYPES))} (08 §8.4)")
    return prof


def _iclamp(v, lo: int, hi: int) -> int:
    """Целое с защитным клампом в диапазон 08 §8.3."""
    return max(lo, min(hi, int(v)))


def _split_units(total: int, pool: tuple[str, ...],
                 rng: random.Random | None, salt: int) -> dict[str, int]:
    """Разложить total юнитов по 1–3 типам пула; счётчики целые ≥ 1."""
    if total <= 0:
        return {}
    want = 3 if total >= 16 else (2 if total >= 8 else 1)
    k = min(want, len(pool), total)
    if rng is not None:
        types = sorted(rng.sample(list(pool), k))
    else:  # без rng — детерминированный поворот пула по номеру волны
        start = salt % len(pool)
        types = [pool[(start + i) % len(pool)] for i in range(k)]
    base, rem = divmod(total, k)
    return {u: base + (1 if i < rem else 0) for i, u in enumerate(types)}


def _wave_troops(size: int, melee_share: float, ranged_share: float,
                 rng: random.Random | None, salt: int) -> dict[str, int]:
    """Состав волны: доли melee/ranged нормируются на их сумму (08 §8.3)."""
    total_share = melee_share + ranged_share
    if total_share <= 0:
        melee, ranged = size, 0
    else:
        melee = max(1, round(size * melee_share / total_share))
        ranged = max(0, size - melee)
    if ranged_share > 0 and melee > 1:
        ranged = max(1, ranged)
        melee = size - ranged
    troops = _split_units(melee, MELEE_POOL, rng, salt)
    troops.update(_split_units(ranged, RANGED_POOL, rng, salt))
    return troops


def invasion_plan(archetype_id: str, genome: dict | None = None,
                  rng: random.Random | None = None) -> list[dict]:
    """План вторжений архетипа (дефолты профиля) с опциональным геномом.

    Геном управляет: first_attack_month, wave_count, wave_gap_months,
    wave_size_base, composition_melee_share/composition_ranged_share
    (нормируются на сумму), feint_enabled+feint_ratio, retreat_threshold,
    super_aggressive, siege_catapult (в первую основную волну). Без генома —
    дефолты профиля. Все числа целые; детерминизм при rng с сидом.
    """
    prof = _profile(archetype_id)
    g = genome or {}
    first = _iclamp(g.get("first_attack_month", prof["first_attack_month"]), 6, 30)
    wave_count = _iclamp(g.get("wave_count", prof["wave_count"]), 1, 5)
    gap = _iclamp(g.get("wave_gap_months", prof["wave_gap_months"]), 2, 10)
    size = _iclamp(g.get("wave_size_base", prof["wave_size_base"]), 8, 40)
    melee_share = float(g.get("composition_melee_share", prof["melee_share"]))
    ranged_share = float(g.get("composition_ranged_share", prof["ranged_share"]))
    catapults = int(g.get("siege_catapult",
                          prof["siege_mix"].get("catapult", 0)))

    waves: list[dict] = []
    for i in range(wave_count):
        troops = _wave_troops(size, melee_share, ranged_share, rng, i)
        if i == 0 and catapults > 0:
            # осадник: первая волна + осадные юниты в troops (S5.4)
            troops["catapult"] = catapults
        waves.append({
            "after_months": first + i * gap,
            "troops": troops,
            "from_marker": 1,
            "attack_marker": 2,
            "repeat": False,
        })

    plan: list[dict] = []
    if bool(g.get("feint_enabled", False)):
        ratio = float(g.get("feint_ratio", 0.2))
        feint_size = max(1, round(size * ratio))
        plan.append({
            "after_months": max(1, first - _FEINT_LEAD_MONTHS),
            "troops": _wave_troops(feint_size, melee_share, ranged_share,
                                   rng, wave_count),
            "from_marker": 1,
            "attack_marker": 2,
            "repeat": False,
        })
    plan.extend(waves)

    # спец-события — немедленная форма DSL ({"action","params"}), S5.4
    if g.get("retreat_threshold") is not None:
        threshold = min(0.6, max(0.2, float(g["retreat_threshold"])))
        plan.append({"action": "AITroopRetreat",
                     "params": {"threshold": round(threshold, 6)}})
    if bool(g.get("super_aggressive", False)):
        plan.append({"action": "SuperAggressiveTroops",
                     "params": {"enabled": True}})
    return plan
