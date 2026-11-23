"""agenda_ai.py — стратегический ИИ лордов: приоритетная таблица (07 §7.3).

score(action) = w_aggr×threat_gain + w_greed×income_gain + w_build×dev_gain
              + w_loyal×coalition_bonus − risk×cost,
веса — черты persona лорда. Соответствие членов формулы действиям (бриф К1):
defend → threat_gain=2; attack/recruit → threat_gain=1, у attack
risk×cost = 0.5×S_армии/1000; develop → dev_gain=1; buy_village/offer_peace →
income_gain=1; join_coalition → coalition_bonus=1. ИИ-лорд выполняет ≤1
кампанию за сезон (лучшее действие; score<0 → пассив); каждое решение
логируется. Атака на игрока → offer "battle"; атака ИИ-ИИ — авто-резолв
немедленно (через season.execute_attack, ленивый импорт против цикла).
"""
from __future__ import annotations

import random

from . import autoresolve as ar
from . import state as st

RESERVE_GOLD = 200               # резерв казны для develop (07 §7.3)
DEV_ACTION_COST = 100            # стоимость развития
DEV_POINTS_PER_ACTION = 20       # очки развития за действие
RECRUIT_BUDGET_RANGE = (200, 400)
VILLAGE_COST_HONOUR = 100        # покупка деревни за честь (G1)
ATTACK_SUPERIORITY = 1.3         # армия ≥ 1.3 × оборона цели
ATTACK_RISK_FACTOR = 0.5         # risk×cost = 0.5 × S_армии / 1000
COALITION_SHARE = 0.5            # лидер владеет ≥ 50 % регионов
DEFEND_THREAT_GAIN = 2          # defend: приоритетная защита (бриф К1)

# детерминированный приоритет равных score (defend — приоритет, бриф К1)
ACTION_ORDER = ("defend", "attack", "recruit", "develop", "buy_village",
                "offer_peace", "join_coalition")


def _persona(config: dict, lord_id: str) -> dict:
    """persona лорда из конфига (пустая — нейтральные веса)."""
    return (st.lord_entry(config, lord_id) or {}).get("persona") or {}


def _name(config: dict, lord_id: str) -> str:
    return (st.lord_entry(config, lord_id) or {}).get("name", lord_id)


def _neighbor_targets(state: dict, config: dict,
                      lord_id: str) -> list[tuple[str, str, float]]:
    """Соседние регионы ЧУЖИХ лордов: [(rid, owner, сила обороны), ...]."""
    out = []
    seen = set()
    for rid in st.owned_region_ids(state, lord_id):
        for nb in st.region_config(config, rid).get("neighbors") or []:
            owner = (state["regions"].get(nb) or {}).get("owner")
            if not owner or owner == lord_id or nb in seen:
                continue
            seen.add(nb)
            out.append((nb, owner, ar.roster_strength(
                st.defense_force_roster(state, nb))))
    return sorted(out, key=lambda t: (t[2], t[0]))


def _war_threat_nearby(state: dict, config: dict, lord_id: str) -> bool:
    """Враждебный (war) лорд владеет регионом-соседом (условие recruit)."""
    from . import diplomacy as dip
    for _rid, owner, _defense in _neighbor_targets(state, config, lord_id):
        if dip.get_pair(state, lord_id, owner) == "war":
            return True
    return False


def _capital_region(state: dict, config: dict, lord_id: str) -> str | None:
    """«Столица»: стартовый регион (если наш), иначе первый по id."""
    owned = st.owned_region_ids(state, lord_id)
    if not owned:
        return None
    start = (st.lord_entry(config, lord_id) or {}).get("start_region")
    return start if start in owned else owned[0]


def _develop_region(state: dict, config: dict, lord_id: str) -> str | None:
    """Регион с наименьшим уровнем замка, где есть куда расти (<5)."""
    candidates = []
    for rid in st.owned_region_ids(state, lord_id):
        rc = st.region_config(config, rid)
        if rc["type"] != "castle":
            continue
        max_level = max(int(k) for k in rc.get("castle_levels") or {"1": "x"})
        if int(state["regions"][rid].get("castle_level", 0)) < max_level:
            candidates.append((int(state["regions"][rid]["castle_level"]), rid))
    return min(candidates)[1] if candidates else None


def _buyable_village(state: dict, config: dict, lord_id: str) -> str | None:
    """Нейтральная деревня-сосед (buy village, G1)."""
    for rid in st.owned_region_ids(state, lord_id):
        for nb in st.region_config(config, rid).get("neighbors") or []:
            rc = st.region_config(config, nb)
            if rc["type"] == "village" \
                    and not (state["regions"].get(nb) or {}).get("owner"):
                return nb
    return None


def _coalition_leader(state: dict, config: dict) -> str | None:
    """Лорд, владеющий ≥ 50 % регионов карты (анти-снежный ком)."""
    total = len(config["regions"])
    counts: dict[str, int] = {}
    for rs in state["regions"].values():
        if rs.get("owner"):
            counts[rs["owner"]] = counts.get(rs["owner"], 0) + 1
    if not counts:
        return None
    leader = max(sorted(counts), key=lambda lid: counts[lid])
    if counts[leader] >= COALITION_SHARE * total:
        return leader
    return None


