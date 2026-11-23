"""Тесты S2.2/S2.3: обход дерева объектов по маркерам + round-trip корпуса (04 §4.3).

Инвариант реконструкции: b"".join(node.reconstruct()) + END_SEG + tail == сегмент
дословно. Границы могут быть «шире» семантики (payload абсорбирует chain-записи),
но побайтовая эквивалентность обязательна для ВСЕХ здоровых файлов корпуса.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from sh2tw.formats.s2m_file import S2mFile, Sh2ParseError
from sh2tw.formats import object_tree as ot
from sh2tw.paths import load_paths

DATA = Path(__file__).parent / "data"
SAMPLE = DATA / "sample.s2m"
SAMPLE_SAVE = DATA / "sample_save.sh2"
CORRUPT_LIST = Path(__file__).parent / "corpus" / "corrupt_saves.txt"


def corpus_files() -> list[Path]:
    p = load_paths()
    out: list[Path] = []
    for d in (p.maps_dir_game, p.maps_dir_user, p.saves_dir):
        if d.is_dir():
            out += [f for f in sorted(d.rglob("*"))
                    if f.suffix.lower() in (".s2m", ".sh2") and f.is_file()]
    return out


def corrupt_names() -> set[str]:
    if not CORRUPT_LIST.is_file():
        return set()
    return {l.strip() for l in CORRUPT_LIST.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("#")}


def walk_and_rebuild(model: S2mFile) -> dict[str, list[ot.ObjectNode]]:
    out: dict[str, list[ot.ObjectNode]] = {}
    for seg in model.segments:
        nodes, tail = ot.parse_segment(seg.decompressed)
        rebuilt = ot.reconstruct_segment(nodes, tail)
        assert rebuilt == seg.decompressed, (
            f"реконструкция != оригинал: сегмент {seg.name} "
            f"({len(rebuilt)} vs {len(seg.decompressed)} байт)")
        out[seg.name] = nodes
    return out


# --- unit-уровень на фикстурах -------------------------------------------------

def test_sample_all_segments_walk_and_rebuild():
    model = S2mFile.load(SAMPLE)
    segs = walk_and_rebuild(model)
    assert {"mapheader", "radarmap", "s2game"} <= set(segs)
    assert segs["mapheader"][0].type_name == "MapHeader"
    assert segs["radarmap"][0].type_name == "RadarMap"
    assert segs["s2game"][0].type_name == "S2Game"


def test_segment_start_magic_pair_preserved():
    # G15: первый объект каждого сегмента предваряется парой (5CA1AB1E, 1);
    # bytes пары обязаны пережить реконструкцию (вheader первого узла).
    model = S2mFile.load(SAMPLE)
    for seg in model.segments:
        nodes, tail = ot.parse_segment(seg.decompressed)
        assert seg.decompressed[:8] == b"\x1e\xab\xa1\x5c\x01\x00\x00\x00", seg.name
        assert nodes[0].header[:8] == seg.decompressed[:8]


def test_heightlayer_payload_sized_not_searched():
    # F3: payload HeightLayer = 3 407 932 B; внутри плоскостей углов встречается
    # ложный паттерн AF1EFFFF — граница обязана считаться по объявленным длинам.
    model = S2mFile.load(SAMPLE)
    hl = [n for n in walk_and_rebuild(model)["s2game"]
          if n.type_name == "HeightLayer"]
    assert len(hl) == 1
    pay = hl[0].payload
    hdr_len = int.from_bytes(pay[4:8], "little")
    assert len(pay) == 3407932 + (hdr_len - 12) >= 3407932
    assert pay[8 + hdr_len:12 + hdr_len] == ot.DATA_START


def test_inline_registrations_harvested():
    # Регистрация типов внутри A5C1FFFF-подблоков payload (факт корпуса:
    # S2Clan reg=151 и TroopClan reg=152 объявлены внутри payload клана на
    # «9 миссия. спасения монастыря.s2m» @10863174/@10863205).
    p = load_paths().maps_dir_game / "9 миссия. спасения монастыря.s2m"
    if not p.is_file():
        pytest.skip("карта есть только на игровой машине")
    model = S2mFile.load(p)
    nodes, _ = ot.parse_segment([s for s in model.segments
                                 if s.name == "s2game"][0].decompressed)
    regs = {n.reg_index: n.type_name for n in nodes if n.type_name}
    assert regs.get(152) == "TroopClan" or regs.get(151) == "S2Clan"
    # без harvest следующий объект с reg=152 читался бы как новый -> облом;
    # сам факт успешного полного обхода проверяет corpus-тест ниже.


# --- корпус S2.3 ---------------------------------------------------------------

def test_corpus_walk_rebuild_all():
    files = corpus_files()
    if len(files) < 100:
        pytest.skip("живого корпуса нет (другая машина)")
    excl = corrupt_names()
    assert excl, "список corrupt_saves.txt обязан существовать (учёт D-файлов)"
    bad: list[str] = []
    walked = 0
    for f in files:
        if f.name in excl:
            continue
        try:
            walk_and_rebuild(S2mFile.loads(f.read_bytes()))
            walked += 1
        except (Sh2ParseError, AssertionError) as e:
            bad.append(f"{f.name}: {e}")
    assert not bad, f"обход/реконструкция упали: {bad[:4]} ({len(bad)} файлов)"
    assert walked >= 140, f"ожидание >=140 здоровых файлов, прошло {walked}"
    assert walked == len(files) - len(excl)


def test_corrupt_list_is_actually_corrupt():
    # Список исключения — не «неудобные файлы», а подтверждённая порча:
    # у них есть гнилые END-маркеры (первый байт AF -> D0/AB), у здоровых — нет.
    files = {f.name: f for f in corpus_files()}
    excl = corrupt_names()
    if not excl or not files:
        pytest.skip("корпус/список недоступен")
    rot = (b"\xd0\x1e\xff\xff", b"\xab\x1e\xff\xff")
    for name in excl:
        f = files.get(name)
        if f is None:
            continue
        blob = b"".join(s.decompressed for s in S2mFile.load(f).segments)
        assert any(blob.count(m) > 0 for m in rot), f"{name}: гниль не подтверждена"
    healthy = 0
    for name, f in files.items():
        if name in excl:
            continue
        blob = b"".join(s.decompressed for s in S2mFile.load(f).segments)
        if ot.END_OBJ in blob:
            assert not any(blob.count(m) for m in rot), f"{name}: гниль у здорового?"
            healthy += 1
            if healthy > 30:
                break


def test_corrupt_saves_fail_loudly_not_hang():
    # Парсер обязан падать на битых сейвах как на мусоре: ошибка, не тихая
    # «починка» и не зависание (поиск маркеров конечен).
    files = {f.name: f for f in corpus_files()}
    for name in corrupt_names() & set(files):
        with pytest.raises(Sh2ParseError):
            walk_and_rebuild(S2mFile.load(files[name]))
