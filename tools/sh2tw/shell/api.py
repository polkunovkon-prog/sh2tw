"""api.py — REST API оболочки кампании (07 §7.5, таблица роутов).

FastAPI-приложение создаётся create_app(campaign_dir); состояние живёт в
памяти приложения с автосейвом на каждое изменение (слепок history/ →
мутация → campaign_state.json). Все мутации идемпотентны по request_id
(кэш ответов в памяти приложения). Импорты FastAPI — внутри create_app,
чтобы остальная оболочка работала без fastapi/uvicorn.

Запуск: python -m sh2tw.shell.api --campaign campaigns/main --port 8402
"""
from __future__ import annotations

import argparse
import copy
from pathlib import Path
from typing import Any, Callable

from . import autoresolve as ar
from . import diplomacy as dip
from . import economy
from . import scene_client
from . import season
from . import state as st

DEFAULT_PORT = 8402
RECRUIT_PRICE_FACTOR = 2     # цена найма = unit_value × 2 (бриф К1)
MERCENARY_UNIT = "maceman"   # наёмный профиль событий (mercenaries, 07 §7.9)


def create_app(campaign_dir: Path | str) -> Any:
    """Собрать FastAPI-приложение кампании (ленивый импорт FastAPI)."""
    from fastapi import Body, FastAPI, HTTPException, Request
    from fastapi.responses import FileResponse, JSONResponse

    campaign_dir = Path(campaign_dir)
    config = st.load_config(campaign_dir / st.CONFIG_NAME)
    state_path = campaign_dir / st.STATE_NAME
    if state_path.exists():
        state = st.load_state(state_path)
    else:
        state = st.new_game(config, campaign_dir=campaign_dir)

    app = FastAPI(title="sh2tw campaign shell", version=st.SCHEMA_VERSION)
    app.state.campaign_dir = campaign_dir
    app.state.config = config
    app.state.state = state
    app.state.responses: dict[str, Any] = {}

    # ------------------------------------------------------------- helpers
    def _cur() -> dict:
        return app.state.state

    def _save() -> None:
        st.save_state(campaign_dir / st.STATE_NAME, _cur())

    def _http(status: int, message: str):
        return HTTPException(status_code=status, detail={"error": message})

    def _require_phase_player_actions() -> None:
        if _cur()["phase"] != "PLAYER_ACTIONS":
            raise _http(400, f"доступно только в фазе PLAYER_ACTIONS "
                             f"(сейчас {_cur()['phase']})")

    def _region_or_404(region_id: str) -> dict:
        rs = _cur()["regions"].get(region_id)
        if rs is None:
            raise _http(404, f"регион {region_id!r} не существует")
        return rs

    def _mutate(payload: dict, fn: Callable[[], dict],
                journal_kind: str | None = None,
                snapshot: bool = True) -> dict:
        """Идемпотентная мутация: request_id → кэш; слепок history → мутация
        → автосейв (+ events.jsonl); ошибки — HTTP 400."""
        rid = (payload or {}).get("request_id")
        if rid is not None and rid in app.state.responses:
            return app.state.responses[rid]
        pre = copy.deepcopy(_cur())
        try:
            result = fn()
        except (st.TransitionError, st.ConfigError, ValueError) as e:
            raise _http(400, str(e)) from e
        if snapshot:                     # undo сам расходует слепки — не плодим
            st.snapshot_history(pre, campaign_dir)
        _save()
        if journal_kind:
            st.append_event(campaign_dir, _cur()["season"], journal_kind,
                            result.get("summary", journal_kind))
        if rid is not None:
            app.state.responses[str(rid)] = result
        return result

    def _derived() -> dict:
        """Производные данные для экрана карты (07 §7.5)."""
        state = _cur()
        regions = []
        for rc in config["regions"]:
            rid = rc["id"]
            rs = state["regions"].get(rid) or {}
            regions.append({
                "id": rid, "name": rc["name"], "type": rc["type"],
                "owner": rs.get("owner"),
                "castle_level": int(rs.get("castle_level", 0)),
                "garrison_total": st.roster_total(rs.get("garrison")),
                "income": economy.region_income(state, config, rid),
                "neighbors": rc.get("neighbors", [])})
        return {"regions": regions, "treasury": state["treasury"],
                "pending_offers": state["pending_offers"],
                "pending_scenes": state["pending_scenes"],
                "victory": state["flags"].get("victory")}

    def _player_targets() -> set[str]:
        """Достижимые цели атак игрока: чужие регионы-соседи его владений."""
        state = _cur()
        player = st.human_lord_id(config)
        targets: set[str] = set()
        for rid in st.owned_region_ids(state, player):
            for nb in st.region_config(config, rid).get("neighbors") or []:
                owner = (state["regions"].get(nb) or {}).get("owner")
                if owner and owner != player:
                    targets.add(nb)
        return targets

    def _recruit(region_id: str, units: dict) -> dict:
        _require_phase_player_actions()
        state = _cur()
        rs = _region_or_404(region_id)
        player = st.human_lord_id(config)
        if rs.get("owner") != player:
            raise _http(400, f"регион {region_id} не принадлежит игроку")
        prices = ar.unit_values_cached()
        cost = 0
        for unit, n in (units or {}).items():
            if unit not in prices:
                raise _http(400, f"неизвестный тип юнита {unit!r}")
            if not isinstance(n, int) or n <= 0:
                raise _http(400, f"число юнитов {unit!r} должно быть > 0")
            cost += int(n * prices[unit] * RECRUIT_PRICE_FACTOR)
        gold = st.lord_gold(state, player)
        if cost > gold:
            raise _http(400, f"не хватает золота: нужно {cost}, есть {gold}")
        st.add_gold(state, player, -cost)
        rs["garrison"] = st.merge_rosters(
            rs.get("garrison"),
            {u: {"count": n, "vet": 0.0} for u, n in units.items()})
        season.player_action_made(state)
        st.logf(state, f"наём в {st.region_config(config, region_id)['name']}: "
                       f"{units} за {cost} золота")
        return {"region": region_id, "units": units, "cost": cost,
                "gold": st.lord_gold(state, player),
                "summary": f"наём {units} в {region_id}"}

    def _adjacent_to_player(region_id: str) -> bool:
        """Регион соседствует с владениями игрока."""
        state = _cur()
        player = st.human_lord_id(config)
        for rid in st.owned_region_ids(state, player):
            if region_id in (st.region_config(config, rid)
                             .get("neighbors") or []):
                return True
        return False

    def _buy_village(region_id: str) -> dict:
        _require_phase_player_actions()
        rs = _region_or_404(region_id)
        state = _cur()
        player = st.human_lord_id(config)
        rc = st.region_config(config, region_id)
        if rc["type"] != "village" or rs.get("owner"):
            raise _http(400, f"регион {region_id} не является нейтральной "
                             f"деревней")
        if not _adjacent_to_player(region_id):
            raise _http(400, f"деревня {region_id} не соседствует с "
                             f"владениями игрока")
        cost = int(rc.get("purchase_cost_honour", st.VILLAGE_COST_HONOUR))
        if st.lord_honour(state, player) < cost:
            raise _http(400, f"нужно {cost} чести, "
                             f"есть {st.lord_honour(state, player)}")
        st.add_honour(state, player, -cost)
        rs["owner"] = player
        rs["loyalty"] = st.START_LOYALTY
        season.player_action_made(state)
        st.logf(state, f"куплена деревня {rc['name']} за {cost} чести")
        return {"region": region_id, "cost_honour": cost,
                "honour": st.lord_honour(state, player),
                "summary": f"покупка {region_id}"}

    def _diplomacy(payload: dict) -> dict:
        _require_phase_player_actions()
        state = _cur()
        player = st.human_lord_id(config)
        action = payload.get("action")
        other = payload.get("with")
        if action not in ("peace", "alliance", "war"):
            raise _http(400, f"действие {action!r} ∉ peace|alliance|war")
        if other not in st.known_lords(state) or other == player:
            raise _http(400, f"лорд {other!r} не участвует в кампании")
        current = dip.get_pair(state, player, other)
        if action == "alliance" and current != "peace":
            raise _http(400, f"союз возможен только из мира (сейчас {current})")
        if action == "war":
            dip.declare_war(state, config, player, other)
        elif action == "peace":
            dip.make_peace(state, config, player, other)
        else:
            dip.make_alliance(state, config, player, other)
        season.player_action_made(state)
        return {"action": action, "with": other,
                "pair": st.pair_key(player, other),
                "state": dip.get_pair(state, player, other),
                "summary": f"дипломатия: {action} с {other}"}

    def _decide_offer(payload: dict) -> dict:
        _require_phase_player_actions()
        state = _cur()
        offers = state.get("pending_offers") or []
        try:
            index = int(payload.get("index"))
        except (TypeError, ValueError) as e:
            raise _http(400, "offer index: нужно целое") from e
        if not 0 <= index < len(offers):
            raise _http(400, f"предложения с индексом {index} нет "
                             f"(всего {len(offers)})")
        accept = bool(payload.get("accept"))
        offer = offers[index]
        kind = offer.get("offer")
        player = st.human_lord_id(config)
        if kind == "battle":
            if not accept:
                st.logf(state, f"игрок отложил решение по бою за "
                               f"{offer['target_region']} — авто-резолв в "
                               f"конце сезона")
                season.player_action_made(state)
                return {"decided": index, "offer": offer,
                        "result": "отложено до RESOLUTION",
                        "summary": "бой отложен"}
            result = season.execute_attack(state, config, offer["attacker"],
                                           offer["target_region"],
                                           st.battle_rng(state))
            offers.remove(offer)
            season.player_action_made(state)
            return {"decided": index, "offer": offer, "result": result,
                    "summary": f"бой за {offer['target_region']} (авто-резолв)"}
        offers.remove(offer)
        season.player_action_made(state)
        if kind == "peace" and accept:
            dip.make_peace(state, config, offer["from"], player)
            return {"decided": index, "offer": offer,
                    "result": "мир заключён",
                    "summary": f"мир с {offer['from']}"}
        if kind == "mercenaries" and accept:
            return _hire_mercenaries(state, offer)
        st.logf(state, f"предложение {kind} отклонено игроком")
        return {"decided": index, "offer": offer, "result": "отклонено",
                "summary": f"предложение {kind} отклонено"}

    def _hire_mercenaries(state: dict, offer: dict) -> dict:
        """Наёмники: макеманы со скидкой (07 §7.9) — сколько позволяет казна."""
        player = st.human_lord_id(config)
        discount = float(offer.get("discount", 0.3))
        price = int(ar.unit_values_cached()[MERCENARY_UNIT]
                    * RECRUIT_PRICE_FACTOR * (1.0 - discount))
        gold = st.lord_gold(state, player)
        n = gold // price if price > 0 else 0
        if n <= 0:
            st.logf(state, "наёмники ушли: не хватило золота")
            return {"decided": None, "offer": offer,
                    "result": "не хватило золота",
                    "summary": "наёмники отклонены (нет золота)"}
        army = st.army_of(state, player)
        army["roster"] = st.merge_rosters(
            army.get("roster"), {MERCENARY_UNIT: {"count": n, "vet": 0.0}})
        st.add_gold(state, player, -n * price)
        st.logf(state, f"наёмники: +{n} × {MERCENARY_UNIT} за {n * price} "
                       f"золота (скидка {int(discount * 100)} %)")
        return {"decided": None, "offer": offer,
                "result": {"unit": MERCENARY_UNIT, "count": n,
                           "gold_spent": n * price},
                "summary": f"наёмники: {n} × {MERCENARY_UNIT}"}

    # -------------------------------------------------------------- роуты
    @app.exception_handler(HTTPException)
    async def _http_error(_request: Request, exc: HTTPException):
        detail = exc.detail if isinstance(exc.detail, dict) \
            else {"error": str(exc.detail)}
        return JSONResponse(status_code=exc.status_code, content=detail)

    @app.get("/")
    def root():
        index = campaign_dir / st.STATIC_DIR / "index.html"
        if index.exists():
            return FileResponse(index)
        return {"status": "sh2tw shell", "docs": "/docs"}

    @app.get("/api/state")
    def get_state():
        return {"state": _cur(), "derived": _derived()}

    @app.post("/api/season/next")
    def season_next(payload: dict = Body(default={})):
        def fn() -> dict:
            result = season.next_season(_cur(), config, campaign_dir)
            result.pop("state", None)
            return result
        return _mutate(payload, fn, "season_next")

    @app.post("/api/region/{region_id}/develop")
    def region_develop(region_id: str, payload: dict = Body(default={})):
        def fn() -> dict:
            _require_phase_player_actions()
            result = scene_client.develop_region(
                _cur(), config, region_id, campaign_dir / "maps")
            season.player_action_made(_cur())
            result["summary"] = f"развитие {region_id}"
            return result
        return _mutate(payload, fn, "develop")

    @app.post("/api/region/{region_id}/recruit")
    def region_recruit(region_id: str, payload: dict = Body(default={})):
        def fn() -> dict:
            return _recruit(region_id, (payload or {}).get("units") or {})
        return _mutate(payload, fn, "recruit")

    @app.post("/api/region/{region_id}/buy")
    def region_buy(region_id: str, payload: dict = Body(default={})):
        def fn() -> dict:
            return _buy_village(region_id)
        return _mutate(payload, fn, "buy_village")

    @app.post("/api/battle/prepare")
    def battle_prepare(payload: dict = Body(default={})):
        target = (payload or {}).get("target_region")
        if target not in _cur()["regions"]:
            raise _http(404, f"регион {target!r} не существует")
        return scene_client.prepare_battle(_cur(), config, target)

    @app.post("/api/battle/scene")
    def battle_scene(payload: dict = Body(default={})):
        def fn() -> dict:
            _require_phase_player_actions()
            state = _cur()
            target = payload.get("target_region")
            _region_or_404(target)
            if target not in _player_targets():
                raise st.TransitionError(
                    f"регион {target} не достижим для атаки")
            out_dir = payload.get("out_dir") or (campaign_dir / "maps")
            result = scene_client.fight_scene(state, config, target, out_dir)
            if result.get("ok"):
                season.player_action_made(state)
            result["summary"] = f"сцена боя на {target}"
            return result
        return _mutate(payload, fn, "battle_scene")

    @app.post("/api/battle/autoresolve")
    def battle_autoresolve(payload: dict = Body(default={})):
        def fn() -> dict:
            _require_phase_player_actions()
            state = _cur()
            target = payload.get("target_region")
            _region_or_404(target)
            if target not in _player_targets():
                raise st.TransitionError(
                    f"регион {target} не достижим для атаки")
            player = st.human_lord_id(config)
            result = season.execute_attack(state, config, player, target,
                                           st.battle_rng(state))
            season.player_action_made(state)
            result["summary"] = f"авто-резолв боя за {target}"
            return result
        return _mutate(payload, fn, "battle_autoresolve")

    @app.post("/api/scene/result")
    def scene_result(payload: dict = Body(default={})):
        def fn() -> dict:
            _require_phase_player_actions()
            result = scene_client.accept_scene_result(_cur(), config, payload)
            season.player_action_made(_cur())
            result["summary"] = f"итог сцены {payload.get('scene_id')}"
            return result
        return _mutate(payload, fn, "scene_result")

    @app.get("/api/scene/pending")
    def scene_pending():
        return _cur().get("pending_scenes") or []

    @app.post("/api/diplomacy")
    def diplomacy_action(payload: dict = Body(default={})):
        def fn() -> dict:
            return _diplomacy(payload)
        return _mutate(payload, fn, "diplomacy")

    @app.post("/api/save")
    def save(payload: dict = Body(default={})):
        _save()
        return {"saved": True, "path": str(campaign_dir / st.STATE_NAME)}

    @app.get("/api/load/{campaign_id}")
    def load(campaign_id: str):
        if campaign_id != config["campaign_id"]:
            raise _http(404, f"кампания {campaign_id!r} не найдена")
        app.state.state = st.load_state(campaign_dir / st.STATE_NAME)
        return {"campaign_id": campaign_id, "state": _cur(),
                "derived": _derived()}

    @app.post("/api/undo")
    def undo(payload: dict = Body(default={})):
        def fn() -> dict:
            restored = st.undo(_cur(), campaign_dir, steps=1)
            app.state.state = restored
            _save()
            return {"undone": True, "season": restored["season"],
                    "phase": restored["phase"],
                    "summary": f"undo к сезону {restored['season']}"}
        return _mutate(payload, fn, "undo", snapshot=False)

    @app.post("/api/offer/decide")
    def offer_decide(payload: dict = Body(default={})):
        def fn() -> dict:
            return _decide_offer(payload)
        return _mutate(payload, fn, "offer_decide")

    return app


def main() -> None:
    """Точка входа: python -m sh2tw.shell.api --campaign campaigns/main."""
    import uvicorn

    parser = argparse.ArgumentParser(description="sh2tw campaign shell API")
    parser.add_argument("--campaign", default="campaigns/main",
                        help="каталог кампании с campaign_config.json")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()
    uvicorn.run(create_app(args.campaign), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
