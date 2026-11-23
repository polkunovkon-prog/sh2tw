"""Тесты S2.7: diff_engine.py + CLI diff (ТЗ 04 §4.2/§4.6, контракт 03 §3.6 карман).

Инварианты:
1. sample.s2m vs sample_save.sh2 — реальный непустой diff; счётчики summary
   связаны с НЕЗАВИСИМО пересчитанными set(obj_id) из списков снимков и с
   census-API S2.5 (s2game.decode_s2game_nodes), а не с движком diff.
2. self-diff пуст: summary.empty, все списки/дельты пусты — на двух
   независимых разборах одного файла (dict-путь и json-файл-путь).
3. Детерминизм: одна и та же пара дважды (снимки пересобраны) ->
   байт-идентичный canonical JSON; запись в два файла — байт-в-байт.
4. Живой корпус (честный skipif): в Saves/ есть пара здоровых сейвов одной
   карты (шаблон имени *_Start_N/*_Restart_N, пара вне corrupt_saves.txt);
   diff такой пары непустой и непротиворечивый.
5. UNKNOWN(null)-vs-null переходы — НЕ изменения; map=null на одной стороне
   фиксируется как map_available, без выдуманных дельт полей.
6. CLI diff: файл-к-файлу end-to-end (.s2m+.sh2 и пара snapshot.json),
   stdout-режим без --out, битый сейв -> exit 1 «ГРОМКО» (04 §4.7).
"""
from __future__ import annotations

import copy
import json
import re
from collections import Counter
from pathlib import Path

import pytest

from sh2tw import cli
from sh2tw.diff_engine import (DIFF_SCHEMA_VERSION, diff_dicts, diff_json,
                               diff_snapshots, load_snapshot)
from sh2tw.formats import object_tree as ot
from sh2tw.formats import s2game as sg
from sh2tw.paths import load_paths
from sh2tw.snapshot_builder import build_snapshot, parse_snapshot

REPO = Path(__file__).resolve().parents[1]
DATA = Path(__file__).parent / "data"
SAMPLE = DATA / "sample.s2m"
SAMPLE_SAVE = DATA / "sample_save.sh2"
CORRUPT_LIST = Path(__file__).parent / "corpus" / "corrupt_saves.txt"

SAVE_PAIR_RE = re.compile(r"^(?P<stem>.+)_(?P<kind>Start|Restart)_(?P<idx>\d+)$")


def corrupt_names() -> set[str]:
    if not CORRUPT_LIST.is_file():
        return set()
    return {l.strip() for l in CORRUPT_LIST.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("#")}


def decode_model_direct(path: Path) -> sg.S2GameModel:
    """Независимый прогон S2.5 census-API (сверка счётчиков diff)."""
    from sh2tw.formats.s2m_file import S2mFile
    m = S2mFile.load(path)
    seg = next(s for s in m.segments if s.name == "s2game")
    nodes, _tail = ot.parse_segment(seg.decompressed)
    return sg.decode_s2game_nodes(nodes, path.name)


def placement_ids(snap: dict, section: str) -> set[int]:
    return {r["obj_id"] for r in snap[section]}


def placement_rows(snap: dict) -> dict[int, dict]:
    out: dict[int, dict] = {}
    for sec in ("buildings", "actors"):
        for r in snap[sec]:
            out[r["obj_id"]] = r
    return out


def recompute_placement_counts(sa: dict, sb: dict) -> dict[str, dict[str, int]]:
    """Независимый пересчёт added/removed/changed из массивов снимков."""
    res: dict[str, dict[str, int]] = {}
    for sec in ("buildings", "actors"):
        ia = {r["obj_id"]: r for r in sa[sec]}
        ib = {r["obj_id"]: r for r in sb[sec]}
        changed = sum(1 for k in set(ia) & set(ib) if ia[k] != ib[k])
        res[sec] = {"added": len(set(ib) - set(ia)), "removed": len(set(ia) - set(ib)),
                    "changed": changed,
                    "unchanged": len(set(ia) & set(ib)) - changed}
    return res


# ---------------- реальный diff фикстур репозитория ----------------

