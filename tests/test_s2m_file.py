"""Тесты S2.1: контейнер .s2m/.sh2 — round-trip, заголовок, мусороустойчивость (04 §4.7)."""
from __future__ import annotations

import zlib
from pathlib import Path

import pytest

from sh2tw.formats.s2m_file import S2mFile, Sh2ParseError
from sh2tw.paths import load_paths

DATA = Path(__file__).parent / "data"
SAMPLE = DATA / "sample.s2m"
SAMPLE_SAVE = DATA / "sample_save.sh2"


def corpus_files() -> list[Path]:
    p = load_paths()
    out: list[Path] = []
    for d in (p.maps_dir_game, p.saves_dir):
        if d.is_dir():
            out += [f for f in sorted(d.iterdir())
                    if f.suffix.lower() in (".s2m", ".sh2")]
    return out


def test_sample_roundtrip_identical():
    f = S2mFile.load(SAMPLE)
    assert f.roundtrip_bytes() == SAMPLE.read_bytes()
    assert f.roundtrip_ok()


def test_sample_save_roundtrip_identical():
    f = S2mFile.load(SAMPLE_SAVE)
    assert f.roundtrip_ok()


def test_header_known_fields():
    f = S2mFile.load(SAMPLE)
    hdr = f.file_header
    assert hdr.string_opts.get("type") == "peacecampaign"
    assert hdr.int_opts["version"] == 1
    assert hdr.int_opts["maxplayers"] >= 1


def test_mapsize_optional_across_corpus():
    files = corpus_files()
    if not files:
        pytest.skip("нет корпусных файлов на этой машине")
    have = miss = 0
    for p in files[:20]:
        io = S2mFile.loads(p.read_bytes()).file_header.int_opts
        if "mapsize" in io:
            have += 1
        else:
            miss += 1
    assert have > 0  # mapsize опционален (FileHeader.md) — оба варианта легальны


def test_segments_order_and_names():
    f = S2mFile.load(SAMPLE)
    names = [s.name for s in f.segments]
    assert names[:3] == ["mapheader", "radarmap", "s2game"]


def test_compression_level_found_on_samples():
    f = S2mFile.load(SAMPLE)
    found = [s.find_compression_level() for s in f.segments]
    for s, lvl in zip(f.segments, found):
        if lvl is not None:
            assert zlib.compress(s.decompressed, lvl) == s.compressed


@pytest.mark.parametrize("cut", [10, 100, 1000])
def test_truncated_raises_not_hangs(cut: int):
    # war_chapter1: tail=0 — любое усечение бьёт последний zlib-поток
    b = (DATA / "sample_notrail.s2m").read_bytes()[:-cut]
    with pytest.raises(Sh2ParseError):
        S2mFile.loads(b)


def test_garbage_raises():
    with pytest.raises(Sh2ParseError):
        S2mFile.loads(b"this is not an s2m file" * 50)


def test_determinism_two_loads():
    a = S2mFile.loads(SAMPLE.read_bytes()).as_dict()
    b = S2mFile.loads(SAMPLE.read_bytes()).as_dict()
    assert a == b


def test_corpus_roundtrip_all():
    files = corpus_files()
    if len(files) < 50:
        pytest.skip("живого корпуса нет (другая машина)")
    bad: list[str] = []
    for f in files:
        try:
            m = S2mFile.loads(f.read_bytes())
            if not m.roundtrip_ok():
                bad.append(f.name)
        except Sh2ParseError as e:
            bad.append(f"{f.name}: {e}")
    assert not bad, f"round-trip упали: {bad[:5]} ({len(bad)} файлов)"
    assert len(files) >= 100
