"""s2game.py — разбор сегмента s2game: raw + выборочные декодеры (ТЗ 04 §4.3, S2.5).

Структура сегмента (Overview.md, подтверждено корпусом): префикс-магическая
пара (5CA1AB1E, 1), сегментный локальный реестр типов, поток объектов,
терминальный маркер AD DE FF FF. Обход границ — object_tree.parse_segment
(S2.2/S2.3): побайтовая реконструкция гарантирует raw-passthrough всего, что
не раскодировано семантически.

Что декодируется:
- HeightLayer: F3 — основная плоскость высот 256x256 float32 (65536 значений)
  и 3 плоскости угловых высот по 262144 float32; длины объявлены в payload,
  границы валидируются строго (ошибка — Sh2ParseError). Пересобирать нельзя —
  только читать (payload остаётся в ObjectNode для round-trip).
- Размещённые сущности — entities_decode (PlacedActors.md/Keep.md):
  BuildingPlacement (позиция модели, поворот кратно 90°, размеры отпечатка,
  saved_ref) и ActorPlacement (байт on-map, XYZ; мир = raw/1024).
- Перепись типов (census) — счётчики по type_name для snapshot (S2.6).

Что остаётся raw (UNKNOWN, ТЗ 00):
- ScriptAction/эмиттеры/формации/кланы/слои/менеджеры (S2Player, S2Estate,
  BuildingLayer и пр.) — кадрируемых секций по докам нет; ~64% объектов.
- Классы из BUILDING_CLASS_BLOCKLIST (Statue, SpiralStairTeleport) — layout
  расходится с докой на корпусе (подробности в docstring entities_decode).
- Объекты актёрских классов без единичного валидного Entity-59 кадра
  (no_frame / multi_frame / invalid_single_frame) — см. raw_stats.
- Поворот/владелец/команда актёров — доками не покрыты (PlacedActors.md:
  heading только после массивов переменной длины; owner/estate/team — нет
  задокументированного смещения). НЕ гадаем.
"""
from __future__ import annotations

import struct
from collections import Counter
from dataclasses import dataclass, field

from . import entities_decode as ed
from .object_tree import DATA_START, END_SEG, ObjectNode
from .s2m_file import Sh2ParseError

HL_MAIN_FLOATS = 65536          # 256x256 основная плоскость (F3)
HL_CORNER_FLOATS = 262144       # угловая плоскость: 4 corner/cell x 65536 cells
HL_PLANES_DECLARED = 3145740    # [tag2][len]: 3*(4 + 4*262144)
HL_BLOCK_HEADER = 65536         # u32 перед каждой угловой плоскостью (семантика не объяснена докой; observed corpus-wide)


@dataclass
class HeightLayerInfo:
    """Плоскостей высот Копия байтов payload (не пересобирать никогда!)."""
    hdr_len: int
    main_plane: bytes       # 65536 float32 LE
    corner_planes: tuple[bytes, bytes, bytes]
    node: ObjectNode = field(repr=False, default=None)  # type: ignore[assignment]

    def main_as_floats(self) -> tuple[float, ...]:
        return struct.unpack("<%df" % HL_MAIN_FLOATS, self.main_plane)

    def corner_as_floats(self, i: int) -> tuple[float, ...]:
        return struct.unpack("<%df" % HL_CORNER_FLOATS, self.corner_planes[i])


