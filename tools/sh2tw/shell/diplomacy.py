"""diplomacy.py — война/мир/союз/дань (07 §7.8).

Состояния пар: war | peace | alliance; ключ пары — лорды по алфавиту через
«|». Союзники обороняющегося вступают в войну через 1 сезон
(pending_ally_joins, процессинг на RESOLUTION). Дань списывается на
SEASON_START (from → to), запись удаляется когда season > until_season.
"""
from __future__ import annotations

from . import state as st


def _check_lords(state: dict, a: str, b: str) -> None:
    """Лорды должны быть известны состоянию (защита от опечаток)."""
    known = set(st.known_lords(state))
    for lord in (a, b):
        if lord not in known:
            raise ValueError(f"неизвестный лорд {lord!r}")


def get_pair(state: dict, a: str, b: str) -> str:
    """Состояние пары лордов (по умолчанию peace)."""
    _check_lords(state, a, b)
    if a == b:
        raise ValueError("пара дипломатии из одного лорда")
    return state.get("diplomacy", {}).get("pairs", {}).get(
        st.pair_key(a, b), "peace")


def set_pair(state: dict, a: str, b: str, value: str) -> None:
    """Установка состояния пары с валидацией значения."""
    if value not in st.DIPLOMACY_STATES:
        raise ValueError(f"состояние дипломатии {value!r} "
                         f"∉ {st.DIPLOMACY_STATES}")
    _check_lords(state, a, b)
    if a == b:
        raise ValueError("пара дипломатии из одного лорда")
    state.setdefault("diplomacy", {}).setdefault("pairs", {})[
        st.pair_key(a, b)] = value


def lords_allied_with(state: dict, lord_id: str) -> list[str]:
    """Союзники лорда (alliance)."""
    pairs = state.get("diplomacy", {}).get("pairs", {})
    out = []
    for key, value in pairs.items():
        if value != "alliance":
            continue
        left, right = key.split("|")
        if left == lord_id:
            out.append(right)
        elif right == lord_id:
            out.append(left)
    return sorted(out)


def declare_war(state: dict, config: dict, aggressor: str,
                defender: str) -> list[dict]:
    """Агрессор объявляет войну; союзники обороняющегося подтягиваются
    через 1 сезон (pending_ally_joins, процессинг на RESOLUTION)."""
    set_pair(state, aggressor, defender, "war")
    pending = state["diplomacy"].setdefault("pending_ally_joins", [])
    joins: list[dict] = []
    for ally in lords_allied_with(state, defender):
        if ally == aggressor or get_pair(state, ally, aggressor) == "war":
            continue
        record = {"season": int(state["season"]) + 1, "ally": ally,
                  "against": aggressor}
        if record not in pending:
            pending.append(record)
            joins.append(record)
    st.logf(state, f"{aggressor} объявляет войну {defender}"
            + (f"; союзники {defender} вступят в войну через сезон"
               if joins else ""))
    return joins


def process_pending_ally_joins(state: dict, config: dict) -> list[dict]:
    """RESOLUTION: союзники вступают в войну, когда наступил их сезон и
    война ещё идёт; отработанные записи удаляются."""
    pending = state["diplomacy"].get("pending_ally_joins") or []
    still, joined = [], []
    for join in pending:
        if int(join["season"]) > int(state["season"]):
            still.append(join)          # сезон союза ещё не настал
            continue
        if get_pair(state, join["ally"], join["against"]) != "war":
            set_pair(state, join["ally"], join["against"], "war")
            joined.append(join)
            st.logf(state, f"союзник {join['ally']} вступает в войну против "
                           f"{join['against']}")
        # сезон настал, но союзник уже воюет/мирён — запись отработана
    state["diplomacy"]["pending_ally_joins"] = still
    return joined


def make_alliance(state: dict, config: dict, a: str, b: str) -> None:
    """Заключение союза."""
    set_pair(state, a, b, "alliance")
    st.logf(state, f"{a} и {b} заключают союз")


def make_peace(state: dict, config: dict, a: str, b: str,
               tribute: dict | None = None) -> dict | None:
    """Мир между лордами; опционально оплачивается данью (запись в tributes)."""
    set_pair(state, a, b, "peace")
    st.logf(state, f"{a} и {b} заключают мир"
                   + (" (условие: дань)" if tribute else ""))
    if tribute:
        record = {"from": a, "to": b,
                  "gold_per_season": int(tribute.get("gold_per_season", 0)),
                  "until_season": int(tribute.get(
                      "until_season", int(state["season"]) + 4))}
        state["diplomacy"].setdefault("tributes", []).append(record)
        return record
    return None


def _transfer_gold(state: dict, from_lord: str, to_lord: str,
                   amount: int) -> int:
    """Перевод золота между казнами (платится сколько есть); возврат — факт."""
    paid = max(0, min(int(amount), st.lord_gold(state, from_lord)))
    st.add_gold(state, from_lord, -paid)
    st.add_gold(state, to_lord, paid)
    return paid


def process_tributes(state: dict, config: dict) -> list[dict]:
    """SEASON_START: дань списывается (from → to); запись удаляется,
    когда season > until_season (бриф К1)."""
    tributes = state["diplomacy"].setdefault("tributes", [])
    paid: list[dict] = []
    keep: list[dict] = []
    for t in tributes:
        if int(state["season"]) <= int(t["until_season"]):
            fact = _transfer_gold(state, t["from"], t["to"],
                                  int(t["gold_per_season"]))
            paid.append({"from": t["from"], "to": t["to"], "gold": fact})
            keep.append(t)
        else:
            st.logf(state, f"дань {t['from']} → {t['to']} прекращается "
                           f"(истекла)")
    state["diplomacy"]["tributes"] = keep
    return paid
