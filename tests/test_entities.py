"""Тесты S2.5: entities_decode.py + s2game.py (ТЗ 04 §4.3, 09 §Этап 2).

Инварианты:
1. decode_s2game_nodes обязан проходить на ПОЛНОМ здоровом корпусе
   (70 .s2m + 89 .sh2 минус corrupt_saves.txt) без исключений; непройденные
   типы/объекты — raw (ObjectNode payload нетронут).
2. Реконструкция побайтна: после декодирования object_tree.reconstruct_segment
   даёт дословно исходные байты сегмента (декодер ничего не мутирует).
3. Строгая валидация layout'а: одиночный Building-52 кадр с рассогласованными
   размерами/поворотом/координатами -> Sh2ParseError с именем файла и объекта
   (мутационные проверки ниже), HeightLayer -- так же.
4. Классы с подтверждённым расхождением доки и корпуса (Statue,
   SpiralStairTeleport) не декодируются вовсе (raw-passthrough).
"""
from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest

from sh2tw.formats.s2m_file import S2mFile, Sh2ParseError
from sh2tw.formats import object_tree as ot
from sh2tw.formats import s2game as sg
from sh2tw.formats import entities_decode as ed
from sh2tw.paths import load_paths

DATA = Path(__file__).parent / "data"
SAMPLE = DATA / "sample.s2m"
SAMPLE_NOTRAIL = DATA / "sample_notrail.s2m"
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


def s2game_nodes(model: S2mFile) -> tuple[list[ot.ObjectNode], bytes, bytes]:
    seg = [s for s in model.segments if s.name == "s2game"]
    assert seg, "нет сегмента s2game"
    nodes, tail = ot.parse_segment(seg[0].decompressed)
    return nodes, tail, seg[0].decompressed


def decode_model(model: S2mFile, name: str = "") -> sg.S2GameModel:
    nodes, tail, raw = s2game_nodes(model)
    model_dec = sg.decode_s2game_nodes(nodes, name)
    # инвариант реконструкции ПОСЛЕ декодирования (задание S2.5)
    assert ot.reconstruct_segment(nodes, tail) == raw, \
        f"реконструкция != оригинал после decode ({name})"
    return model_dec


# --- фикстуры -------------------------------------------------------------------

@pytest.mark.parametrize("path", [SAMPLE, SAMPLE_NOTRAIL, SAMPLE_SAVE])
def test_fixture_decode_positions_sane(path: Path):
    m = decode_model(S2mFile.load(path), path.name)
    assert m.heightlayer is not None
    assert m.buildings and m.actors
    for b in m.buildings:
        assert 0 <= b.x_map < 256 and 0 <= b.z_map < 256
        assert b.yaw_deg % 90 == 0 and 1 <= b.footprint_w <= 40 and 1 <= b.footprint_h <= 40
        assert b.class_name in ed.BUILDING_CLASSES
    for a in m.actors:
        assert 0 <= a.x_map < 256 and 0 <= a.z_map < 256
        assert a.class_name in ed.ACTOR_CLASSES
    # raw-узлы не пусты: менеджерские/слоевые типы остаются raw
    raw_types = {n.type_name for n in m.raw_nodes}
    assert {"S2Player", "BuildingLayer"} & raw_types or {"S2Estate", "BuildingLayer"} & raw_types


def test_fixture_deterministic_and_json_stable():
    """Детерминизм ТЗ 04 §4.7: повторный parse идентичен (сортировка ключей)."""
    a = decode_model(S2mFile.load(SAMPLE), SAMPLE.name)
    b = decode_model(S2mFile.load(SAMPLE), SAMPLE.name)
    da = sorted(json.dumps(p.as_dict(), sort_keys=True) for p in a.placements)
    db = sorted(json.dumps(p.as_dict(), sort_keys=True) for p in b.placements)
    assert da == db
    assert a.census == b.census
    assert a.raw_stats.keys() == b.raw_stats.keys()


def test_save_richer_state_more_placements():
    """Сейвы содержат runtime-состояние: placements сейва > карты-фикстуры (F, §4.8)."""
    m_map = decode_model(S2mFile.load(SAMPLE), SAMPLE.name)
    m_save = decode_model(S2mFile.load(SAMPLE_SAVE), SAMPLE_SAVE.name)
    assert len(m_save.actors) > len(m_map.actors)


