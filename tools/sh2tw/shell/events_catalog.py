"""events_catalog.py — каталог событий кампании (07 §7.9).

Броски выполняются в фазе EVENTS каждого сезона по RNG с сидом; каждое
событие: условие, вероятность (config.events.probabilities), эффект, запись
в журнал. Штрафы дохода пишутся в state.regions[rid].income_penalty и
сбрасываются на SEASON_START следующего сезона (доход уже уплачен — штраф
бьёт по следующему начислению, порядок фаз 07 §7.2). rebellion обязателен
(анти-снежный ком): p = base + (25 − loyalty)/25 для регионов с loyalty < 25.
"""
from __future__ import annotations

import random

from . import state as st

EVENT_ORDER = ("harvest_failure", "plague", "rats", "fair", "mercenaries",
               "harsh_winter", "embassy", "hunt", "feast")

HARVEST_INCOME_FACTOR = 0.5    # неурожай: −50 % дохода региона на сезон
RATS_INCOME_FACTOR = 0.8       # крысы: −20 % дохода одного региона
FAIR_HONOUR_PLAYER = 5         # ярмарка: игроку +5 чести…
FAIR_HONOUR_AI = 2             # …прочим лордам +2 (бриф К1)
MERCENARY_DISCOUNT = 0.3       # наёмники: роспись со скидкой 30 %
EMBASSY_TRIBUTE_GOLD = 10      # посольство: дань 10 з/сезон…
EMBASSY_TRIBUTE_SEASONS = 3    # …на 3 сезона от мирного лорда
EMBASSY_FALLBACK_HONOUR = 3    # …иначе +3 чести
HUNT_HONOUR = 4                # охота: +4 чести игроку
FEAST_GOLD = 50                # пир: −50 золота…
FEAST_HONOUR = 6               # …+6 чести игроку
REBELLION_LOYALTY_THRESHOLD = 25
REBELLION_LOYALTY_AFTER = 20
REBELLION_GARRISON_LOSS = 0.3  # гарнизон −30 %


def _owned_regions(state: dict) -> list[str]:
    """id регионов под чьим-то владением."""
    return sorted(rid for rid, rs in state["regions"].items()
                  if rs.get("owner"))


def _set_penalty(state: dict, region_id: str, factor: float) -> None:
    """Штраф дохода региона на сезон (минимум из действующих)."""
    rs = state["regions"][region_id]
    current = rs.get("income_penalty")
    rs["income_penalty"] = factor if current is None \
        else min(float(current), factor)


def _harvest_failure(state: dict, config: dict, rng: random.Random) -> dict | None:
    """Неурожай в регионе с product=wheat: −50 % дохода на сезон."""
    candidates = [rid for rid in _owned_regions(state)
                  if st.region_config(config, rid).get("product") == "wheat"]
    if not candidates:
        return None
    rid = rng.choice(sorted(candidates))
    _set_penalty(state, rid, HARVEST_INCOME_FACTOR)
    st.logf(state, f"Урожай в {st.region_config(config, rid)['name']} погиб "
                   f"(harvest_failure)")
    return {"id": "harvest_failure", "region": rid}


def _plague(state: dict, config: dict, rng: random.Random) -> dict | None:
    """Эпидемия: лояльность −10 во всех владениях."""
    owned = _owned_regions(state)
    if not owned:
        return None
    for rid in owned:
        rs = state["regions"][rid]
        rs["loyalty"] = max(0, int(rs.get("loyalty", 0)) - 10)
    st.logf(state, "Эпидемия: лояльность −10 во всех владениях (plague)")
    return {"id": "plague", "regions": owned}


def _rats(state: dict, config: dict, rng: random.Random) -> dict | None:
    """Крысы: −20 % дохода одного региона."""
    owned = _owned_regions(state)
    if not owned:
        return None
    rid = rng.choice(owned)
    _set_penalty(state, rid, RATS_INCOME_FACTOR)
    st.logf(state, f"Крысы в {st.region_config(config, rid)['name']}: "
                   f"доход −20 % (rats)")
    return {"id": "rats", "region": rid}


def _fair(state: dict, config: dict, rng: random.Random) -> dict:
    """Ярмарка: игроку +5 чести, прочим лордам +2 (бриф К1)."""
    player = st.human_lord_id(config)
    for lord_id in st.known_lords(state):
        st.add_honour(state, lord_id,
                      FAIR_HONOUR_PLAYER if lord_id == player
                      else FAIR_HONOUR_AI)
    st.logf(state, f"Ярмарка: +{FAIR_HONOUR_PLAYER} чести игроку, "
                   f"+{FAIR_HONOUR_AI} прочим лордам (fair)")
    return {"id": "fair", "honour_player": FAIR_HONOUR_PLAYER,
            "honour_ai": FAIR_HONOUR_AI}


def _mercenaries(state: dict, config: dict, rng: random.Random) -> dict:
    """Наёмники предлагают роспись со скидкой 30 % (offer игроку)."""
    offer = {"offer": "mercenaries", "discount": MERCENARY_DISCOUNT,
             "season": int(state["season"])}
    state.setdefault("pending_offers", []).append(offer)
    st.logf(state, "Наёмники предлагают роспись со скидкой 30 % (mercenaries)")
    return offer


