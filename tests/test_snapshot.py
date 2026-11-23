"""Тесты S2.6: snapshot_builder.py + CLI parse (ТЗ 04 §4.4, контракт 03 §3.5).

Инварианты:
1. sample.s2m и sample_save.sh2 дают валидные снимки формы 03 §3.5
   (schema_version, source.sha256, map, buildings/actors/estates, census,
   raw_unknown_objects; UNKNOWN — null + причина в unknown_fields).
2. Детерминизм: два декода одного файла -> байт-идентичный канонический JSON
   (parsed_at = mtime файла, списки по obj_id, sort_keys).
3. Счётчики снимка совпадают с census-API S2.5 (s2game.decode_s2game_nodes):
   s2game_types == census, raw_unknown_objects == len(raw_nodes),
   total == decoded + raw.
4. Живой корпус (skipif нет): war_chapter1.s2m из project.ini и первый здоровый
   сейв Saves/ (вне corrupt_saves.txt) распадаются в снимки без исключений.
5. CLI parse: exit 0 + валидный JSON по --out (включая '/tmp/...' -> temp),
   битый сейв из corrupt_saves.txt -> exit != 0 («падать ГРОМКО», 04 §4.7).
"""
from __future__ import annotations

import json
import tempfile
from collections import Counter
from pathlib import Path

import pytest

from sh2tw import cli
from sh2tw.formats import object_tree as ot
from sh2tw.formats import s2game as sg
from sh2tw.formats.s2m_file import S2mFile
from sh2tw.paths import load_paths
from sh2tw.snapshot_builder import (SCHEMA_VERSION, build_snapshot,
                                    parse_snapshot, resolve_out_path,
                                    snapshot_json)

REPO = Path(__file__).resolve().parents[1]
DATA = Path(__file__).parent / "data"
SAMPLE = DATA / "sample.s2m"
SAMPLE_SAVE = DATA / "sample_save.sh2"
CORRUPT_LIST = Path(__file__).parent / "corpus" / "corrupt_saves.txt"


def corrupt_names() -> set[str]:
    if not CORRUPT_LIST.is_file():
        return set()
    return {l.strip() for l in CORRUPT_LIST.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("#")}


def decode_model_direct(path: Path) -> sg.S2GameModel:
    """Независимый прогон S2.5 census-API (сверка счётчиков снимка)."""
    m = S2mFile.load(path)
    seg = next(s for s in m.segments if s.name == "s2game")
    nodes, _tail = ot.parse_segment(seg.decompressed)
    return sg.decode_s2game_nodes(nodes, path.name)


def assert_snapshot_shape(snap: dict) -> None:
    assert snap["schema_version"] == SCHEMA_VERSION == "1.0"
    assert len(snap["source"]["sha256"]) == 64
    assert snap["source"]["parsed_at"]  # mtime-детерминированный ISO
    assert json.loads(snapshot_json(snap)) == json.loads(snapshot_json(snap))
    for key in ("game_time_months", "lords", "population"):
        assert snap[key] is None, f"{key} обязан быть null (UNKNOWN, не выдумываем)"
        assert key in snap["unknown_fields"]
    assert snap["resources"]["gold_total_estimated"] is None
    assert snap["parse_errors"] == []
    b, a = snap["buildings"], snap["actors"]
    assert b and a, "размещений из S2.5-декодера нет"
    assert [r["obj_id"] for r in b] == sorted(r["obj_id"] for r in b)  # дет. порядок
    assert all(r["owner_lord"] is None and r["hp_pct"] is None and r["type_id"] is None
               for r in b), "UNKNOWN-поля buildings обязаны быть null"
    assert all(r["owner_lord"] is None and r["rotation"] is None for r in a)
    for est in snap["estates"]:
        assert est["owner_lord"] is None and est["product"] is None
    c = snap["census"]
    assert c["s2game_objects_total"] == sum(c["s2game_types"].values())
    assert (c["decoded_buildings"] + c["decoded_actors"]
            + int(c["heightlayer_decoded"]) + snap["raw_unknown_objects"]
            == c["s2game_objects_total"])
    assert 0.0 < c["coverage"] <= 1.0


def _assert_census_matches_entities_api(path: Path, snap: dict) -> None:
    model = decode_model_direct(path)
    c = snap["census"]
    assert dict(sorted(model.census.items())) == c["s2game_types"]
    assert sum(model.census.values()) == c["s2game_objects_total"]
    assert len(model.raw_nodes) == snap["raw_unknown_objects"]
    assert len(model.buildings) == c["decoded_buildings"]
    assert len(model.actors) == c["decoded_actors"]
    pc = Counter(p.class_name for p in model.placements)
    assert dict(sorted(pc.items())) == c["placement_census"]


# ---------------- фикстуры репозитория ----------------

def test_sample_map_snapshot():
    snap = build_snapshot(SAMPLE)
    assert_snapshot_shape(snap)
    assert snap["map"]["map_type_name"] == "peace_custom"
    assert snap["map"]["name"] == "(M1) Escape Home"  # ведущий слэш снят
    assert snap["map"]["mapsize_class"] == 128
    assert 0 < len(snap["estates"]) <= 32
    _assert_census_matches_entities_api(SAMPLE, snap)


