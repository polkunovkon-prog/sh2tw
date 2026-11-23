"""mapheader_writer.py — писатель сегмента MapHeader (S3.5, L2; ТЗ 05 §5.5).

Собирает mapheader-сегмент из узлов object_tree с модификациями:
- имя карты (блок имени переменной длины пересобирается целиком);
- тип карты (u32 в хвосте MapHeader-узла: 0/2/3/4);
- EstateMarkers (равнодлинные записи 32×12 внутри payload 396 B).

РadarMap/S2Game писатель НЕ трогает (граница 02 §2.5) — они копируются
байт-в-байт генератором (generator.py).

Эталонная планка (05 §5.5): load → writer (без изменений) → байт-идентичность
на ванильных картах — сериализация ровно обратна парсингу. Расхождение =
баг/пропуск поля — чинить до совпадения (тест test_writer_reference_bar).

Структура MapHeader-узла выведена в S2.4 (G17):
  payload = [u32×6 преамбула][u32 L][u32 C][имя UTF-16LE, C символов]
            [1 байт unk][u32 map_type]
  L — длина «блока имени с END-маркером»: из корпуса L = 2C + 9
  (проверено на фикстурах sample.s2m/sample_notrail.s2m/sample_save.sh2; тест фиксирует).
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field

from ..formats.map_header import MAP_TYPES, MARKER_KINDS, EstateMarker
from ..formats.object_tree import ObjectNode, Sh2ParseError
from ..formats.s2m_file import Sh2ParseError as ContainerError  # noqa: F401

NAME_BLOCK_OVERHEAD = 9  # L = 2C + 9 (G17; эмпирика: фикстуры корпуса 23.11)
MAX_NAME_CHARS = 27      # имя карты ≤27–30 символов (05 §5.10; берём 27)
S2TW_PREFIX = "S2TW_"


class WriterError(Exception):
    """Ошибка писателя MapHeader (некорректная модель/модификация)."""


def _validate_map_name(name: str) -> str:
    """Имя карты: [A-Za-z0-9_] после префикса, ≤27 символов (13 §L)."""
    if not name.startswith(S2TW_PREFIX):
        raise WriterError(f"имя генерируемой карты обязано начинаться с "
                          f"{S2TW_PREFIX} (03 §3.13), получено {name!r}")
    rest = name[len(S2TW_PREFIX):]
    if not rest or len(name) > MAX_NAME_CHARS:
        raise WriterError(f"длина имени {name!r} вне 1..{MAX_NAME_CHARS} символов")
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")
    bad = set(rest) - allowed
    if bad:
        raise WriterError(f"имя {name!r}: запрещённые символы {sorted(bad)} "
                          f"(13 §L: только [A-Za-z0-9_])")
    return name


@dataclass
class MapHeaderBuild:
    """Модель для пересборки mapheader-сегмента (узел MapHeader + правки)."""
    nodes: list[ObjectNode]
    mapheader_index: int
    estate_markers_index: int
    modifications: list[str] = field(default_factory=list)


class MapHeaderWriter:
    """Пересборка mapheader-сегмента: узлы → байты с правками имени/типа/маркеров."""

    def __init__(self, nodes: list[ObjectNode]):
        mh_idx = [i for i, n in enumerate(nodes) if n.type_name == "MapHeader"]
        em_idx = [i for i, n in enumerate(nodes) if n.type_name == "EstateMarkers"]
        if len(mh_idx) != 1 or len(em_idx) != 1:
            raise WriterError(
                f"mapheader-сегмент: MapHeader/EstateMarkers ожидаются по одному, "
                f"найдено {len(mh_idx)}/{len(em_idx)}")
        self.build = MapHeaderBuild(nodes=list(nodes),
                                    mapheader_index=mh_idx[0],
                                    estate_markers_index=em_idx[0])
        self._validate_structure()

    # ----------------------------------------------------------- структура
    def _validate_structure(self) -> None:
        node = self.build.nodes[self.build.mapheader_index]
        p = node.payload
        if len(p) < 42:
            raise WriterError(f"MapHeader payload {len(p)} < 42 байт")
        u0, f4, em_id, f1, f4b, sc_id, scen_enum = struct.unpack_from("<7I", p, 0)
        if (u0, f4, f1, f4b, scen_enum) != (0, 4, 1, 4, 2):
            raise WriterError(f"MapHeader: неожиданная преамбула "
                              f"{[u0, f4, f1, f4b, scen_enum]} != [0,4,1,4,2] (G17)")
        block_len, n_chars = struct.unpack_from("<II", p, 28)
        if block_len != 2 * n_chars + NAME_BLOCK_OVERHEAD:
            raise WriterError(
                f"MapHeader: L={block_len} != 2C+{NAME_BLOCK_OVERHEAD} "
                f"(C={n_chars}) — расхождение с формулой корпуса G17")
        if 36 + 2 * n_chars + 5 != len(p):
            raise WriterError(f"MapHeader: длина payload {len(p)} не сходится с C={n_chars}")
        map_type = struct.unpack_from("<I", p, 36 + 2 * n_chars + 1)[0]
        if map_type not in MAP_TYPES:
            raise WriterError(f"MapHeader: map_type {map_type} вне {set(MAP_TYPES)}")
        # EstateMarkers: 396 B, 32 записи (G17)
        emp = self.build.nodes[self.build.estate_markers_index].payload
        if len(emp) != 396:
            raise WriterError(f"EstateMarkers payload {len(emp)} != 396 (G17)")

    # ------------------------------------------------------------- чтение
    @property
    def name(self) -> str:
        p = self.build.nodes[self.build.mapheader_index].payload
        n_chars = struct.unpack_from("<I", p, 32)[0]
        return p[36:36 + 2 * n_chars].decode("utf-16-le")

    @property
    def map_type(self) -> int:
        p = self.build.nodes[self.build.mapheader_index].payload
        n_chars = struct.unpack_from("<I", p, 32)[0]
        return struct.unpack_from("<I", p, 36 + 2 * n_chars + 1)[0]

    def estate_markers(self) -> list[EstateMarker]:
        from ..formats.map_header import decode_estate_markers
        return decode_estate_markers(self.build.nodes[self.build.estate_markers_index])

    # ------------------------------------------------------------ запись
    def set_name(self, new_name: str) -> "MapHeaderWriter":
        """Новое имя карты (с префиксом S2TW_): пересборка блока имени."""
        _validate_map_name(new_name)
        node = self.build.nodes[self.build.mapheader_index]
        p = node.payload
        n_chars = struct.unpack_from("<I", p, 32)[0]
        head = p[:28]                       # преамбула до [L][C]
        tail = p[36 + 2 * n_chars:]         # 1 байт unk + u32 map_type
        name_bytes = new_name.encode("utf-16-le")
        block_len = len(name_bytes) + NAME_BLOCK_OVERHEAD
        new_payload = (head + struct.pack("<II", block_len, len(new_name))
                       + name_bytes + tail)
        node.payload = new_payload
        self.build.modifications.append(f"name→{new_name}")
        self._validate_structure()  # инвариант после правки
        return self

    def set_map_type(self, map_type: int) -> "MapHeaderWriter":
        """Тип карты: 0 kingmaker, 2 war_custom, 3 peace_custom, 4 free_build."""
        if map_type not in MAP_TYPES:
            raise WriterError(f"map_type {map_type} вне {set(MAP_TYPES)}")
        node = self.build.nodes[self.build.mapheader_index]
        p = bytearray(node.payload)
        n_chars = struct.unpack_from("<I", p, 32)[0]
        struct.pack_into("<I", p, 36 + 2 * n_chars + 1, map_type)
        node.payload = bytes(p)
        self.build.modifications.append(f"type→{map_type}")
        return self

    def set_estate_marker(self, slot: int, kind: int | None = None,
                          x: int | None = None, z: int | None = None,
                          packed_loc: int | None = None) -> "MapHeaderWriter":
        """Правка одного слота EstateMarkers (равнодлинная запись, G17).

        kind: 0 inactive / 1 village / 2 castle; координаты — как в EstateMarkers.
        """
        if not 0 <= slot < 32:
            raise WriterError(f"слот {slot} вне 0..31 (32 слота, G17)")
        if kind is not None and kind not in MARKER_KINDS:
            raise WriterError(f"kind {kind} вне {set(MARKER_KINDS)}")
        node = self.build.nodes[self.build.estate_markers_index]
        p = bytearray(node.payload)
        off = 12 + 12 * slot
        cur_loc, cur_x, cur_z, cur_kind = struct.unpack_from("<ihhI", p, off)
        struct.pack_into("<ihhI", p, off,
                         cur_loc if packed_loc is None else packed_loc,
                         cur_x if x is None else x,
                         cur_z if z is None else z,
                         cur_kind if kind is None else kind)
        node.payload = bytes(p)
        self.build.modifications.append(f"marker[{slot}]")
        return self

    # ------------------------------------------------------- пересборка
    def to_segment(self) -> bytes:
        """Узлы → байты сегмента (reconstruct_segment, побайтовая семантика
        object_tree S2.2/S2.3)."""
        from ..formats.object_tree import reconstruct_segment
        nodes, tail = self.build.nodes, b""
        # reconstruct_segment ожидает (nodes, tail): END_SEG уже в узлах нет
        return reconstruct_segment(nodes, tail)


def rewrite_segment(nodes: list[ObjectNode], *, name: str | None = None,
                    map_type: int | None = None,
                    markers: list[dict] | None = None) -> bytes:
    """Удобная одношаговая пересборка: узлы + правки → байты сегмента.

    markers: [{slot, kind?, x?, z?, packed_loc?}] — правки EstateMarkers.
    """
    w = MapHeaderWriter(nodes)
    if name is not None:
        w.set_name(name)
    if map_type is not None:
        w.set_map_type(map_type)
    for m in markers or []:
        w.set_estate_marker(**m)
    return w.to_segment()