def decode_heightlayer(node: ObjectNode, filename: str = "") -> HeightLayerInfo:
    """Строгая граница по объявленным длинам (HeightLayer.md, F3; границы уже
    выставил object_tree._heightlayer_payload_end — здесь повторная сверка).

    Layout payload (замер на корпусе 23.11.2026, все 159 файлов сходятся):
    [u32 tag=3][u32 hdr_len][заголовок hdr_len байт][A5C1FFFF][tv (рег. тип,
    по карте varies — не валидируем)][u32=1][u32 prim=0x40004][u32 cnt=65536]
    [65536 float32 основная плоскость][u32 tag2=2][u32 len=3145740]
    [3 блока: u32 65536 (семантику дока не объясняет) + 262144 float32].
    hdr_len варьируется (12..252) — смещения только от объявленных длин.
    """
    p = node.payload
    who = f"{filename or '<без имени>'}: HeightLayer obj 0x{node.obj_id:x}"
    tag, hdr_len = struct.unpack_from("<II", p, 0)
    if tag != 3 or not 4 <= hdr_len <= 4096:
        raise Sh2ParseError(f"{who}: tag={tag} hdr_len={hdr_len} — ожидали tag=3")
    k = 8 + hdr_len
    if p[k:k + 4] != DATA_START:
        raise Sh2ParseError(f"{who}: нет маркера данных A5C1FFFF @{k}")
    tv, one, prim, cnt = struct.unpack_from("<4I", p, k + 4)
    if one != 1 or prim != 0x40004:
        raise Sh2ParseError(f"{who}: prim-примитив {prim:#x}/one={one} не 0x40004/1")
    if cnt != HL_MAIN_FLOATS:
        raise Sh2ParseError(f"{who}: основная плоскость count={cnt} не {HL_MAIN_FLOATS}")
    off = k + 20
    end_main = off + 4 * HL_MAIN_FLOATS
    t2, ln2 = struct.unpack_from("<II", p, end_main)
    if t2 != 2 or ln2 != HL_PLANES_DECLARED:
        raise Sh2ParseError(f"{who}: угловые плоскости tag={t2} len={ln2}, ожидали 2/{HL_PLANES_DECLARED}")
    corners: list[bytes] = []
    q = end_main + 8
    for i in range(3):
        bh, = struct.unpack_from("<I", p, q)
        block = 4 * HL_CORNER_FLOATS
        if bh != HL_BLOCK_HEADER or q + 4 + block > len(p):
            raise Sh2ParseError(f"{who}: угловая плоскость {i}: заголовок {bh} не {HL_BLOCK_HEADER}")
        corners.append(p[q + 4:q + 4 + block])
        q += 4 + block
    if q != end_main + 8 + HL_PLANES_DECLARED:
        raise Sh2ParseError(f"{who}: разбег плоскостей {q} != {end_main + 8 + HL_PLANES_DECLARED}")
    return HeightLayerInfo(hdr_len=hdr_len, main_plane=p[off:end_main],
                           corner_planes=(corners[0], corners[1], corners[2]), node=node)


@dataclass
class S2GameModel:
    filename: str
    heightlayer: HeightLayerInfo | None
    buildings: list[ed.BuildingPlacement]
    actors: list[ed.ActorPlacement]
    raw_nodes: list[ObjectNode]              # НЕ расшифровано — byte-passthrough (UNKNOWN)
    raw_stats: dict[str, Counter] = field(default_factory=dict)  # класс -> причины raw
    census: Counter = field(default_factory=Counter)             # type_name -> count

    @property
    def placements(self) -> list[ed.BuildingPlacement | ed.ActorPlacement]:
        return self.buildings + self.actors

    def coverage(self) -> float:
        """Доля объектов сегмента с расшифрованной семантикой (метрика S2.6)."""
        total = sum(self.census.values())
        if not total:
            return 0.0
        return (len(self.buildings) + len(self.actors) +
                (1 if self.heightlayer else 0)) / total

    def placement_census(self) -> Counter:
        return Counter([p.class_name for p in self.placements])


def decode_s2game_nodes(nodes: list[ObjectNode], filename: str = "") -> S2GameModel:
    """Сегмент s2game: перепись + HeightLayer + сущности. Исключений для
    здоровых файлов корпуса не бросает; строгие проверки (внутренняя
    непротиворечивость layout) — Sh2ParseError с именем файла/объекта."""
    model = S2GameModel(filename=filename, heightlayer=None, buildings=[],
                        actors=[], raw_nodes=[])
    for nd in nodes:
        model.census[nd.type_name or "<без типа>"] += 1
        if nd.type_name == "HeightLayer":
            model.heightlayer = decode_heightlayer(nd, filename)
            continue
        if nd.type_name in ed.BUILDING_CLASSES:
            bp, reason = ed.decode_building(nd, filename)
            if bp is not None:
                model.buildings.append(bp)
                continue
        elif nd.type_name in ed.ACTOR_CLASSES:
            ap, reason = ed.decode_actor(nd, filename)
            if ap is not None:
                model.actors.append(ap)
                continue
        elif nd.type_name in ed.BUILDING_CLASS_BLOCKLIST:
            reason = "class_blocked"
        else:
            reason = "not_placed_class"
        model.raw_nodes.append(nd)
        model.raw_stats.setdefault(nd.type_name or "<без типа>", Counter())[reason] += 1
    return model
