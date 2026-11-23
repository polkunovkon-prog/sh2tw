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

    cm = sub.add_parser("catalog-maps", help="реестр карт-заготовок → ref/maps_catalog.csv (S3.0)")
    cm.add_argument("maps_dir", nargs="?", default=None,
                    help="разобрать один каталог (по умолчанию: maps_dir_game + maps_dir_user из project.ini)")
    cm.add_argument("--out", default=None, help="путь CSV (по умолчанию ref/maps_catalog.csv)")

    pr = sub.add_parser("parse", help="карта/сейв (.s2m/.sh2) → snapshot.json (S2.6, контракт 03 §3.5)")
    pr.add_argument("path", help=".s2m (карта) или .sh2 (сейв)")
    pr.add_argument("--out", default=None,
                    help="файл snapshot.json (без --out снимок печатается в stdout). "
                         "Практическая уступка git-bash: '/tmp/...' разрешается в "
                         "системный temp (tempfile.gettempdir()), т.к. нативный python3 "
                         "писал бы '/tmp/...' в C:\\mp")

    df = sub.add_parser("diff", help="diff двух snapshot.json (.json) либо двух "
                                     "файлов .s2m/.sh2 через встроенный parse "
                                     "(S2.7, 04 §4.2/§4.6)")
    df.add_argument("a", help="snapshot.json ИЛИ .s2m/.sh2 (разберём сами)")
    df.add_argument("b", help="snapshot.json ИЛИ .s2m/.sh2 (разберём сами)")
    df.add_argument("--out", default=None,
                    help="файл diff-документа (без --out — в stdout; "
                         "'/tmp/...' -> системный temp, как у parse)")

    dmm = sub.add_parser("diff-maps", help="побайтовое сравнение двух карт/сейвов "
                                       "по сегментам (S3.2, процедура 05 §5.3)")
    dmm.add_argument("a", help="эталон .s2m/.sh2")
    dmm.add_argument("b", help="правленая копия .s2m/.sh2")
    dmm.add_argument("--out", default=None, help="файл отчёта JSON "
                     "(без --out — краткая сводка в stdout)")

    hn = sub.add_parser("honesty", help="протокол честности матча (S2.8, 04 §4.6): "
                                     "start.json end.json spec.json")
    hn.add_argument("start", help="snapshot.json старта (или .sh2/.s2m — разберём)")
    hn.add_argument("end", help="snapshot.json конца (или .sh2/.s2m — разберём)")
    hn.add_argument("spec", help="scene_spec.json сцены")
    hn.add_argument("--out", default=None, help="файл honesty_report.json "
                     "(без --out — в stdout; '/tmp/...' -> системный temp)")
    hn.add_argument("--check-balance", action="store_true",
                    help="только проверка provision_balance(spec) — до матча (05 §5.2)")

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

    if args.cmd == "catalog-maps":
        from .catalog_maps import run_catalog_maps

        repo = Path(__file__).resolve().parents[2]
        res = run_catalog_maps(repo,
                               Path(args.maps_dir) if args.maps_dir else None,
                               Path(args.out) if args.out else None)
        print(json.dumps(res, ensure_ascii=False, indent=1))
        if res["failures"]:
            print("БОКЕРЫ (не прошли декод):", *res["failures"], sep="\n  ")
        return 0 if not res["failures"] else 1

    if args.cmd == "parse":
        from .formats.s2m_file import Sh2ParseError
        from .snapshot_builder import parse_snapshot, resolve_out_path

        out_path = resolve_out_path(args.out) if args.out else None
        try:
            snap = parse_snapshot(Path(args.path), out_path)
        except (Sh2ParseError, OSError) as e:  # 04 §4.7: падать быстро и ГРОМКО
            print(f"ОШИБКА РАЗБОРА: {type(e).__name__}: {e}", file=sys.stderr)
            return 1
        if out_path is not None:
            print(json.dumps({
                "out": str(out_path), "source": snap["source"]["file"],
                "sha256": snap["source"]["sha256"], "map": snap["map"],
                "buildings": len(snap["buildings"]), "actors": len(snap["actors"]),
                "estates": len(snap["estates"]),
                "raw_unknown_objects": snap["raw_unknown_objects"],
                "s2game_objects_total": snap["census"]["s2game_objects_total"],
                "coverage": snap["census"]["coverage"],
                "parse_errors": snap["parse_errors"],
            }, ensure_ascii=False, indent=1))
        else:
            from .snapshot_builder import snapshot_json
            print(snapshot_json(snap))
        return 0

    if args.cmd == "diff":
        from .diff_engine import diff_snapshots, diff_json
        from .formats.s2m_file import Sh2ParseError
        from .snapshot_builder import resolve_out_path

        out_path = resolve_out_path(args.out) if args.out else None
        try:
            doc = diff_snapshots(Path(args.a), Path(args.b), out_path)
        except (Sh2ParseError, OSError, ValueError) as e:  # 04 §4.7: ГРОМКО
            print(f"ОШИБКА DIFF: {type(e).__name__}: {e}", file=sys.stderr)
            return 1
        if out_path is not None:
            print(json.dumps({"out": str(out_path), "from": doc["from"]["file"],
                              "to": doc["to"]["file"], "summary": doc["summary"]},
                             ensure_ascii=False, indent=1))
        else:
            print(diff_json(doc))
        return 0

    if args.cmd == "diff-maps":
        from .formats.s2m_file import Sh2ParseError
        from .scenes.diff_maps import diff_maps_json, run_diff_maps
        from .scenes.patcher import PatchError
        from .snapshot_builder import resolve_out_path

        out_path = resolve_out_path(args.out) if args.out else None
        try:
            doc = run_diff_maps(Path(args.a), Path(args.b), out_path)
        except (Sh2ParseError, PatchError, OSError) as e:
            print(f"ОШИБКА DIFF-MAPS: {type(e).__name__}: {e}", file=sys.stderr)
            return 1
        if out_path is not None:
            print(json.dumps({"out": str(out_path),
                              "summary": doc["summary"]}, ensure_ascii=False, indent=1))
        else:
            print(diff_maps_json(doc))
        return 0

    if args.cmd == "honesty":
        import json as _json

        from .diff_engine import load_snapshot
        from .honesty.accounting import (HonestyError, provision_balance_detail,
                                         report_json)
        from .honesty.accounting import honesty_report as make_report
        from .snapshot_builder import resolve_out_path

        out_path = resolve_out_path(args.out) if args.out else None
        try:
            if args.check_balance:
                spec = _json.loads(Path(args.spec).read_text(encoding="utf-8"))
                det = provision_balance_detail(spec)
                doc = {"schema_version": "1.0", "mode": "provision_balance",
                       "scene_id": spec.get("scene_id"), **det.as_dict()}
            else:
                spec = _json.loads(Path(args.spec).read_text(encoding="utf-8"))
                report = make_report(load_snapshot(Path(args.start)),
                                     load_snapshot(Path(args.end)), spec)
                doc = report
        except (HonestyError, OSError, ValueError) as e:
            print(f"ОШИБКА HONESTY: {type(e).__name__}: {e}", file=sys.stderr)
            return 1
        text = report_json(doc)
        if out_path is not None:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(text + "\n", encoding="utf-8")
            print(_json.dumps({"out": str(out_path), "verdict": doc.get("verdict"),
                               "ok": doc.get("ok")}, ensure_ascii=False))
        else:
            print(text)
        verdict = doc.get("verdict", doc.get("ok"))
        return 0 if (verdict in ("pass", True)) else 1

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
