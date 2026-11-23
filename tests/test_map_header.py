"""S2.4: семантика mapheader-сегмента (MapHeader, EstateMarkers) + кросс-ccылки."""
from __future__ import annotations

import pytest

from sh2tw.formats import object_tree as ot
from sh2tw.formats.map_header import decode_mapheader_segment
from sh2tw.formats.s2m_file import S2mFile
from sh2tw.paths import load_paths


def _mapheader_nodes(path):
    m = S2mFile.load(path)
    seg = next(s for s in m.segments if s.name == "mapheader")
    nodes, _trailer = ot.parse_segment(seg.decompressed)
    return nodes


def _corpus_maps():
    p = load_paths()
    roots = [p.maps_dir_game, p.maps_dir_user]
    files = []
    for root in roots:
        if root.exists():
            files += [f for f in sorted(root.rglob("*.s2m")) if f.is_file()]
    if not files:
        pytest.skip("нет карт корпуса")
    return files


def test_fixtures_chapter1_chapter8_markers():
    p = load_paths()
    d = p.maps_dir_game
    f1 = d / "war_chapter1.s2m"
    f8 = d / "war_chapter8.s2m"
    if not (f1.exists() and f8.exists()):
        pytest.skip("карты кампании не на месте")
    r1 = decode_mapheader_segment(_mapheader_nodes(f1))
    mk1 = r1["estate_markers"]
    assert len(mk1) == 32
    e1 = mk1[1]
    assert (e1.x, e1.z, e1.kind) == (151, 29, 2)  # дословно из OpenSH2 EstateMarkers.md
    r8 = decode_mapheader_segment(_mapheader_nodes(f8))
    mk8 = r8["estate_markers"]
    castles = {m.slot for m in mk8 if m.kind == 2}
    villages = {m.slot for m in mk8 if m.kind == 1}
    assert castles == {1, 2, 3, 10, 11}
    assert villages == {4, 5, 6, 7, 8, 9}


def test_mapheader_crossrefs_and_types_all_corpus_maps():
    seen = 0
    for f in _corpus_maps():
        r = decode_mapheader_segment(_mapheader_nodes(f))
        assert r["crossrefs_resolve"], f"{f.name}: id EstateMarkers/Scenario не резолвятся"
        hdr = r["header"]
        assert hdr.map_type in (0, 2, 3, 4), f"{f.name}: map_type {hdr.map_type}"
        assert hdr.name, f"{f.name}: пустое имя"
        # все маркеры валидны уже по декодеру (kind enum проверен там)
        seen += 1
    assert seen >= 60, f"карт разобрано {seen} — ожидали весь корпус"


def test_kingmaker_freebuild_enums_observed():
    # war-карты кампании: тип 2 (war custom). Проверим хотя бы одну.
    p = load_paths()
    f = p.maps_dir_game / "war_chapter1.s2m"
    if not f.exists():
        pytest.skip("нет war_chapter1")
    r = decode_mapheader_segment(_mapheader_nodes(f))
    assert r["header"].map_type_name in ("war_custom", "kingmaker")