def _harsh_winter(state: dict, config: dict, rng: random.Random) -> dict:
    """Суровая зима: содержание ×2 в этом сезоне."""
    state["flags"]["harsh_winter"] = True
    st.logf(state, "Суровая зима: содержание войск ×2 в этом сезоне "
                   "(harsh_winter)")
    return {"id": "harsh_winter"}


def _embassy(state: dict, config: dict, rng: random.Random) -> dict:
    """Посольство: дань 10 з/сезон на 3 сезона от случайного мирного лорда
    (нет мирных — +3 чести игроку)."""
    player = st.human_lord_id(config)
    from . import diplomacy as dip
    peaceful = sorted(lid for lid in st.known_lords(state)
                      if lid != player
                      and dip.get_pair(state, lid, player) == "peace")
    if peaceful:
        donor = rng.choice(peaceful)
        until = int(state["season"]) + EMBASSY_TRIBUTE_SEASONS
        state["diplomacy"].setdefault("tributes", []).append(
            {"from": donor, "to": player,
             "gold_per_season": EMBASSY_TRIBUTE_GOLD, "until_season": until})
        st.logf(state, f"Посольство: {donor} обязуется данью "
                       f"{EMBASSY_TRIBUTE_GOLD} з/сезон до S{until} (embassy)")
        return {"id": "embassy", "tribute_from": donor}
    st.add_honour(state, player, EMBASSY_FALLBACK_HONOUR)
    st.logf(state, f"Посольство: +{EMBASSY_FALLBACK_HONOUR} чести (embassy)")
    return {"id": "embassy", "honour": EMBASSY_FALLBACK_HONOUR}


def _hunt(state: dict, config: dict, rng: random.Random) -> dict:
    """Королевская охота: +4 чести игроку."""
    player = st.human_lord_id(config)
    st.add_honour(state, player, HUNT_HONOUR)
    st.logf(state, f"Королевская охота: +{HUNT_HONOUR} чести (hunt)")
    return {"id": "hunt", "honour": HUNT_HONOUR}


def _feast(state: dict, config: dict, rng: random.Random) -> dict:
    """Пир: −50 золота, +6 чести игроку."""
    st.add_gold(state, st.human_lord_id(config), -FEAST_GOLD)
    st.add_honour(state, st.human_lord_id(config), FEAST_HONOUR)
    st.logf(state, f"Пир: −{FEAST_GOLD} золота, +{FEAST_HONOUR} чести (feast)")
    return {"id": "feast", "gold": -FEAST_GOLD, "honour": FEAST_HONOUR}


_HANDLERS = {"harvest_failure": _harvest_failure, "plague": _plague,
             "rats": _rats, "fair": _fair, "mercenaries": _mercenaries,
             "harsh_winter": _harsh_winter, "embassy": _embassy,
             "hunt": _hunt, "feast": _feast}


def _rebellions(state: dict, config: dict, rng: random.Random) -> list[dict]:
    """Восстания (обязательное событие): регионы с лояльностью < 25;
    p = base + (25 − loyalty)/25; эффект: loyalty → 20, гарнизон −30 %."""
    base = float(config["events"]["probabilities"].get("rebellion", 0.0))
    player = st.human_lord_id(config)
    fired: list[dict] = []
    for rid in _owned_regions(state):
        rs = state["regions"][rid]
        loyalty = int(rs.get("loyalty", 100))
        if loyalty >= REBELLION_LOYALTY_THRESHOLD:
            continue
        p_region = base + (REBELLION_LOYALTY_THRESHOLD - loyalty) \
            / REBELLION_LOYALTY_THRESHOLD
        if rng.random() >= p_region:
            continue
        rs["loyalty"] = REBELLION_LOYALTY_AFTER
        garrison = rs.get("garrison") or {}
        for unit, rec in garrison.items():           # гарнизон −30 %
            dead = int(rec.get("count", 0) * REBELLION_GARRISON_LOSS)
            rec["count"] = int(rec.get("count", 0)) - dead
        rs["garrison"] = {u: r for u, r in garrison.items() if r["count"] > 0}
        warning = " — ВНИМАНИЕ: регион игрока!" if rs.get("owner") == player \
            else ""
        st.logf(state, f"Восстание в {st.region_config(config, rid)['name']}: "
                       f"гарнизон −30 %, лояльность "
                       f"{REBELLION_LOYALTY_AFTER}{warning} (rebellion)")
        fired.append({"id": "rebellion", "region": rid})
    return fired


def apply_events(state: dict, config: dict, rng: random.Random) -> list[dict]:
    """Фаза EVENTS: броски по каталогу → эффекты + записи в журнал."""
    probs = config["events"]["probabilities"]
    fired: list[dict] = []
    for event_id in EVENT_ORDER:
        if rng.random() >= float(probs.get(event_id, 0.0)):
            continue
        record = _HANDLERS[event_id](state, config, rng)
        if record is not None:
            fired.append(record)
    fired.extend(_rebellions(state, config, rng))
    return fired
