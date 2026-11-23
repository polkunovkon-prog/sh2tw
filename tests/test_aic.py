"""Тесты S2.9: .aic round-trip по корпусу игры (04 §4.3, §4.7 «AIC»; F4, 13 §F).

Инвариант: для КАЖДОГО файла корпуса loads → roundtrip_bytes() побайтово ==
исходник. 4 обрезанных тестовых файла поставки (AIC.md: «four shipped test
files are truncated») — исключение с причиной, и отдельный тест подтверждает,
что исключение = реальная порча (len < 2928+8N), а парсер на них падает
громко (Sh2ParseError), не «чинит» молча — паттерн corrupt_saves.txt из
tests/test_object_tree.py.
"""
from __future__ import annotations

import struct
from pathlib import Path

import pytest

from sh2tw.formats.aic import (SIZE_BASE, AicFile, KEEP_KINDS, decode_point)
from sh2tw.formats.s2m_file import Sh2ParseError
from sh2tw.paths import load_paths

# AIC.md (строка 33): «Of the 47 installed files, 43 contain the complete
# layout; four shipped test files are truncated». Имена подтверждены замером
# корпуса (см. test_truncated_set_matches_docs).
DOC_TRUNCATED = {"test.aic", "test2.aic", "TEST3.aic", "test4.aic"}
CORPUS_TOTAL_EXPECTED = 47  # G12: «47 .aic» в копии заказчика


def aic_corpus() -> list[Path]:
    g = load_paths().game_dir
    if not g.is_dir():
        return []
    return sorted(f for f in g.rglob("*.aic") if f.is_file())


def truncation_of(f: Path) -> int | None:
    """None, если файл целый (len == 2928+8N), иначе дефицит байт."""
    b = f.read_bytes()
    n, = struct.unpack_from("<I", b, 0)
    need = SIZE_BASE + 8 * n
    return None if len(b) == need else need - len(b)


def need_corpus():
    files = aic_corpus()
    if not files:
        pytest.skip("живого корпуса .aic нет (другая машина)")
    return files


# --- корпус: формула, round-trip, обрезанные --------------------------------

def test_formula_holds_for_healthy_corpus():
    # F4 «2928+8N» перепроверен, а не принят на веру (память оркестратора).
    files = need_corpus()
    healthy = [f for f in files if truncation_of(f) is None]
    assert len(healthy) == CORPUS_TOTAL_EXPECTED - len(DOC_TRUNCATED), \
        f"здоровых файлов: {len(healthy)} (ожидалось 43 при корпусе {CORPUS_TOTAL_EXPECTED})"


def test_truncated_set_matches_docs():
    files = need_corpus()
    detected = {f.name for f in files if truncation_of(f) is not None}
    assert detected == DOC_TRUNCATED, f"обрезанные: {sorted(detected)}"
    for f in files:
        if f.name in DOC_TRUNCATED:
            deficit = truncation_of(f)
            assert deficit and deficit > 0, f"{f.name}: порча не подтверждена"


def test_truncated_fail_loudly_not_silently():
    for f in need_corpus():
        if f.name in DOC_TRUNCATED:
            with pytest.raises(Sh2ParseError):
                AicFile.load(f)


def test_corpus_roundtrip_byte_exact():
    bad, ok = [], 0
    for f in need_corpus():
        if f.name in DOC_TRUNCATED:
            continue
        blob = f.read_bytes()
        model = AicFile.load(f)
        assert model.n == struct.unpack_from("<I", blob, 0)[0]
        if not model.roundtrip_ok():
            bad.append(f.name)
        ok += 1
    assert not bad, f"round-trip != исходник: {bad}"
    assert ok == CORPUS_TOTAL_EXPECTED - len(DOC_TRUNCATED)


# --- докованные верифицированные примеры (AIC.md, строки 36-38) -------------

def test_docs_verified_example_olaf():
    g = load_paths().game_dir / "castles" / "AIVChap6_Olaf.aic"
    if not g.is_file():
        pytest.skip("карта/шаблон есть только на игровой машине")
    a = AicFile.load(g)
    assert a.n == 90
    e = a.entries[0]
    # «0x00283014, 0x00000001: wooden keep at local (48,40), rotation 0, group 1»
    assert (e.word0, e.word1) == (0x00283014, 0x00000001)
    assert (e.kind, e.x, e.z, e.rotation, e.group) == (20, 48, 40, 0, 1)
    assert e.is_keep and KEEP_KINDS[e.kind] == "wooden"
    pk = a.primary_keep
    assert pk is not None and pk.is_keep
    assert pk is a.keep_entries[-1]  # «PrimaryKeep returns the last keep entry»


