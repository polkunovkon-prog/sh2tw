"""aic_diff.py — дифф-протокол 50 general values .aic (S5.5; 08 §8.6).

Семантика 50 значений UNKNOWN(AIC.md: «General values (semantics retained
as unknown)»). Шаги 1–2 протокола: матрица файл×позиция, CSV длинного
формата, кластерный отчёт по позициям. Гипотезы и A/B-проверки — живая
разметка ref/aic_general_values.md (V8b); GA использует только
подтверждённые значения.
"""
from __future__ import annotations

import warnings
from collections import Counter
from pathlib import Path

from ..formats.aic import GENERAL_COUNT, AicFile
from ..formats.s2m_file import Sh2ParseError


def general_values_matrix(aic_dir: Path | str) -> dict[str, list[int]]:
    """Матрица {имя файла: [50 значений]} по каталогу .aic (шаг 1).

    Битые (обрезанные) файлы пропускаются С ПОМЕТКОЙ — warning с причиной:
    их general values физически недоступны (4 тестовых файла поставки,
    AIC.md, строка 33).
    """
    d = Path(aic_dir)
    matrix: dict[str, list[int]] = {}
    if not d.is_dir():
        return {}
    for f in sorted(d.glob("*.aic")):
        if not f.is_file():
            continue
        try:
            model = AicFile.load(f)
        except Sh2ParseError as exc:
            warnings.warn(f"пропущен битый .aic {f.name}: {exc}",
                          stacklevel=2)
            continue
        values = list(model.general_values)
        if len(values) != GENERAL_COUNT:  # pragma: no cover — раскладка фиксирована
            warnings.warn(f"пропущен .aic {f.name}: general values "
                          f"{len(values)} ≠ {GENERAL_COUNT}", stacklevel=2)
            continue
        matrix[f.name] = values
    return matrix


def matrix_to_csv(matrix: dict[str, list[int]]) -> str:
    """Матрица → CSV длинного формата: колонки filename, position (0–49),
    value — по строке на (файл, позицию)."""
    lines = ["filename,position,value"]
    for name in sorted(matrix):
        for pos, value in enumerate(matrix[name]):
            lines.append(f"{name},{pos},{value}")
    return "\n".join(lines) + "\n"


def cluster_report(matrix: dict[str, list[int]]) -> str:
    """Кластерный отчёт по позициям (шаг 2, 08 §8.6): n_unique, min, max,
    most_common — материал для гипотез «значение N похоже на агрессию»."""
    lines = [
        "# Кластерный отчёт 50 general values (шаг 2 протокола 08 §8.6)",
        "",
        f"Файлов: {len(matrix)}; семантика всех позиций — UNKNOWN(AIC.md).",
        "",
        "| позиция | n_unique | min | max | most_common |",
        "|---|---:|---:|---:|---|",
    ]
    for pos in range(GENERAL_COUNT):
        values = [m[pos] for m in matrix.values()]
        if not values:
            lines.append(f"| {pos} | 0 | — | — | — |")
            continue
        counts = Counter(values)
        mode, freq = counts.most_common(1)[0]
        lines.append(f"| {pos} | {len(counts)} | {min(values)} | "
                     f"{max(values)} | {mode} ×{freq} |")
    return "\n".join(lines) + "\n"