def _candidates(state: dict, config: dict, lord_id: str, budget: int,
                attacked: set[str]) -> list[dict]:
    """Кандидаты сезона с оценками (07 §7.3); ничьи ломает ACTION_ORDER."""
    from . import diplomacy as dip
    persona = _persona(config, lord_id)
    gold = st.lord_gold(state, lord_id)
    honour = st.lord_honour(state, lord_id)
    out: list[dict] = []
    if attacked:                        # defend: на регион напали (приоритет)
        out.append({"action": "defend",
                    "score": float(persona.get("aggression", 0.0))
                    * DEFEND_THREAT_GAIN,
                    "region": sorted(attacked)[0]})
    targets = _neighbor_targets(state, config, lord_id)
    force = ar.roster_strength(st.attack_force_roster(state, lord_id))
    if targets:
        rid, owner, defense = targets[0]          # слабейший сосед
        if defense <= 0 or force >= ATTACK_SUPERIORITY * defense:
            out.append({"action": "attack",
                        "score": float(persona.get("aggression", 0.0))
                        - ATTACK_RISK_FACTOR * force / 1000.0,
                        "target_region": rid, "target_owner": owner})
    threat = _war_threat_nearby(state, config, lord_id)
    if threat and gold >= budget:
        out.append({"action": "recruit",
                    "score": float(persona.get("aggression", 0.0))})
    dev_region = _develop_region(state, config, lord_id)
    if dev_region and gold > RESERVE_GOLD:
        out.append({"action": "develop", "region": dev_region,
                    "score": float(persona.get("builder", 0.0))})
    village = _buyable_village(state, config, lord_id)
    if village and honour >= VILLAGE_COST_HONOUR:
        out.append({"action": "buy_village", "region": village,
                    "score": float(persona.get("greed", 0.0))})
    player = st.human_lord_id(config)
    start = len(state.get("ai_start_regions", {}).get(lord_id) or [])
    if dip.get_pair(state, lord_id, player) == "war" and start \
            and len(st.owned_region_ids(state, lord_id)) < start \
            and not any(o.get("offer") == "peace" and o.get("from") == lord_id
                        for o in state.get("pending_offers") or []):
        out.append({"action": "offer_peace",
                    "score": float(persona.get("greed", 0.0))})
    leader = _coalition_leader(state, config)
    if leader and leader != lord_id \
            and not state["flags"].get("coalition_against_leader_active"):
        out.append({"action": "join_coalition", "leader": leader,
                    "score": float(persona.get("loyal", 0.0))})
    return out


def _decide(state: dict, config: dict, lord_id: str, budget: int,
            attacked: set[str]) -> dict | None:
    """Лучшее действие по score (score < 0 → пассив)."""
    candidates = _candidates(state, config, lord_id, budget, attacked)
    if not candidates:
        return None
    best = max(candidates, key=lambda c: (c["score"],
                                          -ACTION_ORDER.index(c["action"])))
    return best if best["score"] >= 0 else None


