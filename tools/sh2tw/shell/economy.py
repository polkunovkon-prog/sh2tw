"""economy.py — экономика кампании (07 §7.10): один код для игрока и ИИ.

Доход региона — за СЕЗОН (сезон = 12/seasons_per_year месяцев, по умолчанию 3):
castle-регион = base_income × (1 + 0.1 если есть product) × месяцы
              + деревни-соседи того же владельца × village_tax × месяцы;
минус содержание гарнизона Σ count × army_upkeep_gold_per_unit_month × месяцы
(суровая зима: содержание ×2). Деревня приносит свой base_income × месяцы.
Штрафы событий (state.regions[rid].income_penalty, например 0.5 при неурожае)
умножают валовой доход; сбрасываются на SEASON_START следующего сезона.
"""
from __future__ import annotations

from . import state as st

PRODUCT_BONUS_SHARE = 0.10   # castle-регион с product: +10 % base_income


def region_income(state: dict, config: dict, region_id: str) -> int:
    """Чистый доход региона за сезон (07 §7.10); int золота."""
    rc = st.region_config(config, region_id)
    rs = (state.get("regions") or {}).get(region_id) or {}
    eco = config["economy"]
    months = st.months_per_season(config)
    gross = float(rc.get("base_income", 0) or 0)
    if rc["type"] == "castle" and rc.get("product"):
        gross *= 1.0 + PRODUCT_BONUS_SHARE
    if rc["type"] == "castle":
        gross += _neighbor_village_tax(state, config, region_id)
    penalty = rs.get("income_penalty")
    if penalty is not None:                 # событие сезона (harvest_failure…)
        gross *= float(penalty)
    upkeep = _upkeep(rs.get("garrison"), eco, state, months)
    return int(round(gross * months - upkeep))


def _neighbor_village_tax(state: dict, config: dict, region_id: str) -> float:
    """Деревни-соседи того же владельца: village_tax_gold_per_month каждая."""
    rc = st.region_config(config, region_id)
    owner = (state["regions"].get(region_id) or {}).get("owner")
    if not owner:
        return 0.0
    tax = float(config["economy"]["village_tax_gold_per_month"])
    total = 0.0
    for nb in rc.get("neighbors") or []:
        nrc = st.region_config(config, nb)
        if nrc["type"] != "village":
            continue
        if (state["regions"].get(nb) or {}).get("owner") == owner:
            total += tax
    return total


def _upkeep(roster: dict | None, eco: dict, state: dict, months: int) -> float:
    """Содержание росписи за сезон (×2 в суровую зиму, бриф К1)."""
    rate = float(eco["army_upkeep_gold_per_unit_month"])
    units = st.roster_total(roster)
    winter = 2.0 if (state.get("flags") or {}).get("harsh_winter") else 1.0
    return units * rate * months * winter


def army_upkeep(state: dict, config: dict, lord_id: str) -> int:
    """Содержание армий лорда за сезон (та же ставка, что у гарнизона)."""
    eco = config["economy"]
    months = st.months_per_season(config)
    total = 0.0
    for army in state.get("armies", {}).values():
        if army.get("owner") == lord_id:
            total += _upkeep(army.get("roster"), eco, state, months)
    return int(round(total))


def season_income(state: dict, config: dict, lord_id: str) -> int:
    """Доход лорда за сезон: Σ по регионам − содержание армий (07 §7.10).
    Единый код для игрока и ИИ (честность 07 §7.10)."""
    total = sum(region_income(state, config, rid)
                for rid in st.owned_region_ids(state, lord_id))
    return total - army_upkeep(state, config, lord_id)