def test_real_diff_sample_map_vs_sample_save():
    sa, sb = build_snapshot(SAMPLE), build_snapshot(SAMPLE_SAVE)
    doc = diff_dicts(sa, sb)
    assert doc["schema_version"] == DIFF_SCHEMA_VERSION == "1.0"
    assert doc["summary"]["empty"] is False
    # счётчики — к независимому пересчёту по set(obj_id) из списков снимков
    assert doc["summary"]["buildings"] == recompute_placement_counts(sa, sb)["buildings"]
    assert doc["summary"]["actors"] == recompute_placement_counts(sa, sb)["actors"]
    assert (doc["summary"]["buildings"]["added"] > 0
            and doc["summary"]["buildings"]["removed"] > 0)
    # added/removed/changed непротиворечивы самим спискам документа
    pl = doc["placements"]["buildings"]
    assert {r["obj_id"] for r in pl["added"]} == placement_ids(sb, "buildings") - placement_ids(sa, "buildings")
    assert {r["obj_id"] for r in pl["removed"]} == placement_ids(sa, "buildings") - placement_ids(sb, "buildings")
    assert len(pl["changed"]) == doc["summary"]["buildings"]["changed"]

    # census — к независимому census-API (S2.5), а не к diff-движку
    ma, mb = decode_model_direct(SAMPLE), decode_model_direct(SAMPLE_SAVE)
    cd = doc["census_deltas"]
    ca, cb = dict(ma.census), dict(mb.census)
    assert cd["s2game_objects_total"] == {
        "from": sum(ca.values()), "to": sum(cb.values())}
    expected_types = {f"s2game_types.{t}": {"from": ca.get(t), "to": cb.get(t)}
                      for t in sorted(set(ca) | set(cb)) if ca.get(t) != cb.get(t)}
    assert {k: v for k, v in cd.items() if k.startswith("s2game_types.")} == expected_types
    assert expected_types, "census-дельты по типам пустые — фикстуры рассинхронизировались"
    # parse_errors у здоровых фикстур пусты, но секция обязана присутствовать
    assert doc["parse_errors"] == {"from": [], "to": []}
    # map-секции раскоданы на обеих — map_deltas это дельты полей, не map_available
    # map_deltas — плоские ключи, скоуп — секция (без «map.»; как в census_deltas)
    assert "map_available" not in doc["map_deltas"]
    assert doc["map_deltas"]["name"]["to"] == "TheNewFrontier"


def test_changed_rows_carry_class_and_position_deltas():
    # changed-строки реально есть у живых пар сейвов одной карты (замер V3),
    # а не у пары фикстур разных карт (там пересекающихся obj_id-построек 0).
    for pa, pb in same_map_pair_candidates()[:3]:
        sa, sb = build_snapshot(pa), build_snapshot(pb)
        name_a = (sa.get("map") or {}).get("name")
        name_b = (sb.get("map") or {}).get("name")
        if name_a is None or name_a != name_b:
            continue
        doc = diff_dicts(sa, sb)
        rows_a, rows_b = placement_rows(sa), placement_rows(sb)
        for sec in ("buildings", "actors"):
            for row in doc["placements"][sec]["changed"]:
                ra, rb = rows_a[row["obj_id"]], rows_b[row["obj_id"]]
                for f, d in row["deltas"].items():
                    assert d["from"] == ra.get(f) and d["to"] == rb.get(f)
        changed = doc["placements"]["buildings"]["changed"] + \
            doc["placements"]["actors"]["changed"]
        if not changed:
            continue
        pos = [r for r in changed if "x" in r["deltas"] or "z" in r["deltas"]]
        assert pos, "changed-строки есть, но без позиционных дельт"
        return
    pytest.skip("в Saves/ нет пары одной карты с changed-размещениями — форсировать не будем")


# ---------------- self-diff ----------------

