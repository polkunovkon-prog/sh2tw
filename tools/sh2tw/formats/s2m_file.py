"""Контейнер .s2m/.sh2: ASCII-заголовок + zlib-сегменты + трейлер (ТЗ 04 §4.3, S2.1).

Факты формата: ref/OpenSH2-Notes/FileFormats/S2M/{FileHeader,Overview}.md +
реестр J (G14: трейлер переносится как есть).
Round-trip контракт: roundtrip_bytes() побайтово равна исходнику (сегменты
хранятся сжатыми как были; уровень сжатия определяется отдельно,
find_compression_level, для писателя 05).
"""
from __future__ import annotations

import zlib
from dataclasses import dataclass, field
from pathlib import Path

MAX_TABLE_ROWS = 10_000  # заголовок: строки/целые — десятки, не тысячи
MAX_KEY_LEN = 128
SEGMENT_NAMES = ("mapheader", "radarmap", "s2game")  # порядок — Overview.md


class Sh2ParseError(Exception):
    """Повреждённый/непонятный файл. Парсер обязан падать быстро (04 §4.7)."""


@dataclass
class FileHeaderModel:
    string_opts: dict[str, str]
    int_opts: dict[str, int]
    raw: bytes  # исходные байты заголовка — для round-trip

    def as_dict(self) -> dict:
        return {"string_opts": dict(sorted(self.string_opts.items())),
                "int_opts": dict(sorted(self.int_opts.items()))}


@dataclass
class Segment:
    name: str
    decompressed: bytes
    compressed: bytes
    offset: int  # в исходном файле
    level: int | None = None  # родной уровень zlib (find_compression_level)

    def find_compression_level(self) -> int | None:
        """Перебор уровней 0–9: подобрать уровень, при котором
        zlib.compress(decompressed, level) == исходные сжатые байты (04 §4.3.3)."""
        if self.level is not None:
            return self.level
        hint = (self.compressed[1] >> 6) & 3 if len(self.compressed) >= 2 else None
        order = ([hint] if hint is not None else []) + [9, 6, 1, 0, 2, 3, 4, 5, 7, 8]
        for lvl in dict.fromkeys(order):
            if zlib.compress(self.decompressed, lvl) == self.compressed:
                self.level = lvl
                return lvl
        return None


@dataclass
class S2mFile:
    path: Path | None
    file_header: FileHeaderModel
    segments: list[Segment]
    tail: bytes
    _src: bytes = field(repr=False, default=b"")

    # ---------- загрузка ----------
    @classmethod
    def load(cls, path: Path) -> "S2mFile":
        return cls.loads(path.read_bytes(), path=path)

    @classmethod
    def loads(cls, data: bytes, path: Path | None = None) -> "S2mFile":
        hdr, off = cls._parse_file_header(data)
        segments: list[Segment] = []
        while off < len(data) - 4:
            if not _is_zlib_start(data, off):
                break
            d = zlib.decompressobj()
            try:
                decompressed = d.decompress(data[off:])
            except zlib.error as e:  # обрывок в середине файла
                raise Sh2ParseError(f"zlib-сегмент #{len(segments)} повреждён: {e}") from e
            if not d.eof:  # обрезанный хвост потока — тоже битый файл
                raise Sh2ParseError(f"zlib-сегмент #{len(segments)} оборван (no eof)")
            consumed = len(data) - off - len(d.unused_data)
            if consumed <= 0:
                raise Sh2ParseError("нулевой progress zlib-потока")
            name = SEGMENT_NAMES[len(segments)] if len(segments) < len(SEGMENT_NAMES) \
                else f"extra{len(segments)}"
            segments.append(Segment(name=name, decompressed=decompressed,
                                    compressed=data[off:off + consumed], offset=off))
            off += consumed
        if len(segments) < 2:
            raise Sh2ParseError(f"найдено сегментов: {len(segments)} (ожидались ≥2)")
        tail = data[off:]
        return cls(path=path, file_header=hdr, segments=segments, tail=tail, _src=data)

    @staticmethod
    def _parse_file_header(b: bytes) -> tuple[FileHeaderModel, int]:
        off = 0

        def i32() -> int:
            nonlocal off
            if off + 4 > len(b):
                raise Sh2ParseError("обрыван целое в заголовке")
            from struct import unpack_from
            v, = unpack_from("<i", b, off)
            off += 4
            return v

        n = i32()
        if not 0 <= n <= MAX_TABLE_ROWS:
            raise Sh2ParseError(f"странное число строковых опций: {n}")
        strs: dict[str, str] = {}
        for _ in range(n):
            kl = i32()
            if not 1 <= kl <= MAX_KEY_LEN or off + kl + 4 > len(b):
                raise Sh2ParseError("битый ключ строковой опции")
            key = b[off:off + kl].decode("ascii", errors="replace")
            off += kl
            vs = i32()
            if vs < 0 or off + vs * 2 > len(b):
                raise Sh2ParseError("битое значение строковой опции")
            strs[key] = b[off:off + vs * 2].decode("utf-16-le", errors="replace")
            off += vs * 2
        m = i32()
        if not 0 <= m <= MAX_TABLE_ROWS:
            raise Sh2ParseError(f"странное число целых опций: {m}")
        ints: dict[str, int] = {}
        for _ in range(m):
            kl = i32()
            if not 1 <= kl <= MAX_KEY_LEN or off + kl + 4 > len(b):
                raise Sh2ParseError("битый ключ целой опции")
            key = b[off:off + kl].decode("ascii", errors="replace")
            off += kl
            ints[key] = i32()
        return FileHeaderModel(strs, ints, b[:off]), off

    # ---------- round-trip ----------
    def roundtrip_bytes(self) -> bytes:
        return self.file_header.raw + b"".join(s.compressed for s in self.segments) + self.tail

    def roundtrip_ok(self) -> bool:
        return self._src == self.roundtrip_bytes()

    def as_dict(self) -> dict:
        return {
            "path": str(self.path) if self.path else None,
            "file_header": self.file_header.as_dict(),
            "segments": [
                {"name": s.name, "decompressed_len": len(s.decompressed),
                 "compressed_len": len(s.compressed), "offset": s.offset,
                 "zlib_level": s.level}
                for s in self.segments],
            "tail_len": len(self.tail),
        }


def _is_zlib_start(b: bytes, o: int) -> bool:
    if o + 1 >= len(b):
        return False
    cmf = b[o]
    if (cmf & 0x0F) != 8:  # метод deflate(8), любое FLEVEL
        return False
    return ((cmf << 8) | b[o + 1]) % 31 == 0
