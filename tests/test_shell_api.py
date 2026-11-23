"""Integration-тесты REST API оболочки (07 §7.5) через FastAPI TestClient.

Мини-кампания из conftest: 3 региона, победа eliminate_lords [l_hawk].
Сценарная генерация в тестовой среде деградирует (нет карт игры) —
проверяем fallback без 500. Исходы боев зависят от сида — тесты допускают
оба исхода, но проверяют консистентность состояния.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import make_mini_config
from sh2tw.scenes.templates import Template, TemplateError
from sh2tw.shell import scene_client
from sh2tw.shell import state as st
from sh2tw.shell.api import create_app

DATA = Path(__file__).resolve().parents[1] / "tests" / "data"


@pytest.fixture()
def client(mini_campaign: Path) -> TestClient:
    """TestClient на tmp-каталоге кампании (campaign_config.json записан)."""
    app = create_app(mini_campaign)
    return TestClient(app)


class FixtureTemplate(Template):
    """Шаблон-фикстура: файл из tests/data напрямую (как в test_generator)."""

    def __init__(self, file: str = "sample.s2m"):
        super().__init__(template_id="tpl_fixture", kind="game_map",
                         file=file, sha256=None, roles=["siege"])

    def resolve(self, game_maps_dir=None) -> Path:  # noqa: ANN001
        p = DATA / self.file
        if not p.exists():
            raise TemplateError(f"нет фикстуры {p}")
        return p


# ================================================================== базовые
def test_root_and_state(client: TestClient, mini_campaign: Path):
    assert client.get("/").json() == {"status": "sh2tw shell",
                                      "docs": "/docs"}
    (mini_campaign / "static").mkdir()
    (mini_campaign / "static" / "index.html").write_text(
        "<html>карта</html>", encoding="utf-8")
    assert "карта" in client.get("/").text
    r = client.get("/api/state")
    assert r.status_code == 200
    body = r.json()
    assert body["state"]["season"] == 0
    derived = body["derived"]
    assert [reg["id"] for reg in derived["regions"]] == ["r01", "r02", "r07"]
    r01 = derived["regions"][0]
    assert r01["owner"] == "player" and r01["garrison_total"] == 16
    assert r01["income"] == 122 and r01["neighbors"] == ["r02", "r07"]
    assert derived["treasury"]["gold"] == 500
    assert derived["victory"] is None


def test_season_next_twice(client: TestClient):
    r1 = client.post("/api/season/next", json={})
    assert r1.status_code == 200
    assert r1.json()["season"] == 1 and r1.json()["season_name"] == "Весна"
    r2 = client.post("/api/season/next", json={})
    assert r2.status_code == 200
    body = r2.json()
    assert body["season"] == 2
    assert isinstance(body["offers"], list)      # offers могут быть пусты
    assert isinstance(body["events"], list)
    assert isinstance(body["warnings"], list)
    assert client.get("/api/state").json()["state"]["season"] == 2


def test_404_unknown_region(client: TestClient):
    r = client.post("/api/region/r99/recruit", json={"units": {"archer": 1}})
    assert r.status_code == 404 and "error" in r.json()


# ==================================================================== найм
def test_recruit_success_and_insufficient_gold(client: TestClient):
    r = client.post("/api/region/r01/recruit", json={"units": {"archer": 5}})
    assert r.status_code == 200
    body = r.json()
    assert body["cost"] == 300                    # 5 × 30 × 2
    assert body["gold"] == 200
    state = client.get("/api/state").json()["state"]
    assert state["treasury"]["gold"] == 200
    assert state["regions"]["r01"]["garrison"]["archer"]["count"] == 6 + 5
    # не хватает золота → 400 с ошибкой
    r = client.post("/api/region/r01/recruit", json={"units": {"knight": 9}})
    assert r.status_code == 400 and "error" in r.json()
    # чужой регион → 400
    r = client.post("/api/region/r07/recruit", json={"units": {"archer": 1}})
    assert r.status_code == 400


def test_buy_village_for_honour(client: TestClient):
    r = client.post("/api/region/r02/buy", json={})
    assert r.status_code == 200
    state = client.get("/api/state").json()["state"]
    assert state["regions"]["r02"]["owner"] == "player"
    assert state["treasury"]["honour"] == 0       # 100 − 100
    r = client.post("/api/region/r02/buy", json={})   # уже не нейтральная
    assert r.status_code == 400


# ==================================================================== бои
def test_battle_prepare_forecast(client: TestClient):
    r = client.post("/api/battle/prepare", json={"target_region": "r07"})
    assert r.status_code == 200
    body = r.json()
    assert body["target"] == "r07"
    assert body["transitions"] == "0/15"
    assert 0.0 <= body["p_win_autoresolve"] <= 1.0
    assert body["battle_type"] == "siege"          # castle_level r07 = 1


def test_battle_autoresolve_consistency(client: TestClient):
    r = client.post("/api/battle/autoresolve", json={"target_region": "r07"})
    assert r.status_code == 200
    body = r.json()
    assert body["winner"] in ("player", "l_hawk")
    assert 0.0 <= body["p_win_att"] <= 1.0
    state = client.get("/api/state").json()["state"]
    assert state["counters"]["battles_auto"] == 1
    # исход по сиду: либо захват, либо оборона держится — но консистентно
    r07 = state["regions"]["r07"]
    if body["winner"] == "player":
        assert r07["owner"] == "player" and r07["loyalty"] == 30
        assert st.roster_total(state["armies"]["army_01"]["roster"]) \
            == st.roster_total(body["survivors"]["player"])
    else:
        assert r07["owner"] == "l_hawk"
    # росписи неотрицательны
    for army in state["armies"].values():
        for rec in army["roster"].values():
            assert rec["count"] >= 0


def test_battle_scene_fallback_without_game_maps(client: TestClient):
    """Нет карт игры → ok=False + fallback autoresolve, но НЕ 500."""
    r = client.post("/api/battle/scene", json={"target_region": "r07"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert body["fallback"] == "autoresolve"
    assert body["reason"]
    state = client.get("/api/state").json()["state"]
    assert state["counters"]["transitions_used"] == 0   # переход не списан
    assert state["pending_scenes"] == []


def test_battle_scene_success_with_template(client: TestClient,
                                            monkeypatch):
    monkeypatch.setattr(scene_client, "template_for_role",
                        lambda role: FixtureTemplate())
    r = client.post("/api/battle/scene", json={"target_region": "r07"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["scene_id"].startswith("sc_")
    assert Path(body["map"]).exists()
    state = client.get("/api/state").json()["state"]
    assert state["counters"]["transitions_used"] == 1
    assert state["pending_scenes"][0]["scene_id"] == body["scene_id"]
    assert client.get("/api/scene/pending").json() == state["pending_scenes"]


def test_scene_result_manual_entry(client: TestClient):
    """Экран «Исход?» (07 §7.6): ручной ввод итога сцены."""
    state = client.app.state.state
    state["pending_scenes"].append(
        {"scene_id": "sc_99001", "target_region": "r07", "type": "siege",
         "attacker_lord": "player", "defender_lord": "l_hawk",
         "map": "S2TW_sc_00901_siege.s2m"})
    r = client.post("/api/scene/result", json={
        "scene_id": "sc_99001", "outcome": "win",
        "survivors": {"attacker": {"spearman": {"count": 15, "vet": 0.0}}}})
    assert r.status_code == 200
    body = r.json()
    assert body["captured"] is True
    state = client.get("/api/state").json()["state"]
    assert state["regions"]["r07"]["owner"] == "player"
    assert state["counters"]["battles_manual"] == 1
    assert state["counters"]["scenes_played"] == 1
    assert state["pending_scenes"] == []
    assert state["armies"]["army_01"]["located_region"] == "r07"


def test_scene_result_aborted_mercy(client: TestClient):
    state = client.app.state.state
    state["pending_scenes"].append(
        {"scene_id": "sc_99002", "target_region": "r07", "type": "siege",
         "attacker_lord": "player", "defender_lord": "l_hawk",
         "map": "x.s2m"})
    before = st.roster_total(state["armies"]["army_01"]["roster"])
    r = client.post("/api/scene/result", json={
        "scene_id": "sc_99002", "outcome": "aborted"})
    assert r.status_code == 200
    state = client.get("/api/state").json()["state"]
    assert st.roster_total(state["armies"]["army_01"]["roster"]) == before
    assert state["counters"]["aborted_streak"] == 1


# ============================================================== партия/undo
def test_undo_restores_previous_state(client: TestClient):
    client.post("/api/season/next", json={})               # сезон 1
    r = client.post("/api/undo", json={})
    assert r.status_code == 200 and r.json()["undone"] is True
    state = client.get("/api/state").json()["state"]
    assert state["season"] == 0                            # откат к слепку
    assert state["treasury"]["gold"] == 500
    assert state["counters"]["empty_seasons_streak"] == 0
    # второй undo без слепков → 400
    r = client.post("/api/undo", json={})
    assert r.status_code == 400


def test_request_id_idempotency(client: TestClient):
    r1 = client.post("/api/season/next", json={"request_id": "req-1"})
    assert r1.status_code == 200
    r2 = client.post("/api/season/next", json={"request_id": "req-1"})
    assert r2.status_code == 200
    assert r1.json() == r2.json()               # тот же ответ из кэша
    assert client.get("/api/state").json()["state"]["season"] == 1
    r3 = client.post("/api/season/next", json={"request_id": "req-2"})
    assert r3.json()["season"] == 2             # другой id — исполнилось
    assert client.get("/api/state").json()["state"]["season"] == 2


def test_save_and_load(client: TestClient, mini_campaign: Path):
    client.post("/api/season/next", json={})
    r = client.post("/api/save", json={})
    assert r.status_code == 200 and r.json()["saved"] is True
    assert (mini_campaign / "campaign_state.json").exists()
    r = client.get("/api/load/mini_v1")
    assert r.status_code == 200 and r.json()["state"]["season"] == 1
    r = client.get("/api/load/other_v1")
    assert r.status_code == 404


def test_history_and_events_journal(client: TestClient,
                                    mini_campaign: Path):
    client.post("/api/season/next", json={})
    history = list((mini_campaign / "history").glob("state_*.json"))
    assert any(p.name.endswith("_end.json") for p in history)
    journal = (mini_campaign / "events.jsonl").read_text(encoding="utf-8")
    assert "season_end" in journal


# ================================================================ дипломатия
def test_diplomacy_endpoints(client: TestClient):
    r = client.post("/api/diplomacy", json={"action": "war",
                                            "with": "l_hawk"})
    assert r.status_code == 200 and r.json()["state"] == "war"
    r = client.post("/api/diplomacy", json={"action": "alliance",
                                            "with": "l_hawk"})
    assert r.status_code == 400                     # союз только из мира
    r = client.post("/api/diplomacy", json={"action": "peace",
                                            "with": "l_hawk"})
    assert r.status_code == 200 and r.json()["state"] == "peace"
    r = client.post("/api/diplomacy", json={"action": "peace",
                                            "with": "l_ghost"})
    assert r.status_code == 400                     # неизвестный лорд


def test_offer_decide_battle_and_peace(client: TestClient):
    state = client.app.state.state
    state["pending_offers"].append(
        {"offer": "battle", "attacker": "l_hawk", "target_region": "r01",
         "season": 0})
    state["pending_offers"].append(
        {"offer": "peace", "from": "l_hawk", "season": 0})
    r = client.post("/api/offer/decide", json={"index": 1, "accept": True})
    assert r.status_code == 200
    state = client.get("/api/state").json()["state"]
    assert state["diplomacy"]["pairs"]["l_hawk|player"] == "peace"
    assert len(state["pending_offers"]) == 1
    r = client.post("/api/offer/decide", json={"index": 0, "accept": True})
    assert r.status_code == 200
    state = client.get("/api/state").json()["state"]
    assert state["counters"]["battles_auto"] == 1     # бой сыгран авто-резолвом
    assert state["pending_offers"] == []
    r = client.post("/api/offer/decide", json={"index": 5, "accept": True})
    assert r.status_code == 400