def test_self_diff_empty_dict_path():
    d1, d2 = build_snapshot(SAMPLE), build_snapshot(SAMPLE)  # два независимых разбора
    doc = diff_dicts(d1, d2)
    assert doc["summary"]["empty"] is True
    for sec in ("buildings", "actors", "estates"):
        s = doc["summary"][sec]
        assert s == {"added": 0, "removed": 0, "changed": 0, "unchanged": s["unchanged"]}
        assert doc["placements"].get(sec, doc["estates"])["added"] == []
        assert doc["placements"].get(sec, doc["estates"])["removed"] == []
        assert doc["placements"].get(sec, doc["estates"])["changed"] == []
    assert doc["census_deltas"] == {} and doc["map_deltas"] == {}
    assert doc["container_deltas"] == {} and doc["parse_errors"] == {"from": [], "to": []}
    assert doc["delta_months"] is None


def test_self_diff_empty_json_file_path(tmp_path: Path):
    f1, f2 = tmp_path / "a.json", tmp_path / "b.json"
    parse_snapshot(SAMPLE, f1)
    parse_snapshot(SAMPLE, f2)
    doc = diff_snapshots(f1, f2)
    assert doc["summary"]["empty"] is True
    # сам JSON-путь загрузки даёт те же снимки
    assert load_snapshot(f1) == load_snapshot(f2) == build_snapshot(SAMPLE)


# ---------------- детерминизм ----------------

def test_determinism_same_pair_twice_byte_identical():
    # снимки пересобираются заново — diff обязан совпасть байт-в-байт
    d1 = diff_json(diff_dicts(build_snapshot(SAMPLE), build_snapshot(SAMPLE_SAVE)))
    d2 = diff_json(diff_dicts(build_snapshot(SAMPLE), build_snapshot(SAMPLE_SAVE)))
    assert d1 == d2, "две сборки diff одной пары не байт-идентичны"


def test_determinism_out_files_byte_identical(tmp_path: Path):
    o1, o2 = tmp_path / "d1.json", tmp_path / "d2.json"
    diff_snapshots(SAMPLE, SAMPLE_SAVE, o1)
    diff_snapshots(SAMPLE, SAMPLE_SAVE, o2)
    assert o1.read_bytes() == o2.read_bytes()


# ---------------- честность UNKNOWN и синтетика ----------------

def test_unknown_null_vs_null_is_not_a_change():
    base = build_snapshot(SAMPLE)
    other = copy.deepcopy(base)
    # трогать UNKNOWN-поля «в тот же null» — изменений быть не должно
    for r in other["buildings"]:
        r["owner_lord"] = None
        r["hp_pct"] = None
        r["type_id"] = None
    for r in other["actors"]:
        r["owner_lord"] = None
    for e in other["estates"]:
        e["owner_lord"] = None
        e["product"] = None
    other["lords"] = None
    other["population"] = None
    doc = diff_dicts(base, other)
    assert doc["summary"]["empty"] is True, "UNKNOWN(null) vs null не обязан быть пустым diff"


def test_changed_row_and_map_available_synthetic():
    base = build_snapshot(SAMPLE)
    other = copy.deepcopy(base)
    r0 = other["buildings"][0]
    r0["x"] = r0["x"] + 1.0
    other["map"] = None  # «mapheader не раскодан» на одной стороне
    doc = diff_dicts(base, other)
    assert doc["map_deltas"] == {"map_available": {"from": True, "to": False}}
    ch = doc["placements"]["buildings"]["changed"]
    assert len(ch) == 1
    assert ch[0]["obj_id"] == base["buildings"][0]["obj_id"]
    assert ch[0]["deltas"] == {"x": {"from": base["buildings"][0]["x"],
                                     "to": base["buildings"][0]["x"] + 1.0}}
    assert doc["summary"]["empty"] is False


# ---------------- живой корпус: пара сейвов одной карты ----------------

def same_map_pair_candidates() -> list[tuple[Path, Path]]:
    """Здоровые пары *_Start_N / *_Restart_N (один stem) из Saves/ (и подкаталогов
    типа Restarts/). Детерминированный порядок: stem.lower(), затем idx."""
    d = load_paths().saves_dir
    if not d.is_dir():
        return []
    bad = corrupt_names()
    groups: dict[str, list[tuple[int, Path]]] = {}
    for f in d.rglob("*.sh2"):
        if not f.is_file() or f.name in bad:
            continue
        m = SAVE_PAIR_RE.match(f.stem)
        if m:
            groups.setdefault(m.group("stem").lower(), []).append((int(m.group("idx")), f))
    pairs: list[tuple[Path, Path]] = []
    for stem in sorted(groups):
        members = sorted(groups[stem])
        if len(members) >= 2:
            pairs.append((members[0][1], members[-1][1]))
    return pairs


