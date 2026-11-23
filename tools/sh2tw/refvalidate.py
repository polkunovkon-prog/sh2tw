"""S2.0: валидация ref/unit_types.csv + ref/buildings.csv (архитектура 02, §D справочники).

Консервативный контракт UNKNOWN: до финальных внутриигровых замеров (V7c)
числовые поля могут быть литералом UNKNOWN — валидатор требует только
синтаксис (число или UNKNOWN), уникальность class_name и непустоту файлов.
"""
from __future__ import annotations
import csv
from pathlib import Path

NUM_COLS = ("gold", "honour", "unit_value", "aic_kind")
REQUIRED = {"unit_types.csv": ("class_name", "gold"),
            "buildings.csv": ("class_name",)}


def validate_ref(root: Path) -> tuple[list[str], dict[str, dict]]:
    errs: list[str] = []
    stats: dict[str, dict] = {}
    for name, req in REQUIRED.items():
        p = root / "ref" / name
        if not p.exists():
            errs.append(f"{name}: файл не найден")
            continue
        rows = list(csv.DictReader(p.read_text(encoding="utf-8").splitlines()))
        if not rows:
            errs.append(f"{name}: пуст")
            continue
        cols = set(rows[0].keys())
        for c in req:
            if c not in cols:
                errs.append(f"{name}: нет колонки {c}")
        ids = [(r.get("class_name") or "").strip() for r in rows]
        if any(not x for x in ids):
            errs.append(f"{name}: пустой class_name (строки {[i+2 for i,x in enumerate(ids) if not x]})")
        dupes = sorted({x for x in ids if ids.count(x) > 1})
        if dupes:
            errs.append(f"{name}: дубли class_name: {dupes}")
        known = 0
        for i, r in enumerate(rows, 2):
            numeric = {c: (r.get(c) or "").strip() for c in cols if c in NUM_COLS}
            if any(v not in ("", "UNKNOWN") for v in numeric.values()):
                known += 1
            for c, v in numeric.items():
                if v in ("", "UNKNOWN"):
                    if v == "":
                        errs.append(f"{name}:{i}: пустое поле {c}")
                elif not v.lstrip("-").isdigit():
                    errs.append(f"{name}:{i}: не число в {c}: {v!r}")
        stats[name] = {"rows": len(rows), "rows_with_numbers": known}
    return errs, stats


def run_validate_ref(root: Path) -> int:
    errs, stats = validate_ref(root)
    for k, v in stats.items():
        print(f"{k}: строк {v['rows']}, с числовыми данными {v['rows_with_numbers']} "
              f"(UNKNOWN-строки — до замеров V7c)")
    if errs:
        print("ОШИБКИ:")
        for e in errs:
            print(" -", e)
        return 1
    print("RESULT: ref-контракт выполним (валидация пройдена)")
    return 0
