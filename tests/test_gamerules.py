"""Тесты S2.9: gameRules.dat round-trip + нод-дерево (04 §4.3, §4.7; G4/G5, 13 §G).

Корпус: gamerules*.dat в game_dir (факт: один gameRules.dat, 2111 B).
Инварианты: (1) loads → roundtrip_bytes() побайтово == исходник; (2)
распакованный сегмент — дерево объектов, reconstruct_segment() == сегмент
(object_tree, G15-синтаксис); (3) на обрезке потока — громкая Sh2ParseError.

Расхождение с G4 («2111 байт заголовка → zlib»): замер — файл 2111 B ЦЕЛИКОМ,
zlib начинается с байта 0, после потока 73 B сырого хвоста; фиксация в
docstring gamerules.py и в фактах отчёта задачи (файл игры authoritative, 00 §3).
"""
from __future__ import annotations

import zlib
from pathlib import Path

import pytest

from sh2tw.formats import object_tree as ot
from sh2tw.formats.gamerules import GameRulesFile
from sh2tw.formats.s2m_file import Sh2ParseError
from sh2tw.paths import load_paths


def gamerules_corpus() -> list[Path]:
    g = load_paths().game_dir
    if not g.is_dir():
        return []
    return sorted(f for f in g.rglob("*.dat")
                  if f.name.lower().startswith("gamerules") and f.is_file())


def need_corpus() -> list[Path]:
    files = gamerules_corpus()
    if not files:
        pytest.skip("gameRules*.dat нет в корпусе (другая машина)")
    return files


# --- корпус: round-trip байт-в-байт -----------------------------------------

def test_corpus_roundtrip_byte_exact():
    bad = []
    for f in need_corpus():
        blob = f.read_bytes()
        gf = GameRulesFile.load(f)
        if not gf.roundtrip_ok() or gf.roundtrip_bytes() != blob:
            bad.append(f.name)
    assert not bad, f"round-trip != исходник: {bad}"


def test_layout_zlib_at_zero_raw_tail():
    # Факт корпуса против буквы G4: заголовка нет, поток с байта 0, хвост —
    # сырые байты после потока (не zlib).
    for f in need_corpus():
        blob = f.read_bytes()
        gf = GameRulesFile.load(f)
        assert gf.header_raw == b"", f"{f.name}:Unexpected header_raw {len(gf.header_raw)}"
        assert gf.compressed[:2] == b"\x78\x9c"
        assert blob.startswith(gf.compressed)
        assert gf.tail and not _looks_zlib(gf.tail), f"{f.name}: хвост не зафиксирован как не-zlib"
        assert len(gf.compressed) + len(gf.tail) == len(blob)
        d = zlib.decompressobj()
        assert d.decompress(blob).startswith(b"\x1e\xab\xa1\x5c")  # magic-пара G15


def _looks_zlib(b: bytes) -> bool:
    if len(b) < 2:
        return False
    try:
        zlib.decompressobj().decompress(b)
        return True
    except zlib.error:
        return False


# --- нод-дерево (переиспользование object_tree) ------------------------------

def test_object_tree_walk_and_rebuild():
    gf = GameRulesFile.load(need_corpus()[0])
    nodes = gf.nodes()
    assert ot.reconstruct_segment(nodes, b"") == gf.decompressed
    types = {n.type_name for n in nodes}
    assert types == {"GameRules", "LordsRules"}, types
    assert len(gf.lords_rules) == 21, "21 профиль лордов (факт корпуса)"
    assert gf.game_rules_node.type_name == "GameRules"
    # семантика полей LordsRules не задокументирована → payload сырой,
    # ничего не декодируем и не правим (# UNKNOWN(offsets) в gamerules.py)
    assert all(n.payload for n in gf.lords_rules)


def test_decompressed_shape_facts():
    gf = GameRulesFile.load(need_corpus()[0])
    assert len(gf.decompressed) == 22092  # замер корпуса 23.11.2026
    assert gf.decompressed[-8:] == ot.END_OBJ + ot.END_SEG
    assert gf.decompressed.count(ot.END_SEG) == 1


# --- уровень сжатия (образец корректной переупаковки — G5/Lord Editor) ------

def test_compression_level_exact():
    gf = GameRulesFile.load(need_corpus()[0])
    lvl = gf.find_compression_level()
    assert lvl == 6, f"факт корпуса: уровень 6 воспроизводит поток, получено {lvl}"
    assert zlib.compress(gf.decompressed, lvl) == gf.compressed
    assert lvl == gf.find_compression_level()  # кэш идемпотентен


# --- мутационная устойчивость ------------------------------------------------

def test_truncated_stream_fails_loudly():
    blob = need_corpus()[0].read_bytes()
    for cut in (blob[:1500], blob[:10], blob[:1000]):
        with pytest.raises(Sh2ParseError):
            GameRulesFile.loads(cut)


def test_garbage_fails_loudly():
    for junk in (b"", b"AAAA", b"\x00" * 200):
        with pytest.raises(Sh2ParseError):
            GameRulesFile.loads(junk)


# --- синтетика: допущенный префикс-заголовок (G4-вариант) + идемпотентность --

def test_synthetic_prefixed_variant_roundtrip():
    gf = GameRulesFile.load(need_corpus()[0])
    variant = b"OPTS-prefix-simulating-G4-header\x00\x00" + zlib.compress(
        gf.decompressed, 6) + gf.tail
    m = GameRulesFile.loads(variant)
    assert m.header_raw.startswith(b"OPTS-prefix")
    assert m.roundtrip_ok() and m.roundtrip_bytes() == variant
    assert len(m.lords_rules) == 21
    # разбор одного и того же файла дважды — идемпотентно
    again = GameRulesFile.loads(variant)
    assert again.as_dict() == m.as_dict() or [n.as_dict() for n in again.nodes()] == \
        [n.as_dict() for n in m.nodes()]