def test_heightlayer_planes_fixture():
    m = decode_model(S2mFile.load(SAMPLE), SAMPLE.name)
    hl = m.heightlayer
    assert hl is not None
    assert len(hl.main_plane) == 4 * sg.HL_MAIN_FLOATS
    assert all(len(cp) == 4 * sg.HL_CORNER_FLOATS for cp in hl.corner_planes)
    main = hl.main_as_floats()
    assert len(main) == 65536 and all(v == v for v in main)  # без NaN
    # height scale совпадает с эталоном F3: значения конечны и в разумных пределах
    assert max(abs(v) for v in main) < 1e6


def test_class_blocklist_not_decoded():
    """Statue/SpiralStairTeleport — layout расходится с докой: raw целиком."""
    m = decode_model(S2mFile.load(SAMPLE_NOTRAIL), SAMPLE_NOTRAIL.name)
    assert all(b.class_name not in ed.BUILDING_CLASS_BLOCKLIST for b in m.placements)
    stats = m.raw_stats.get("SpiralStairTeleport")
    assert stats and stats["class_blocked"] > 0
    spiral_raw = [n for n in m.raw_nodes if n.type_name == "SpiralStairTeleport"]
    assert spiral_raw, "на sample_notrail спирали обязаны остаться raw"
    assert all(n.payload for n in spiral_raw)  # payload сохранён для реконструкции


# --- строгая валидация (layout доки) --------------------------------------------

def _corrupt_node(node: ot.ObjectNode, off_rel: int, data: bytes) -> ot.ObjectNode:
    """Копия узла с правкой payload (для мутационных проверок; оригинал не трогаем)."""
    pay = bytearray(node.payload)
    pay[off_rel:off_rel + len(data)] = data
    return ot.ObjectNode(obj_id=node.obj_id, reg_index=node.reg_index,
                         type_name=node.type_name, chain=list(node.chain),
                         header=node.header, payload=bytes(pay),
                         has_end_marker=node.has_end_marker)


def test_building_layout_mutation_raises_named_error():
    """Битые размеры/поворот/позиция в BUILDING body -> Sh2ParseError, именуя
    файл, класс и объект (контракт «raise naming file/object on mismatch»)."""
    nodes, _, _ = s2game_nodes(S2mFile.load(SAMPLE))
    baks = [n for n in nodes if n.type_name == "Bakery"]
    assert baks
    for patch_spec, frag in (
        (ed.BW_ROT, b"\x00\x00\x00\x00"),               # размеры 0x0 (как «плохие» Statue)
        (ed.BYAW, struct.pack("<f", 33.5)),              # поворот не кратен 90
        (ed.BPOS_X, struct.pack("<f", 1e9)),             # позиция вне поля карты
    ):
        for n in baks:
            off = ed.find_building_bodies(n.payload)
            if not off:
                continue
            mut = _corrupt_node(n, off[0] + patch_spec, frag)
            with pytest.raises(Sh2ParseError) as ei:
                ed.decode_building(mut, "mut.s2m")
            msg = str(ei.value)
            assert "mut.s2m" in msg and "Bakery" in msg and hex(mut.obj_id) in msg
            break


def test_heightlayer_layout_mutation_raises():
    nodes, _, _ = s2game_nodes(S2mFile.load(SAMPLE))
    hl = [n for n in nodes if n.type_name == "HeightLayer"][0]
    hdr_len = struct.unpack_from("<I", hl.payload, 4)[0]
    cnt_off = 8 + hdr_len + 16  # dword count основной плоскости
    mut = _corrupt_node(hl, cnt_off, b"\x00\x10\x00\x00")  # 4096 != 65536
    with pytest.raises(Sh2ParseError) as ei:
        sg.decode_heightlayer(mut, "broken.s2m")
    assert "broken.s2m" in str(ei.value) and "65536" in str(ei.value)


