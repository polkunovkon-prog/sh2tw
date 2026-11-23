"""Контейнер gameRules.dat (ТЗ 04 §4.3 «gameRules.dat», задача S2.9; 13 §G).

ВНИМАНИЕ — расхождение дока ТЗ с файлом игры (файл authoritative, 00 §3):
реестр G4 формулирует «2111 байт заголовка → zlib → нод-дерево». Замер на
файле поставки (game_dir/gameRules.dat, 2111 байт ВСЕГО): заголовка нет —
zlib-поток начинается с байта 0 и занимает 2038 байт, после потока — 73 байта
сырого хвоста (не zlib). Число «2111» — это полный размер файла, а не длина
заголовка. Для совместимости с возможным «2111-байтным префиксом» (образец
Lord Editor gamerules_fixed.dat на другой машине недоступен) loads() допускает
сырой префикс перед zlib-потоком (header_raw переносится как есть).

Распакованный payload — сегмент дерева объектов того же синтаксиса, что
сегменты .s2m (маркеры AF 1E FF FF / AD DE FF FF, magic-пара 0x5CA1AB1E):
1 узел GameRules + 21 узел LordsRules (факт корпуса, тест
test_object_tree_walk_and_rebuild). Обход — переиспользование object_tree.

Семантика полей LordsRules: в OpenSH2-Notes byte-layout LordsRules НЕ
документирован; 13 §G перечисляет «честные поля» Lord Editor (торговые веса,
приоритеты найма, предпочтения построек, оборонные группы, спавн
преступности/гноя/крыс) БЕЗ смещений, и запрещает правки стартовых ресурсов/
скрытых доходов. Следствие: payload узлов НЕ декодируется — сохраняется
сырым; # UNKNOWN(offsets LordsRules-полей; доразбор — живые вечера/эксперименты).

Round-trip контракт (04 §4.7, обязательно): roundtrip_bytes() побайтово равна
исходнику. Модель пересобирает поток: header_raw + сжатые байты + tail;
find_compression_level() подбирает уровень, дающий поток побайтово (факт
корпуса: zlib level 6 == исходный поток gameRules.dat из игры).
"""
from __future__ import annotations

import zlib
from dataclasses import dataclass, field
from pathlib import Path

from . import object_tree as ot
from .object_tree import ObjectNode
from .s2m_file import Sh2ParseError

SCAN_WINDOW = 65536  # предел поиска начала zlib-потока (G4 заявлял префикс 2111)


def _is_zlib_start(b: bytes, o: int) -> bool:
    if o + 1 >= len(b):
        return False
    cmf = b[o]
    if (cmf & 0x0F) != 8:
        return False
    return ((cmf << 8) | b[o + 1]) % 31 == 0


@dataclass
class GameRulesFile:
    """Один gameRules-файл: [header_raw][zlib-поток][tail_raw]."""

    path: Path | None
    header_raw: bytes      # байты до zlib-потока (в игре — пусто; см. docstring)
    compressed: bytes      # точные сжатые байты потока (round-trip переносит их)
    tail: bytes            # байты после потока (в игре 73 B, не zlib) — как есть
    decompressed: bytes    # распакованный сегмент дерева объектов
    _src: bytes = field(repr=False, default=b"")
    _nodes: list[ObjectNode] | None = field(repr=False, default=None, compare=False)
    level: int | None = None

    # ---------- загрузка ----------
    @classmethod
    def load(cls, path: Path) -> "GameRulesFile":
        return cls.loads(path.read_bytes(), path=path)

    @classmethod
    def loads(cls, data: bytes, path: Path | None = None) -> "GameRulesFile":
        if len(data) < 4:
            raise Sh2ParseError("gameRules: файл короче 4 байт")
        off = -1
        stream = decompressed = unused = b""
        limit = min(len(data) - 2, SCAN_WINDOW)
        for cand in range(0, limit):
            if not _is_zlib_start(data, cand):
                continue
            d = zlib.decompressobj()
            try:
                dec = d.decompress(data[cand:])
            except zlib.error:
                continue
            if not d.eof or not dec:
                continue
            consumed = len(data) - cand - len(d.unused_data)
            if consumed <= 0:
                continue
            off, stream, decompressed, unused = cand, data[cand:cand + consumed], dec, d.unused_data
            break
        if off < 0:
            raise Sh2ParseError("gameRules: zlib-поток не найден в первых "
                                f"{limit+2} байтах (не gameRules?)")
        model = cls(path=path, header_raw=data[:off], compressed=stream,
                    tail=unused, decompressed=decompressed, _src=data)
        # сегмент обязан читаться целиком (облом = битый файл → громкая ошибка)
        model.nodes()
        return model

    # ---------- дерево объектов ----------
    def nodes(self) -> list[ObjectNode]:
        """Обход распакованного сегмента; инвариант реконструкции проверен
        на corpus (tests/test_gamerules.py) — здесь только повторный разбор
        для ленивого кэша."""
        if self._nodes is None:
            nodes, tail = ot.parse_segment(self.decompressed)
            if ot.reconstruct_segment(nodes, tail) != self.decompressed:
                raise Sh2ParseError("gameRules: реконструкция узлового дерева "
                                    "не равна распакованному сегменту")
            self._nodes = nodes
        return self._nodes

    @property
    def game_rules_node(self) -> ObjectNode:
        for n in self.nodes():
            if n.type_name == "GameRules":
                return n
        raise Sh2ParseError("нет узла GameRules")

    @property
    def lords_rules(self) -> list[ObjectNode]:
        """Профили лордов (G5: «честные поля» Lord Editor). payload — raw,
        # UNKNOWN(offsets полей): байт-доков LordsRules нет, не гадаем."""
        return [n for n in self.nodes() if n.type_name == "LordsRules"]

    # ---------- уровень сжатия (для писателя 05) ----------
    def find_compression_level(self) -> int | None:
        """Перебор уровней 0–9: уровень, при котором
        zlib.compress(decompressed, lvl) == исходный поток (факт корпуса: 6)."""
        if self.level is not None:
            return self.level
        hint = (self.compressed[1] >> 6) & 3 if len(self.compressed) >= 2 else None
        order = ([hint] if hint is not None else []) + [9, 6, 1, 0, 2, 3, 4, 5, 7, 8]
        for lvl in dict.fromkeys(order):
            if zlib.compress(self.decompressed, lvl) == self.compressed:
                self.level = lvl
                return lvl
        return None

    # ---------- round-trip ----------
    def roundtrip_bytes(self) -> bytes:
        return self.header_raw + self.compressed + self.tail

    def roundtrip_ok(self) -> bool:
        return self._src == self.roundtrip_bytes()

    def as_dict(self) -> dict:
        return {
            "path": str(self.path) if self.path else None,
            "file_len": len(self._src),
            "header_raw_len": len(self.header_raw),
            "compressed_len": len(self.compressed),
            "tail_len": len(self.tail),
            "decompressed_len": len(self.decompressed),
            "zlib_level": self.level,
            "nodes": [n.as_dict() for n in self.nodes()],
        }
