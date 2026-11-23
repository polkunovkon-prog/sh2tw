"""Шаблоны замков .aic (ТЗ 04 §4.3 «.aic», задача S2.9; реестр F4, 13 §F).

Документ формата: ref/OpenSH2-Notes/FileFormats/AIC.md (AicCastleReader.cs).
Файлы поставки — без magic-заголовка, little-endian, без версионности.

Раскладка (всё u32/int32 little-endian), смещения подтверждены корпусом
(43 из 47 файлов игры побайтово: len == 2928 + 8*N; см. tests/test_aic.py):

  [0]      N — число записей построек (doc: cap 262 144, файл cap 16 MiB)
  [4]      N × (word0, word1) — упорядоченные записи построек, 8N байт
           word0, байты от младшего к старшему: kind, локальный X, локальный Z,
           код поворота; word1: 16-битная группа, байт-параметр,
           сохранённый старший байт (AIC.md).
  [4+8N]   50 «general values» (u32) — # UNKNOWN(AIC.md: «General values
           (semantics retained as unknown)»; семантика — дифф-протокол 08 §8.6)
  [+200]   одно доп. значение u32 — # UNKNOWN(AIC.md: «Additional unknown
           value»; в корпусе AIVChap6_Olaf = 100)
  [+204]   24 списка × 10 точек = 240 int32 — кодировка Z*100+X, 0 = не
           используется (AIC.md)
  [+1164]  10 групп × 20 точек = 200 int32 — та же кодировка
  [+1964]  240 флагов (int32) — # UNKNOWN(AIC.md: «List flags ... retained
           without assigning unverified behavior»; в корпусе значения 0/1)
  [+2924]  дальше — «Optional preserved extension bytes»: хвост сверх
           обязательной длины сохраняется как есть (doc, строка 16 и 34).

Требуемая длина = 2928 + 8*N (AIC.md, строка 18; факт F4, перепроверен на
корпусе: 43/43 здоровых файлов точны). 4 тестовых файла поставки обрезаны
(AIC.md строка 33) — у них len < 2928+8N → парсер падает громко
(Sh2ParseError, 04 §4.7 «мутационная устойчивость»), а тесты корпуса помечают
их исключением с причиной — как в tests/corpus/corrupt_saves.txt для сейвов.

Кинданы донжонов (AIC.md): 20 деревянный, 21 малый, 22 средний, 23 большой;
PRIMARY_KEEP = ПОСЛЕДНЯЯ запись-донжон («PrimaryKeep returns the last keep
entry»). Нераспознанные kind/повороты/биты НЕ отбрасываются — entry хранит
исходные слова (word0/word1), свойства только декодируют поля.

Round-trip контракт: roundtrip_bytes() побайтово равна исходнику для всех
здоровых файлов корпуса (поля реупаковываются из декодированных слов,
extension-хвост переносится как есть).
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path

from .s2m_file import Sh2ParseError

# --- константы раскладки (AIC.md; перепроверено корпусом) --------------------
N_OFF = 0
ENTRY_OFF = 4
ENTRY_SIZE = 8            # два u32-слова на запись
SIZE_BASE = 2928          # требуемая длина = SIZE_BASE + 8*N (F4)
GENERAL_COUNT = 50        # general values: 50 × u32 — UNKNOWN(семантика)
EXTRA_COUNT = 1           # одно доп. значение u32 — UNKNOWN(семантика)
LIST_POINTS = 240         # 24 списка × 10 точек (int32, Z*100+X)
GROUP_POINTS = 200        # 10 групп × 20 точек (int32, Z*100+X)
LIST_FLAGS = 240          # флаг int32 на каждую точку списка — UNKNOWN(семантика)
MAX_ITEMS = 262_144       # cap числа записей (AIC.md, строка 31)
MAX_FILE = 16 << 20       # cap файла 16 MiB (AIC.md, строка 31)

KEEP_KINDS = {20: "wooden", 21: "small", 22: "medium", 23: "large"}  # AIC.md


@dataclass
class AicBuildEntry:
    """Запись постройки: точные исходные слова + декодированные поля (AIC.md)."""

    word0: int
    word1: int

    # word0: байты младший→старший: kind, X, Z, поворот (AIC.md, строки 19-20).
    @property
    def kind(self) -> int:
        return self.word0 & 0xFF

    @property
    def x(self) -> int:
        """Локальный X (байт 1 слова word0)."""
        return (self.word0 >> 8) & 0xFF

    @property
    def z(self) -> int:
        """Локальный Z (байт 2 слова word0)."""
        return (self.word0 >> 16) & 0xFF

    @property
    def rotation(self) -> int:
        """Код четвертного поворота (байт 3). # UNKNOWN(AIC.md: коды вне 0..3 не трактуем)."""
        return (self.word0 >> 24) & 0xFF

    # word1: 16-битная группа, байт-параметр, старший байт (AIC.md, строка 20).
    @property
    def group(self) -> int:
        return self.word1 & 0xFFFF

    @property
    def param(self) -> int:
        return (self.word1 >> 16) & 0xFF

    @property
    def high(self) -> int:
        """# UNKNOWN(AIC.md: «one preserved high byte») — сохраняется как есть."""
        return (self.word1 >> 24) & 0xFF

    @property
    def is_keep(self) -> bool:
        return self.kind in KEEP_KINDS

    def reconstruct(self) -> bytes:
        return struct.pack("<II", self.word0, self.word1)

    def as_dict(self) -> dict:
        return {"kind": self.kind, "x": self.x, "z": self.z,
                "rotation": self.rotation, "group": self.group,
                "param": self.param, "high": self.high}