def test_real_save_pair_same_map_of_the_same_session():
    cands = same_map_pair_candidates()
    if not cands:
        pytest.skip("в Saves/ нет здоровой пары сейвов одной карты (*_Start_N/*_Restart_N)")
    chosen = None
    for pa, pb in cands[:3]:  # первые кандидаты детерминированы сортировкой
        sa, sb = build_snapshot(pa), build_snapshot(pb)
        name_a = (sa.get("map") or {}).get("name")
        name_b = (sb.get("map") or {}).get("name")
        if name_a is None or name_b is None or name_a != name_b:
            continue
        doc = diff_dicts(sa, sb)
        if doc["summary"]["empty"]:
            continue
        chosen = (pa, pb, sa, sb, doc)
        break
    if chosen is None:
        pytest.skip("кандидаты одной карты не дали непустого diff — форсировать не будем")
    pa, pb, sa, sb, doc = chosen
    # непротиворечивость к независимому пересчёту по массивам снимков
    exp = recompute_placement_counts(sa, sb)
    assert doc["summary"]["buildings"] == exp["buildings"]
    assert doc["summary"]["actors"] == exp["actors"]
    assert doc["parse_errors"] == {"from": [], "to": []}  # пара обязана быть здоровой
    # census total привязан к независимому census-API
    tot_a = sum(decode_model_direct(pa).census.values())
    tot_b = sum(decode_model_direct(pb).census.values())
    assert doc["census_deltas"]["s2game_objects_total"] == {"from": tot_a, "to": tot_b}
    # map одного имени — дельты поля name в map_deltas быть не должно
    assert ("name" not in doc["map_deltas"])


# ---------------- CLI diff ----------------

def test_cli_diff_raw_files_end_to_end(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.chdir(REPO)
    out = tmp_path / "diffs" / "events.json"
    rc = cli.main(["diff", "tests/data/sample.s2m", "tests/data/sample_save.sh2",
                   "--out", str(out)])
    assert rc == 0
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["schema_version"] == "1.0"
    assert doc["summary"]["empty"] is False
    rep = json.loads(capsys.readouterr().out)
    assert rep["out"] == str(out) and rep["summary"]["empty"] is False
    # пересчёт из массивов самих снимков (независимо от diff_engine)
    sa, sb = build_snapshot(SAMPLE), build_snapshot(SAMPLE_SAVE)
    assert doc["summary"]["buildings"] == recompute_placement_counts(sa, sb)["buildings"]


def test_cli_diff_two_snapshot_jsons_and_stdout(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.chdir(REPO)
    fa, fb = tmp_path / "a.json", tmp_path / "b.json"
    parse_snapshot(SAMPLE, fa)
    parse_snapshot(SAMPLE_SAVE, fb)
    rc = cli.main(["diff", str(fa), str(fb)])  # без --out — полный diff-документ в stdout
    assert rc == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["schema_version"] == "1.0" and doc["summary"]["empty"] is False
    # json-вход эквивалентен file-входу
    assert diff_json(doc) == diff_json(diff_dicts(build_snapshot(SAMPLE),
                                                  build_snapshot(SAMPLE_SAVE)))


def test_cli_diff_corrupt_save_fails_loudly(monkeypatch, capsys):
    monkeypatch.chdir(REPO)
    p = load_paths()
    name = next(iter(sorted(corrupt_names())), None)
    if name is None:
        pytest.skip("corrupt_saves.txt пуст")
    by_name = {f.name: f for f in p.saves_dir.rglob("*.sh2")}
    f = by_name.get(name)
    if f is None:
        pytest.skip(f"{name} нет в Saves/")
    rc = cli.main(["diff", str(f), str(SAMPLE_SAVE), "--out", "unused.json"])
    assert rc == 1  # 04 §4.7: битый файл — падать ГРОМКО, не молча
    assert "ОШИБКА DIFF" in capsys.readouterr().err
