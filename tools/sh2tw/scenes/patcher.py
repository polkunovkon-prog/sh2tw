"""patcher.py — равнодлинные якорные патчи распакованных сегментов (S3.2, L1).

Контракт манифеста — 03 §3.8 (*.patch.json): патч адресуется НЕ абсолютным
смещением, а якорем (уникальная цепочка байт) + смещением от КОНЦА якоря.

Гарантии (ТЗ 05 §5.3):
- равнодлинность len(new) == len(expected) — проверяется при загрузке
  манифеста (PatchManifestError), патч никогда не меняет длину сегмента;
- якорь обязан встречаться в сегменте РОВНО 1 раз — иначе PatchAnchorError
  (защита от неоднозначности и от версии шаблона);
- байты по адресу обязаны равняться expected — иначе PatchMismatchError
  с контекстом ±16 байт (дифф для разработки, защита от версии шаблона);
- после применения манифеста сегмент обязан перечитываться парсером
  (интеграционная проверка — в generator.py, S3.8).

Процедура разработки патча (регламент 05 §5.3, человек + `diff-maps` CLI):
копия шаблона → правка одного поля в редакторе игры →
`python -m sh2tw.cli diff-maps original.s2m edited.s2m` → выбор якоря →
запись патча с expected_hex = старое значение.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

SCHEMA_VERSION = "1.0"
_CONTEXT = 16  # байт контекста в сообщении об ошибке (05 §5.3: ±16)


class PatchError(Exception):
    """Базовая ошибка патчера."""


class PatchManifestError(PatchError):
    """Манифест некорректен (структура/равнодлинность/дубликаты id)."""


class PatchAnchorError(PatchError):
    """Якорь не найден или найден более одного раза."""

    def __init__(self, patch_id: str, occurrences: int):
        self.patch_id = patch_id
        self.occurrences = occurrences
        super().__init__(f"патч {patch_id!r}: якорь встречается {occurrences} раз "
                         f"(обязан ровно 1)")


class PatchMismatchError(PatchError):
    """Байты по адресу не равны expected (версия шаблона отличается)."""

    def __init__(self, patch_id: str, offset: int, expected: bytes,
                 found: bytes, context: bytes):
        self.patch_id = patch_id
        self.offset = offset
        self.expected = expected
        self.found = found
        super().__init__(
            f"патч {patch_id!r} @{offset}: ожидалось {expected.hex(' ')}, "
            f"факт {found.hex(' ')}; контекст: {context.hex(' ')}")


_HEX_RE = re.compile(r"^([0-9a-fA-F]{2}\s*)+$")


def parse_hex(s: str) -> bytes:
    """Строка 'E8 03 00 00' → bytes; не-хекс — PatchManifestError."""
    s = (s or "").strip()
    if not s or not _HEX_RE.match(s):
        raise PatchManifestError(f"не hex-строка: {s!r}")
    return bytes.fromhex(s.replace(" ", ""))


def find_all(buf: bytes, needle: bytes) -> list[int]:
    """Все вхождения needle в buf (поиск без пересечений)."""
    out: list[int] = []
    i = buf.find(needle)
    while i >= 0:
        out.append(i)
        i = buf.find(needle, i + 1)
    return out


@dataclass
class Patch:
    id: str
    anchor: bytes
    anchor_offset: int
    expected: bytes
    new: bytes
    notes: str = ""

    def as_dict(self) -> dict:
        return {"id": self.id, "anchor_hex": self.anchor.hex(" ").upper(),
                "anchor_offset": self.anchor_offset,
                "expected_hex": self.expected.hex(" ").upper(),
                "new_hex": self.new.hex(" ").upper(),
                "length_check": len(self.expected), "notes": self.notes}


@dataclass
class PatchManifest:
    """Один файл *.patch.json (03 §3.8) на шаблон карты."""
    template_id: str
    template_file: str
    template_sha256: str
    patches: list[Patch] = field(default_factory=list)
    source_path: Path | None = None

    @classmethod
    def from_dict(cls, d: dict, source_path: Path | None = None) -> "PatchManifest":
        if not isinstance(d, dict) or d.get("schema_version") != SCHEMA_VERSION:
            raise PatchManifestError(
                f"schema_version {d.get('schema_version')!r} != {SCHEMA_VERSION!r}")
        man = cls(template_id=str(d.get("template_id", "")),
                  template_file=str(d.get("template_file", "")),
                  template_sha256=str(d.get("template_sha256", "")),
                  source_path=source_path)
        if not man.template_id:
            raise PatchManifestError("пустой template_id")
        seen: set[str] = set()
        for i, p in enumerate(d.get("patches") or []):
            pid = str(p.get("id") or f"patch_{i}")
            if pid in seen:
                raise PatchManifestError(f"дубль id патча: {pid}")
            seen.add(pid)
            anchor = parse_hex(p.get("anchor_hex", ""))
            expected = parse_hex(p.get("expected_hex", ""))
            new = parse_hex(p.get("new_hex", ""))
            if not anchor:
                raise PatchManifestError(f"{pid}: пустой якорь")
            if len(new) != len(expected):
                raise PatchManifestError(
                    f"{pid}: нарушение равнодлинности "
                    f"len(new)={len(new)} != len(expected)={len(expected)} (03 §3.8)")
            lc = p.get("length_check")
            if isinstance(lc, int) and lc != len(expected):
                raise PatchManifestError(
                    f"{pid}: length_check={lc} != len(expected_hex)={len(expected)}")
            try:
                anchor_offset = int(p.get("anchor_offset", 0))
            except (TypeError, ValueError):
                raise PatchManifestError(f"{pid}: anchor_offset не целое")
            man.patches.append(Patch(id=pid, anchor=anchor,
                                     anchor_offset=anchor_offset,
                                     expected=expected, new=new,
                                     notes=str(p.get("notes", ""))))
        return man

    @classmethod
    def load(cls, path: Path) -> "PatchManifest":
        path = Path(path)
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            raise PatchManifestError(f"{path.name}: {e}") from e
        return cls.from_dict(d, source_path=path)

    def as_dict(self) -> dict:
        return {"schema_version": SCHEMA_VERSION,
                "template_id": self.template_id,
                "template_file": self.template_file,
                "template_sha256": self.template_sha256,
                "patches": [p.as_dict() for p in self.patches]}


def apply_patches(segment: bytes, manifest: PatchManifest) -> bytes:
    """Применяет патчи строго по порядку; любой конфликт — исключение
    (сигнатура ТЗ 05 §5.3). Сегмент не меняет длину (равнодлинность)."""
    buf = bytes(segment)
    for p in manifest.patches:
        positions = find_all(buf, p.anchor)
        if len(positions) != 1:
            raise PatchAnchorError(p.id, len(positions))
        off = positions[0] + len(p.anchor) + p.anchor_offset
        end = off + len(p.expected)
        if end > len(buf):
            raise PatchMismatchError(p.id, off, p.expected, b"",
                                     buf[max(0, off - _CONTEXT):off + _CONTEXT])
        found = buf[off:end]
        if found != p.expected:
            ctx = buf[max(0, off - _CONTEXT):min(len(buf), end + _CONTEXT)]
            raise PatchMismatchError(p.id, off, p.expected, found, ctx)
        buf = buf[:off] + p.new + buf[end:]
    return buf


# ------------------------------------------------------- разработка патчей
def diff_buffers(a: bytes, b: bytes, context: int = _CONTEXT) -> list[dict]:
    """Различия двух равнодлинных буферов → список {offset, a_hex, b_hex,
    context_hex} (основа `diff-maps`, процедура 05 §5.3 п.3).

    Буферы разной длины — ошибка: равнодлинный патчинг не про это;
    добавление/удаление — территория писателя L2 (05 §5.3 «граница»).
    """
    if len(a) != len(b):
        raise PatchError(f"равнодлинность нарушена: {len(a)} != {len(b)} байт — "
                         f"это правка писателя L2, не патчера")
    out: list[dict] = []
    i = 0
    while i < len(a):
        if a[i] == b[i]:
            i += 1
            continue
        j = i
        while j < len(a) and a[j] != b[j]:
            j += 1
        out.append({
            "offset": i,
            "length": j - i,
            "a_hex": a[i:j].hex(" ").upper(),
            "b_hex": b[i:j].hex(" ").upper(),
            "context_hex": a[max(0, i - context):j + context].hex(" ").upper(),
            "context_offset": max(0, i - context),
        })
        i = j
    return out
