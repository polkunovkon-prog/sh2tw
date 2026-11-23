"""Точка входа CLI (архитектура 02: parse|diff|build|launch|ga|backup ...).

Запуск из корня репозитория:  PYTHONPATH=tools .venv/Scripts/python.exe -m sh2tw.cli <cmd>
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .paths import load_paths


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="sh2tw")
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("backup", help="бэкап Maps/ и Saves/ (S1.1)")
    b.add_argument("--dry-run", action="store_true", help="только манифест, без копирования")
    b.add_argument("--what", default="maps,saves", help="maps,saves — что бэкапить")

    cb = sub.add_parser("check-build", help="сверка exe с эталоном v1.5.0 (S1.2)")
    cb.add_argument("--report", default=None, help="путь отчёта V5.json")

    vr = sub.add_parser("validate-ref", help="валидация ref/*.csv (S2.0)")

    w = sub.add_parser("watch-saves", help="лог файл-событий Saves/ (S1.3, для V3a)")
    w.add_argument("--secs", type=float, default=600, help="сколько секунд наблюдать")
    w.add_argument("--interval", type=float, default=2.0, help="период поллинга, с")
    w.add_argument("--out", default="experiments/reports/watcher_saves.jsonl")

    args = ap.parse_args(argv)

    if args.cmd == "backup":
        from .backup import run_backup

        res = run_backup(load_paths(), dry_run=args.dry_run,
                         what=tuple(w.strip() for w in args.what.split(",")))
        print(json.dumps(res, ensure_ascii=False, indent=1))
        return 0

    if args.cmd == "check-build":
        from .check_build import check_build

        rep = check_build(load_paths(),
                          Path(args.report) if args.report else None)
        print(json.dumps(rep["metrics"]["checks"], ensure_ascii=False, indent=1))
        print("RESULT:", rep["result"])
        return 0 if all(c["match"] for c in rep["metrics"]["checks"].values()) else 1

    if args.cmd == "validate-ref":
        from .refvalidate import run_validate_ref

        repo = Path(__file__).resolve().parents[2]
        return run_validate_ref(repo)

    if args.cmd == "watch-saves":
        from .watcher import jsonl_logger, watch

        logf = jsonl_logger(Path(args.out))
        try:
            n = watch(load_paths().saves_dir, logf, interval=args.interval,
                      duration_s=args.secs)
        finally:
            logf.fh.close()  # type: ignore[attr-defined]
        print(json.dumps({"events": n, "out": args.out,
                          "watching": str(load_paths().saves_dir)}, ensure_ascii=False))
        return 0

    ap.error(f"неизвестная команда {args.cmd}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