def test_sample_save_snapshot():
    snap = build_snapshot(SAMPLE_SAVE)
    assert_snapshot_shape(snap)
    assert snap["map"]["map_type_name"] == "war_custom"
    assert snap["map"]["name"] == "TheNewFrontier"
    _assert_census_matches_entities_api(SAMPLE_SAVE, snap)


@pytest.mark.parametrize("fx", [SAMPLE, SAMPLE_SAVE], ids=["map", "save"])
def test_determinism_byte_identical(fx: Path):
    j1 = snapshot_json(build_snapshot(fx))
    j2 = snapshot_json(build_snapshot(fx))
    assert j1 == j2, "два декода одного файла обязаны давать байт-идентичный JSON"


def test_parse_snapshot_writes_file(tmp_path: Path):
    out = tmp_path / "sub" / "snap.json"
    snap = parse_snapshot(SAMPLE, out)
    assert out.is_file()
    assert json.loads(out.read_text(encoding="utf-8")) == snap  # canonical round-trip


def test_resolve_out_path(tmp_path: Path):
    r = resolve_out_path("/tmp/snap.json")
    assert r == Path(tempfile.gettempdir()) / "snap.json"
    real = tmp_path / "custom.json"
    assert resolve_out_path(str(real)) == real  # обычный путь — без изменений
    assert str(resolve_out_path("rel.json")) == "rel.json"


# ---------------- живой корпус (skipif нет) ----------------

def find_game_map() -> Path | None:
    p = load_paths()
    for d in (p.maps_dir_game, p.maps_dir_user):
        f = d / "war_chapter1.s2m"
        if f.is_file():
            return f
    return None


def find_healthy_save() -> Path | None:
    d = load_paths().saves_dir
    if not d.is_dir():
        return None
    bad = corrupt_names()
    # детерминированный выбор: сортировка по имени без учёта регистра
    for f in sorted((f for f in d.rglob("*.sh2") if f.is_file()),
                    key=lambda p: p.name.lower()):
        if f.name not in bad:
            return f
    return None


def test_real_game_map_war_chapter1():
    mp = find_game_map()
    if mp is None:
        pytest.skip("war_chapter1.s2m нет в maps_dir_game/user (project.ini)")
    snap = build_snapshot(mp)
    assert snap["map"]["name"], "имя карты из MapHeader пустое"
    assert snap["buildings"], "на живой карте нет ни одного Building-52 размещения"
    assert not snap["parse_errors"]
    _assert_census_matches_entities_api(mp, snap)
    assert snap["census"]["coverage"] > 0.15


def test_real_healthy_save():
    sp = find_healthy_save()
    if sp is None:
        pytest.skip("в Saves/ нет здоровых .sh2 (project.ini / corrupt_saves.txt)")
    snap = build_snapshot(sp)
    assert_snapshot_shape(snap)
    _assert_census_matches_entities_api(sp, snap)


# ---------------- CLI parse ----------------

def test_cli_parse_out_to_tmp_mapping(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(REPO)  # tests/data/sample.s2m — из корня репозитория
    name = "snap_test_s26.json"
    rc = cli.main(["parse", "tests/data/sample.s2m", "--out", f"/tmp/{name}"])
    assert rc == 0
    out = resolve_out_path(f"/tmp/{name}")
    assert out == Path(tempfile.gettempdir()) / name
    try:
        doc = json.loads(out.read_text(encoding="utf-8"))
        assert doc["schema_version"] == "1.0"
        assert doc["census"]["s2game_objects_total"] > 0
    finally:
        out.unlink(missing_ok=True)


def test_cli_parse_out_custom_path(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(REPO)
    out = tmp_path / "a b" / "snap.json"  # пробел в каталоге — путь не должен ломаться
    rc = cli.main(["parse", "tests/data/sample.s2m", "--out", str(out)])
    assert rc == 0
    assert json.loads(out.read_text(encoding="utf-8"))["schema_version"] == "1.0"


def test_cli_parse_stdout_json_without_out(monkeypatch, capsys):
    monkeypatch.chdir(REPO)
    rc = cli.main(["parse", "tests/data/sample.s2m"])
    assert rc == 0
    doc = json.loads(capsys.readouterr().out)  # без --out — полный снимок в stdout
    assert doc["schema_version"] == "1.0"


def test_cli_parse_corrupt_save_fails_loudly(monkeypatch, capsys):
    monkeypatch.chdir(REPO)
    p = load_paths()
    name = next(iter(sorted(corrupt_names())))
    by_name = {f.name: f for f in p.saves_dir.rglob("*.sh2")}  # сейвы ищутся рекурсивно
    f = by_name.get(name)
    if f is None:
        pytest.skip(f"{name} нет в Saves/")
    rc = cli.main(["parse", str(f), "--out", "unused.json"])
    assert rc == 1  # 04 §4.7: битый файл — падать быстро и ГРОМКО
    assert "ОШИБКА РАЗБОРА" in capsys.readouterr().err
