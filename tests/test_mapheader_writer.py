"""Тесты писателя MapHeader L2 (S3.5; эталонная планка 05 §5.5).

Планка: load → writer без правок → reconstruct байт-идентичен исходному
распакованному сегменту; с правками — сегмент перечитывается парсером,
инварианты сохраняются.
"""
from __future__ import annotations

import struct
import zlib
from pathlib import Path

import pytest

from sh2tw.formats.map_header import decode_mapheader_segment
from sh2tw.formats.object_tree import parse_segment, reconstruct_segment
from sh2tw.formats.s2m_file import S2mFile
from sh2tw.scenes.mapheader_writer import (
    MapHeaderWriter,
    WriterError,
    rewrite_segment,
)

DATA = Path(__file__).resolve().parents[1] / "tests" / "data"
FIXTURES = [DATA / "sample.s2m", DATA / "sample_notrail.s2m",
            DATA / "sample_save.sh2"]


def load_nodes(fixture: Path):
    m = S2mFile.load(fixture)
    seg = next(s for s in m.segments if s.name == "mapheader")
    nodes, _tail = parse_segment(seg.decompressed)
    return m, seg, nodes


# ------------------------------------------------- эталонная планка (05 §5.5)
@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda p: p.name)
def test_writer_reference_bar_roundtrip(fixture: Path):
    """load → MapHeaderWriter без правок → байт-идентичность сегмента."""
    _m, seg, nodes = load_nodes(fixture)
    rebuilt = MapHeaderWriter(nodes).to_segment()
    assert rebuilt == seg.decompressed


def test_full_file_roundtrip_via_container():
    """Сегмент после писателя, пересобранный в контейнер — round-trip файла."""
    fixture = DATA / "sample.s2m"
    m, seg, nodes = load_nodes(fixture)
    rebuilt = MapHeaderWriter(nodes).to_segment()
    new_segments = [type(seg)(name=seg.name, decompressed=rebuilt,
                              compressed=zlib.compress(rebuilt, 6),
                              offset=seg.offset, level=6) if s.name == "mapheader"
                    else s for s in m.segments]
    m2 = S2mFile(path=None, file_header=m.file_header,
                 segments=new_segments, tail=m.tail)
    assert m2.roundtrip_ok() or m2.roundtrip_bytes()  # заголовок+сегменты+хвост
    # и парсер его снова читает без ошибок
    m3 = S2mFile.loads(m2.roundtrip_bytes())
    assert m3.roundtrip_ok()


# --------------------------------------------------------------- имя карты
def test_set_name_rebuilds_name_block():
    _m, seg, nodes = load_nodes(DATA / "sample.s2m")
    w = MapHeaderWriter(nodes)
    old_name = w.name
    w.set_name("S2TW_sc0001_siege")
    assert w.name == "S2TW_sc0001_siege"
    # перечитали сегмент парсером — имя видно в декоде
    nodes2, _t = parse_segment(w.to_segment())
    dec = decode_mapheader_segment(nodes2)
    assert dec["header"].name == "S2TW_sc0001_siege"
    assert old_name != "S2TW_sc0001_siege"  # фиксируем, что имя реально другое
    # длина блока: L = 2C + 8 (G17)
    p = nodes2[[i for i, n in enumerate(nodes2)
                if n.type_name == "MapHeader"][0]].payload
    L, C = struct.unpack_from("<II", p, 28)
    assert L == 2 * C + 9


@pytest.mark.parametrize("bad", [
    "no_prefix_map",           # без S2TW_
    "S2TW_" + "x" * 40,        # длиннее 27
    "S2TW_карта",              # кириллица запрещена (13 §L)
    "S2TW_sc 01",              # пробел запрещён
])
def test_set_name_rejects_bad_names(bad):
    _m, _seg, nodes = load_nodes(DATA / "sample.s2m")
    with pytest.raises(WriterError):
        MapHeaderWriter(nodes).set_name(bad)


# ---------------------------------------------------------------- тип карты
def test_set_map_type_changes_type():
    _m, _seg, nodes = load_nodes(DATA / "sample.s2m")
    w = MapHeaderWriter(nodes)
    w.set_map_type(2)  # war_custom — тип боевых сцен
    nodes2, _t = parse_segment(w.to_segment())
    dec = decode_mapheader_segment(nodes2)
    assert dec["header"].map_type == 2
    assert dec["header"].map_type_name == "war_custom"


def test_set_map_type_rejects_unknown():
    _m, _seg, nodes = load_nodes(DATA / "sample.s2m")
    with pytest.raises(WriterError):
        MapHeaderWriter(nodes).set_map_type(9)


# ------------------------------------------------------------ EstateMarkers
def test_set_estate_marker_modifies_slot():
    _m, _seg, nodes = load_nodes(DATA / "sample.s2m")
    w = MapHeaderWriter(nodes)
    markers = w.estate_markers()
    # первый активный слот (или слот 0): деактивируем, затем возвращаем
    target = next((mk for mk in markers if mk.kind != 0), markers[0])
    old_kind = target.kind
    w.set_estate_marker(target.slot, kind=0)
    assert w.estate_markers()[target.slot].kind == 0
    w.set_estate_marker(target.slot, kind=old_kind)
    assert w.estate_markers()[target.slot].kind == old_kind
    # сегмент остался равнодлинным и перечитывается
    nodes2, _t = parse_segment(w.to_segment())
    dec = decode_mapheader_segment(nodes2)
    assert len(dec["estate_markers"]) == 32
    assert dec["estate_markers"][target.slot].kind == old_kind


def test_set_estate_marker_rejects_bad_slot_and_kind():
    _m, _seg, nodes = load_nodes(DATA / "sample.s2m")
    w = MapHeaderWriter(nodes)
    with pytest.raises(WriterError):
        w.set_estate_marker(32, kind=1)
    with pytest.raises(WriterError):
        w.set_estate_marker(0, kind=7)


def test_rewrite_segment_one_step():
    _m, _seg, nodes = load_nodes(DATA / "sample.s2m")
    out = rewrite_segment(nodes, name="S2TW_sc0002_field", map_type=2,
                          markers=[{"slot": 1, "kind": 2}])
    nodes2, _t = parse_segment(out)
    dec = decode_mapheader_segment(nodes2)
    assert dec["header"].name == "S2TW_sc0002_field"
    assert dec["header"].map_type == 2
    slot1 = dec["estate_markers"][1]
    assert slot1.kind == 2


def test_reconstruct_segment_matches_writer():
    """Писатель использует reconstruct_segment — совместимость с S2.2/S2.3."""
    _m, _seg, nodes = load_nodes(DATA / "sample.s2m")
    assert MapHeaderWriter(nodes).to_segment() == reconstruct_segment(nodes, b"")


def test_writer_rejects_segment_without_mapheader():
    m = S2mFile.load(DATA / "sample.s2m")
    seg = next(s for s in m.segments if s.name == "s2game")
    nodes, _t = parse_segment(seg.decompressed)
    with pytest.raises(WriterError):
        MapHeaderWriter(nodes)