def _recruit_into(state: dict, config: dict, lord_id: str, region_id: str,
                  budget: int) -> dict:
    """Найм юнитов профиля лорда в гарнизон региона (07 §7.3):
    aggression > 0.5 — spearman/archer 50/50, иначе archer 70/30."""
    persona = _persona(config, lord_id)
    shares = ({"spearman": 0.5, "archer": 0.5}
              if float(persona.get("aggression", 0.0)) > 0.5
              else {"archer": 0.7, "spearman": 0.3})
    budget = min(budget, st.lord_gold(state, lord_id))
    prices = ar.unit_values_cached()
    units: dict[str, int] = {}
    spent = 0
    for unit, share in sorted(shares.items()):
        price = prices.get(unit)
        if price is None:
            continue
        n = int(budget * share // price)
        if n > 0:
            units[unit] = n
            spent += n * int(price)
    if units:
        st.add_gold(state, lord_id, -spent)
        rs = state["regions"][region_id]
        rs["garrison"] = st.merge_rosters(
            rs.get("garrison"),
            {u: {"count": n, "vet": 0.0} for u, n in units.items()})
    return {"units": units, "gold_spent": spent}


def _apply(state: dict, config: dict, lord_id: str, decision: dict,
           budget: int) -> dict:
    """Применить решение (кроме attack — его резолвит _execute_attack)."""
    name = _name(config, lord_id)
    action = decision["action"]
    if action == "defend":
        region = decision["region"]
        army = st.army_of(state, lord_id)
        if army is not None:                # лорд — в замке (07 §7.3)
            army["located_region"] = region
            army["lord_present"] = True
        recruit = _recruit_into(state, config, lord_id, region, budget)
        st.logf(state, f"{name} обороняет "
                       f"{st.region_config(config, region)['name']} "
                       f"(defend, наём {recruit['units']})")
        return {"lord": lord_id, "action": "defend", "region": region,
                **recruit}
    if action == "recruit":
        region = _capital_region(state, config, lord_id)
        targets = _neighbor_targets(state, config, lord_id)
        if targets:                         # гарнизон у границы с угрозой
            for rid in st.owned_region_ids(state, lord_id):
                if targets[0][0] in (st.region_config(config, rid)
                                     .get("neighbors") or []):
                    region = rid
                    break
        recruit = _recruit_into(state, config, lord_id, region, budget)
        st.logf(state, f"{name} набирает войска в "
                       f"{st.region_config(config, region)['name']} "
                       f"({recruit['units']}, −{recruit['gold_spent']} з)")
        return {"lord": lord_id, "action": "recruit", "region": region,
                **recruit}
    if action == "develop":
        region = decision["region"]
        st.add_gold(state, lord_id, -DEV_ACTION_COST)
        rs = state["regions"][region]
        rs["development_points"] = int(rs.get("development_points", 0)) \
            + DEV_POINTS_PER_ACTION
        st.recalc_castle_level(state, config, region)
        st.logf(state, f"{name} развивает "
                       f"{st.region_config(config, region)['name']} "
                       f"(−{DEV_ACTION_COST} з, +{DEV_POINTS_PER_ACTION} очков)")
        return {"lord": lord_id, "action": "develop", "region": region}
    if action == "buy_village":
        region = decision["region"]
        st.add_honour(state, lord_id, -VILLAGE_COST_HONOUR)
        rs = state["regions"][region]
        rs["owner"] = lord_id
        rs["loyalty"] = st.START_LOYALTY
        st.logf(state, f"{name} покупает "
                       f"{st.region_config(config, region)['name']} "
                       f"за {VILLAGE_COST_HONOUR} чести")
        return {"lord": lord_id, "action": "buy_village", "region": region}
    if action == "offer_peace":
        offer = {"offer": "peace", "from": lord_id,
                 "season": int(state["season"])}
        state.setdefault("pending_offers", []).append(offer)
        st.logf(state, f"{name} предлагает игроку мир (проигрывает войну)")
        return offer
    if action == "join_coalition":
        return _join_coalition(state, config, lord_id, decision["leader"])
    raise ValueError(f"неизвестное действие ИИ: {action}")  # pragma: no cover


def _join_coalition(state: dict, config: dict, lord_id: str,
                    leader: str) -> dict:
    """Коалиция против лидера: прочие лорды — мир между собой, война с ним."""
    from . import diplomacy as dip
    state["flags"]["coalition_against_leader_active"] = True
    members = [lid for lid in st.known_lords(state) if lid != leader]
    for i in range(len(members)):
        for j in range(i + 1, len(members)):
            dip.set_pair(state, members[i], members[j], "peace")
    for lid in members:
        dip.set_pair(state, lid, leader, "war")
    st.logf(state, f"{_name(config, lord_id)} сколачивает коалицию против "
                   f"лидера {leader}")
    return {"lord": lord_id, "action": "join_coalition", "leader": leader}


def _execute_attack(state: dict, config: dict, lord_id: str,
                    decision: dict, rng: random.Random,
                    offers: list[dict]) -> None:
    """Атака ИИ: цель-игрок → offer «battle»; ИИ-ИИ → авто-резолв немедленно."""
    from . import season
    region_id = decision["target_region"]
    if decision["target_owner"] == st.human_lord_id(config):
        offer = {"offer": "battle", "attacker": lord_id,
                 "target_region": region_id, "season": int(state["season"])}
        state.setdefault("pending_offers", []).append(offer)
        offers.append(offer)
        state.setdefault("attacked_regions", []).append(region_id)
        st.logf(state, f"{_name(config, lord_id)} выступает против "
                       f"{st.region_config(config, region_id)['name']} — "
                       f"нужно решение игрока (сцена/авто-резолв)")
        return
    st.logf(state, f"{_name(config, lord_id)} атакует "
                   f"{st.region_config(config, region_id)['name']} "
                   f"(война ИИ-ИИ, авто-резолв)")
    season.execute_attack(state, config, lord_id, region_id, rng)


def ai_turn(state: dict, config: dict, rng: random.Random,
            attacked_regions: set[str] | list[str] | None = None) -> list[dict]:
    """AI_TURNS: ≤1 кампания на ИИ-лорда; возвращает offers, созданные ходом
    (атаки на игрока); атаки ИИ-ИИ резолвятся немедленно (07 §7.3)."""
    offers: list[dict] = []
    owned_by = set(attacked_regions or [])
    for lord_id in st.ai_lord_ids(config):
        if not st.owned_region_ids(state, lord_id):
            continue                        # мёртвый лорд (07 §7.7)
        attacked = owned_by & set(st.owned_region_ids(state, lord_id))
        budget = rng.randint(*RECRUIT_BUDGET_RANGE)
        decision = _decide(state, config, lord_id, budget, attacked)
        if decision is None:
            st.logf(state, f"{_name(config, lord_id)} выжидает (пассив)")
            continue
        if decision["action"] == "attack":
            _execute_attack(state, config, lord_id, decision, rng, offers)
            continue
        result = _apply(state, config, lord_id, decision, budget)
        if isinstance(result, dict) and result.get("offer"):
            offers.append(result)         # мир/наёмники — тоже offers (бриф)
    return offers
