"""archetypes.py — 6 архетипов .aic: профили, клон+правки, синтез (S5.2; 08 §8.2, §8.4).

Два режима (08 §8.2 «клоны+правки»):
- КЛОН (основной): ванильный .aic из файлов игры; правим ТОЛЬКО
  документированные поля записей — group/param, копии и удаления записей
  (формат позволяет); kind вне донжонов — # UNKNOWN(AIC.md), не трогаем;
  general values / точки / флаги переносятся без изменений (семантика
  UNKNOWN, дифф-протокол 08 §8.6).
- СИНТЕЗ (fallback): единственная запись-донжон (kind 20–23 из AIC.md,
  X=48 Z=40 rot=0 — пример Олафа), general values = 50×0xFFFFFFFF,
  точки/флаги нули; честная пометка mode="synthetic_keep_only".
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass
from pathlib import Path

from ..formats.aic import (GENERAL_COUNT, GROUP_POINTS, LIST_FLAGS, LIST_POINTS,
                           AicBuildEntry, AicFile)
from ..formats.s2m_file import Sh2ParseError


class DoctrineError(Exception):
    """Ошибка подсистемы доктрин (архетип, путь, валидация)."""


SYNTHETIC_WARNING = (
    "полный план замка — только клон ванильного .aic (файлы игры); "
    "synthetic = донжон+UNKNOWN-секции")

# 6 архетипов (08 §8.4: id, имя, акцент, тайминг; kind донжонов — AIC.md
# 20 деревянный / 21 малый / 22 средний / 23 большой). Числовые поля лежат
# в диапазонах 08 §8.3, чтобы default_genome прошёл валидацию.
ARCHETYPES: dict[str, dict] = {
    "hedgehog": {
        "name_ru": "«Ёж»",
        "accent": "глухие стены, башни лучников, kill-zone у ворот",
        "timing": "поздний",
        "keep_kind": 22,
        "ranged_share": 0.50, "melee_share": 0.30,
        "first_attack_month": 26, "wave_count": 2,
        "wave_gap_months": 5, "wave_size_base": 20,
        "siege_mix": {},
    },
    "archer": {
        "name_ru": "«Лучник»",
        "accent": "фланкирующий огонь, внешние башни, рвы",
        "timing": "средний",
        "keep_kind": 21,
        "ranged_share": 0.50, "melee_share": 0.30,
        "first_attack_month": 14, "wave_count": 3,
        "wave_gap_months": 4, "wave_size_base": 22,
        "siege_mix": {},
    },
    "sieger": {
        "name_ru": "«Осадник»",
        "accent": "крепость + осадные мастерские в плане замка",
        "timing": "средне-поздний",
        "keep_kind": 21,
        "ranged_share": 0.35, "melee_share": 0.55,
        "first_attack_month": 18, "wave_count": 3,
        "wave_gap_months": 4, "wave_size_base": 26,
        "siege_mix": {"ram": 1, "tower": 1, "catapult": 2, "ladders": 4},
    },
    "raider": {
        "name_ru": "«Рейдер»",
        "accent": "лёгкий замок, конюшни, быстрые выходы",
        "timing": "ранний",
        "keep_kind": 20,
        "ranged_share": 0.30, "melee_share": 0.65,
        "first_attack_month": 8, "wave_count": 2,
        "wave_gap_months": 3, "wave_size_base": 15,
        "siege_mix": {},
    },
    "balanced": {
        "name_ru": "«Баланс»",
        "accent": "сбалансированный план, упор на экономику",
        "timing": "адаптивный",
        "keep_kind": 22,
        "ranged_share": 0.45, "melee_share": 0.50,
        "first_attack_month": 16, "wave_count": 3,
        "wave_gap_months": 4, "wave_size_base": 20,
        "siege_mix": {},
    },
    "fortress": {
        "name_ru": "«Крепость»",
        "accent": "многослойные стены, ловушки, редуты",
        "timing": "поздний",
        "keep_kind": 23,
        "ranged_share": 0.40, "melee_share": 0.55,
        "first_attack_month": 26, "wave_count": 2,
        "wave_gap_months": 5, "wave_size_base": 28,
        "siege_mix": {},
    },
}


@dataclass(frozen=True)
class EntryTransform:
    """Правки клона ванильного .aic (08 §8.2 «клонировать → править»).

    # UNKNOWN(AIC.md: семантика group/param записей вне донжонов не
    # документирована — «future builder inputs»; сдвиги ниже — проектная
    # эвристика, эффект проверяется живым прогоном V12, 08 §8.5).
    kind НЕ меняется никогда; донжоны (kind 20–23) не трогаем вовсе —
    основной донжон обязан остаться ПОСЛЕДНЕЙ записью-донжоном
    (PrimaryKeep, AIC.md).
    """

    group_shift: int = 0     # сдвиг 16-битной группы записей не-донжонов
    param_boost: int = 0     # прибавка к байту-параметру записей не-донжонов
    duplicate_tail: int = 0  # продублировать N последних не-донжонов
    remove_tail: int = 0     # убрать N последних не-донжонов (лёгкий замок)


ARCHETYPE_TRANSFORMS: dict[str, EntryTransform] = {
    "hedgehog": EntryTransform(group_shift=2, duplicate_tail=1),   # стены
    "archer": EntryTransform(group_shift=1, param_boost=1),        # башни
    "sieger": EntryTransform(group_shift=3, param_boost=2,         # мастерские
                             duplicate_tail=2),
    "raider": EntryTransform(group_shift=1, remove_tail=2),        # лёгкий
    "balanced": EntryTransform(group_shift=2),                     # мягко
    "fortress": EntryTransform(group_shift=4, param_boost=1,       # слои стен
                               duplicate_tail=3),
}


def _profile(archetype_id: str) -> dict:
    """Профиль по id; неизвестный id — DoctrineError (антигаллюцинация)."""
    prof = ARCHETYPES.get(archetype_id)
    if prof is None:
        raise DoctrineError(
            f"неизвестный архетип {archetype_id!r}; доступны: "
            f"{', '.join(sorted(ARCHETYPES))} (08 §8.4)")
    return prof


def _synthetic_keep_entry(kind: int) -> AicBuildEntry:
    """Запись-донжон (48,40), rot 0, group 1 — по примеру Олафа из AIC.md
    (первые слова AIVChap6_Olaf.aic: 0x00283014, 0x00000001)."""
    word0 = (kind & 0xFF) | (48 << 8) | (40 << 16)   # kind, X, Z, rot=0
    return AicBuildEntry(word0=word0, word1=1)       # group 1, param 0, high 0


def _assemble(entries: list[AicBuildEntry], general_values: list[int],
              extra_value: int, list_points: list[int],
              group_points: list[int], list_flags: list[int],
              extension: bytes) -> bytes:
    """Сборка .aic сериализатором AicFile (длина обязана быть 2928+8N)."""
    model = AicFile(path=None, n=len(entries), entries=entries,
                    general_values=list(general_values), extra_value=int(extra_value),
                    list_points=list(list_points), group_points=list(group_points),
                    list_flags=list(list_flags), extension=extension)
    return model.roundtrip_bytes()


def _apply_transform(base: AicFile, tr: EntryTransform) -> list[AicBuildEntry]:
    """Клон+правки: удалить/дублировать не-донжоны, сдвинуть group/param.

    Донжоны и их слова не трогаем: PrimaryKeep = последняя запись-донжон
    (AIC.md) обязана сохраниться; kind менять запрещено (08 §8.2).
    """
    entries = list(base.entries)

    def _drop_last_nonkeep() -> bool:
        for i in range(len(entries) - 1, -1, -1):
            if not entries[i].is_keep:
                del entries[i]
                return True
        return False

    for _ in range(max(0, tr.remove_tail)):
        if not _drop_last_nonkeep():
            break
    if tr.duplicate_tail > 0:
        tail = [e for e in entries if not e.is_keep][-tr.duplicate_tail:]
        entries = entries + [AicBuildEntry(word0=e.word0, word1=e.word1)
                             for e in tail]
    if tr.group_shift or tr.param_boost:
        shifted: list[AicBuildEntry] = []
        for e in entries:
            if e.is_keep:
                shifted.append(e)
                continue
            group = max(0, min(0xFFFF, e.group + tr.group_shift))
            param = max(0, min(0xFF, e.param + tr.param_boost))
            word1 = (e.high << 24) | (param << 16) | group
            shifted.append(AicBuildEntry(word0=e.word0, word1=word1))
        entries = shifted
    return entries


def load_base_aic(base_dir: Path | str | None) -> Path | None:
    """Путь первого читаемого *.aic в каталоге (база клона) или None.

    Обрезанные тестовые файлы поставки (AIC.md, строка 33) пропускаются
    с пометкой-предупреждением — клонить нечего, general values нет.
    """
    if base_dir is None:
        return None
    d = Path(base_dir)
    if not d.is_dir():
        return None
    for f in sorted(d.glob("*.aic")):
        if not f.is_file():
            continue
        try:
            AicFile.load(f)
        except Sh2ParseError as exc:
            warnings.warn(f"пропущен битый .aic {f.name}: {exc}",
                          stacklevel=2)
            continue
        return f
    return None


def build_archetype_aic(archetype_id: str,
                        base_path: Path | str | None = None) -> bytes:
    """Валидный .aic архетипа: клон base_path (режим клона) или синтез.

    Клон: AicFile.load(base_path) → transform записей (group/param/копии/
    удаления; kind — НЕТ) → roundtrip; general values/точки/флаги и хвост
    переносятся как есть. Синтез: одна запись-донжон kind из профиля.
    """
    prof = _profile(archetype_id)
    if base_path is not None:
        bp = Path(base_path)
        if not bp.is_file():
            raise DoctrineError(
                f"база клона не найдена: {bp} (режим клона требует ванильный "
                f".aic из файлов игры, 08 §8.2)")
        try:
            base = AicFile.load(bp)
        except Sh2ParseError as exc:
            raise DoctrineError(f"база клона не читается: {exc}") from exc
        entries = _apply_transform(base, ARCHETYPE_TRANSFORMS[archetype_id])
        return _assemble(entries, base.general_values, base.extra_value,
                         base.list_points, base.group_points, base.list_flags,
                         base.extension)
    keep = _synthetic_keep_entry(int(prof["keep_kind"]))
    # 0xFFFFFFFF — UNKNOWN-маркер корпуса (tests/test_aic.py): семантика
    # 50 значений не документирована (AIC.md), дифф-протокол 08 §8.6.
    return _assemble([keep], [0xFFFFFFFF] * GENERAL_COUNT, 0,
                     [0] * LIST_POINTS, [0] * GROUP_POINTS, [0] * LIST_FLAGS,
                     b"")


def build_archetype_aic_result(archetype_id: str,
                               base_path: Path | str | None = None) -> dict:
    """{"data", "mode", "warning"} — байты .aic + честная пометка режима."""
    data = build_archetype_aic(archetype_id, base_path)
    if base_path is None:
        return {"data": data, "mode": "synthetic_keep_only",
                "warning": SYNTHETIC_WARNING}
    return {"data": data, "mode": "clone", "warning": None}


def write_archetypes(out_dir: Path | str,
                     base_dir: Path | str | None = None) -> dict[str, dict]:
    """Записать 6 файлов aic_<id>_v1.aic → {archetype: {"path", "mode"}}.

    base_dir задан и содержит читаемый .aic → режим клона для всех
    архетипов (правки у каждого свои); иначе — честный синтез.
    """
    base_path = load_base_aic(base_dir) if base_dir is not None else None
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    result: dict[str, dict] = {}
    for aid in ARCHETYPES:
        res = build_archetype_aic_result(aid, base_path)
        AicFile.loads(res["data"])  # самопроверка формата перед записью
        path = out / f"aic_{aid}_v1.aic"
        path.write_bytes(res["data"])
        result[aid] = {"path": path, "mode": res["mode"]}
    return result