def test_actor_invalid_body_falls_back_to_raw_not_raise():
    """Entity-59 с мусорными координатами — НЕ исключение (корпус такие файлы
    содержит здоровыми), а raw с зафиксированной причиной."""
    nodes, _, _ = s2game_nodes(S2mFile.load(SAMPLE))
    arch = [n for n in nodes if n.type_name == "Archer"
            and ed.find_entity_field0(n.payload)]
    assert arch
    b = ed.find_entity_field0(arch[0].payload)[0]
    mut = _corrupt_node(arch[0], b + ed.POS_X, struct.pack("<fff", 123e6, 0, 0))
    dec, reason = ed.decode_actor(mut, "x.s2m")
    assert dec is None and reason == "invalid_frames"


# --- корпус S2.5: decode без падений + round-trip -------------------------------

def test_corpus_s2game_decode_and_reconstruct_all():
    files = corpus_files()
    if len(files) < 100:
        pytest.skip("живого корпуса нет (другая машина)")
    excl = corrupt_names()
    assert excl, "corrupt_saves.txt обязан существовать"
    maps_ok = saves_ok = 0
    bad: list[str] = []
    total_b = total_a = 0
    seen_raw_types: set[str] = set()
    blocked_seen: set[str] = set()
    for f in files:
        if f.name in excl:
            continue
        try:
            m = decode_model(S2mFile.loads(f.read_bytes()), f.name)
        except (Sh2ParseError, AssertionError) as e:
            bad.append(f"{f.name}: {e}")
            continue
        total_b += len(m.buildings)
        total_a += len(m.actors)
        seen_raw_types |= {n.type_name for n in m.raw_nodes if n.type_name}
        blocked_seen |= {c for c, r in m.raw_stats.items() if r.get("class_blocked")}
        assert m.heightlayer is not None, f"{f.name}: нет HeightLayer"
        assert m.census.get("S2Game"), f"{f.name}: нет корневого S2Game"
        for p in m.placements:
            assert 0 <= p.x_map < 256 and 0 <= p.z_map < 256, f"{f.name}: {p.class_name} {p.obj_id:#x} вне поля"
            assert p.class_name not in ed.BUILDING_CLASS_BLOCKLIST, f"{f.name}: блоклированный класс расшифрован"
        if f.suffix.lower() == ".s2m":
            maps_ok += 1
        else:
            saves_ok += 1
    assert not bad, f"decode упал: {bad[:4]} ({len(bad)} файлов)"
    healthy = len(files) - len(excl)
    assert maps_ok == sum(1 for f in files if f.suffix.lower() == ".s2m" and f.name not in excl)
    assert saves_ok == sum(1 for f in files if f.suffix.lower() == ".sh2" and f.name not in excl)
    assert maps_ok >= 70, f"ожидание >=70 карт, прошло {maps_ok}"
    assert saves_ok >= 89, f"ожидание >=89 сейвов, прошло {saves_ok}"
    assert maps_ok + saves_ok == healthy
    # нижние пороги покрытия подтверждены замером корпуса (23.11.2026: 55167/266770)
    assert total_b >= 50_000 and total_a >= 200_000, (total_b, total_a)
    # блокировки реализованы, не-размещаемые типы остались raw
    assert {"Statue", "SpiralStairTeleport"} == blocked_seen & {"Statue", "SpiralStairTeleport"}
    assert {"ScriptAction", "S2Player", "BuildingLayer"} <= seen_raw_types
    # перепись сегмента покрывает все объекты
    assert maps_ok and saves_ok  # конкретные числа проверены выше


def test_corpus_disagreements_recorded_not_guessed():
    """Расхождения (no_frame/multi/invalid) фиксируются в raw_stats, не съедаются."""
    files = [f for f in corpus_files() if f.suffix.lower() == ".sh2"]
    if not files:
        pytest.skip("живого корпуса нет")
    excl = corrupt_names()
    agg: dict[str, dict[str, int]] = {}
    for f in files[:40]:
        if f.name in excl:
            continue
        m = decode_model(S2mFile.loads(f.read_bytes()), f.name)
        for cls, cnt in m.raw_stats.items():
            dst = agg.setdefault(cls, {})
            for r, c in cnt.items():
                dst[r] = dst.get(r, 0) + c
    # хотя бы один класс с multi_frame/no_frame должен встретиться на 40 сейвах
    assert any(r in ("multi_frame", "no_frame") for d in agg.values() for r in d)