def decode_point(v: int) -> tuple[int, int] | None:
    """Точка int32 → (X, Z) по кодировке Z*100+X (AIC.md, строка 26).

    0 = неиспользуемая точка → None. Для v < 0 возвращаем None:
    # UNKNOWN(разбивка отрицательных точек в AIC.md «signed int32» не
    описана) — сама точка при этом остаётся в raw-списке list_points.
    """
    if v == 0:
        return None
    if v < 0:  # UNKNOWN(кодировка отрицательных точек в AIC.md)
        return None
    return v % 100, v // 100


@dataclass
class AicFile:
    """Один .aic: N записей + фиксированные секции + extension-хвост."""

    path: Path | None
    n: int
    entries: list[AicBuildEntry]
    general_values: list[int]      # 50 u32 — UNKNOWN(семантика, AIC.md)
    extra_value: int               # 1 u32  — UNKNOWN(семантика, AIC.md)
    list_points: list[int]         # 240 int32 (Z*100+X; 0 = неисп.)
    group_points: list[int]        # 200 int32 (та же кодировка)
    list_flags: list[int]          # 240 int32 — UNKNOWN(семантика, AIC.md)
    extension: bytes = b""         # байты сверх 2928+8N — переносятся как есть
    _src: bytes = field(repr=False, default=b"")

    # ---------- загрузка ----------
    @classmethod
    def load(cls, path: Path) -> "AicFile":
        return cls.loads(path.read_bytes(), path=path)

    @classmethod
    def loads(cls, data: bytes, path: Path | None = None) -> "AicFile":
        if len(data) < 4:
            raise Sh2ParseError("файл .aic короче 4 байт — не N")
        if len(data) > MAX_FILE:
            raise Sh2ParseError(f"размер {len(data)} > cap 16 MiB (AIC.md)")
        n, = struct.unpack_from("<I", data, N_OFF)
        if n > MAX_ITEMS:
            raise Sh2ParseError(f"подозрительное N={n} > cap {MAX_ITEMS} (AIC.md)")
        need = SIZE_BASE + ENTRY_SIZE * n
        if len(data) < need:
            # 4 обрезанных тестовых файла поставки (AIC.md, строка 33) —
            # парсер падает громко, не «чинит» молча (04 §4.7).
            raise Sh2ParseError(
                f"обрезан: N={n}, требуется {need} байт (2928+8N, F4), "
                f"есть {len(data)} (deficit {need - len(data)})")
        entries = [AicBuildEntry(*struct.unpack_from("<II", data, ENTRY_OFF + 8 * i))
                   for i in range(n)]
        gen_off = ENTRY_OFF + ENTRY_SIZE * n
        general = struct.unpack_from(f"<{GENERAL_COUNT}I", data, gen_off)
        extra, = struct.unpack_from("<I", data, gen_off + 4 * GENERAL_COUNT)
        lp_off = gen_off + 4 * GENERAL_COUNT + 4 * EXTRA_COUNT
        lp = struct.unpack_from(f"<{LIST_POINTS}i", data, lp_off)
        gp_off = lp_off + 4 * LIST_POINTS
        gp = struct.unpack_from(f"<{GROUP_POINTS}i", data, gp_off)
        fl_off = gp_off + 4 * GROUP_POINTS
        fl = struct.unpack_from(f"<{LIST_FLAGS}i", data, fl_off)
        assert fl_off + 4 * LIST_FLAGS == need, "несхождение фиксированной раскладки"
        return cls(path=path, n=n, entries=entries, general_values=list(general),
                   extra_value=extra, list_points=list(lp), group_points=list(gp),
                   list_flags=list(fl), extension=data[need:], _src=data)

    # ---------- семантические convenience (только подтверждённые доком) ------
    @property
    def keep_entries(self) -> list[AicBuildEntry]:
        return [e for e in self.entries if e.is_keep]

    @property
    def primary_keep(self) -> AicBuildEntry | None:
        """ПОСЛЕДНЯЯ запись-донжон (AIC.md: «PrimaryKeep returns the last keep
        entry, matching the reference keep-marker scan»)."""
        keeps = self.keep_entries
        return keeps[-1] if keeps else None

    # ---------- round-trip ----------
    def roundtrip_bytes(self) -> bytes:
        out = bytearray()
        out += struct.pack("<I", self.n)
        for e in self.entries:
            out += e.reconstruct()
        out += struct.pack(f"<{GENERAL_COUNT}I", *self.general_values)
        out += struct.pack("<I", self.extra_value)
        out += struct.pack(f"<{LIST_POINTS}i", *self.list_points)
        out += struct.pack(f"<{GROUP_POINTS}i", *self.group_points)
        out += struct.pack(f"<{LIST_FLAGS}i", *self.list_flags)
        out += self.extension
        return bytes(out)

    def roundtrip_ok(self) -> bool:
        return self._src == self.roundtrip_bytes()

    def as_dict(self) -> dict:
        return {
            "path": str(self.path) if self.path else None,
            "n": self.n,
            "size": SIZE_BASE + ENTRY_SIZE * self.n,
            "extension_len": len(self.extension),
            "entries_sample": [e.as_dict() for e in self.entries[:8]],
            "keep_kinds_found": sorted({e.kind for e in self.entries if e.is_keep}),
            "nonzero_general": sum(1 for v in self.general_values if v),
            "nonzero_list_points": sum(1 for v in self.list_points if v),
            "nonzero_group_points": sum(1 for v in self.group_points if v),
            "flag_values": sorted(set(self.list_flags)),
        }