def test_primary_keep_edwin_small():
    g = load_paths().game_dir / "castles" / "AIVChap6_Edwin.aic"
    if not g.is_file():
        pytest.skip("шаблон есть только на игровой машине")
    a = AicFile.load(g)
    # «AIVChap6_Edwin.aic begins with a small keep» — small = 21
    assert a.entries[0].kind == 21


def test_keep_kinds_present_across_corpus():
    found = set()
    for f in need_corpus():
        if f.name in DOC_TRUNCATED:
            continue
        for e in AicFile.load(f).entries:
            if e.is_keep:
                found.add(e.kind)
    assert {20, 21, 22, 23} <= found, f"kind'ы донжонов: {sorted(found)}"


# --- синтетика: поля, extension, детерминизм --------------------------------

def _synthetic(with_extension: bool = False) -> bytes:
    n = 2
    out = bytearray(struct.pack("<I", n))
    out += struct.pack("<II", 0x0102_0314, 0xAB01_0203)  # kind20 x3 z2 rot1 grp0x203 par1 hi0xAB
    out += struct.pack("<II", 0x0304_05C8, 0x00FF_0001)  # kind 200 (неизвестный — сохраняется)
    out += struct.pack("<50I", *(0xFFFFFFFF if i % 2 else 0x12345678 for i in range(50)))
    out += struct.pack("<I", 100)
    pts = [(i - 120) * 101 if i % 7 else 0 for i in range(240)]   # вкл. отрицательные
    out += struct.pack("<240i", *pts)
    out += struct.pack("<200i", *(0 if i % 5 else 6651 for i in range(200)))
    out += struct.pack("<240i", *([i % 2 for i in range(240)]))
    assert len(out) == SIZE_BASE + 8 * n
    if with_extension:
        out += b"\xde\xad\xbe\xef" * 3
    return bytes(out)


def test_synthetic_fields_and_roundtrip():
    blob = _synthetic()
    a = AicFile.loads(blob)
    assert a.n == 2 and len(a.entries) == 2
    e0, e1 = a.entries
    # word0 0x01020314: байты младший→старший 14 03 02 01 = kind/x/z/rot
    assert (e0.kind, e0.x, e0.z, e0.rotation) == (0x14, 3, 2, 1)
    assert (e0.group, e0.param, e0.high) == (0x0203, 0x01, 0xAB)
    assert e0.is_keep and e0.kind == 20
    assert a.extra_value == 100
    assert a.general_values[1] == 0xFFFFFFFF and a.general_values[0] == 0x12345678
    assert any(v < 0 for v in a.list_points)
    assert a.list_flags[:4] == [0, 1, 0, 1]
    assert e1.kind == 200 and not e1.is_keep  # неизвестный kind не отбрасывается
    assert a.roundtrip_ok() and a.roundtrip_bytes() == blob
    assert decode_point(6651) == (51, 66) and decode_point(0) is None
    assert decode_point(-6651) is None  # UNKNOWN(отрицательная кодировка)


def test_synthetic_extension_bytes_preserved():
    blob = _synthetic(with_extension=True)
    a = AicFile.loads(blob)
    assert a.extension == b"\xde\xad\xbe\xef" * 3
    assert a.roundtrip_ok() and a.roundtrip_bytes() == blob


def test_determinism_two_parses():
    blob = _synthetic()
    assert AicFile.loads(blob).as_dict() == AicFile.loads(blob).as_dict()


def test_garbage_fails_loudly():
    for junk in (b"", b"\x00\x00", b"AAAA", b"\xff" * 100):
        with pytest.raises(Sh2ParseError):
            AicFile.loads(junk)
    # N в допустимом cap, но файл короток — обрезан, не мусор-цикл
    with pytest.raises(Sh2ParseError):
        AicFile.loads(struct.pack("<I", 1000) + b"\x00" * 100)
