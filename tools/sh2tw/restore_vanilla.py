"""restore_vanilla.py — полный откат игры к ванильному состоянию (S8.7, DoD 8).

Что делает (регламент 00 §0.7 — каталог игры чужая территория):
1. Удаляет все сгенерированные карты S2TW_* из Maps/ (в т.ч. .build.json).
2. Восстанавливает gameRules.dat из бэкапа, если установка доктрин
   делала копию (backup/gameRules.dat.orig рядом или backup_dir).
3. Восстанавливает .aic-файлы, изменённые установкой доктрин
   (backup/*.aic.orig).
4. НЕ трогает: ванильные карты, сейвы, конфиг проекта.

Всё с --dry-run по умолчанию: сначала список изменений, потом применение.

Запуск (из корня репо): PYTHONPATH=tools python -m sh2tw.restore_vanilla
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from sh2tw.paths import load_paths

REPO_ROOT = Path(__file__).resolve().parents[1]


def _restore_backups(game_dir: Path, dry_run: bool) -> list[str]:
    """Восстановление файлов, изменённых установкой доктрин (08 §8.5)."""
    actions: list[str] = []
    # gameRules: бэкап кладётся рядом как gameRules.dat.sh2tw_bak
    gr = game_dir / "gameRules.dat"
    gr_bak = game_dir / "gameRules.dat.sh2tw_bak"
    if gr_bak.exists() and gr.exists():
        actions.append(f"восстановить gameRules.dat из {gr_bak.name}")
        if not dry_run:
            shutil.copy2(gr_bak, gr)
            gr_bak.unlink()
    # .aic: бэкапы castles/*.aic.sh2tw_bak
    aic_dir = game_dir / "castles"
    if aic_dir.is_dir():
        for bak in sorted(aic_dir.glob("*.aic.sh2tw_bak")):
            orig = bak.with_suffix("")  # x.aic.sh2tw_bak → x.aic.
            orig = bak.parent / bak.name[: -len(".sh2tw_bak")]
            actions.append(f"восстановить {orig.name} из бэкапа")
            if not dry_run and orig.exists():
                shutil.copy2(bak, orig)
                bak.unlink()
    return actions


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="restore_vanilla",
        description="Откат игры к ванили: S2TW_*-карты + изменённые "
                    "gameRules/aic из бэкапов (ТЗ 11.3 DoD-8)")
    ap.add_argument("--dry-run", action="store_true", default=True,
                    help="только показать план (по умолчанию)")
    ap.add_argument("--no-dry-run", dest="dry_run", action="store_false",
                    help="применить изменения")
    ap.add_argument("--maps-dir", default=None,
                    help="каталог Maps (по умолчанию maps_dir_game из project.ini)")
    args = ap.parse_args(argv)

    try:
        p = load_paths()
        maps_dir = Path(args.maps_dir) if args.maps_dir else p.maps_dir_game
        game_dir = p.game_dir
    except Exception as e:  # configparser/pathlib — конфиг может отсутствовать
        print(f"ОШИБКА config/project.ini: {e}", file=sys.stderr)
        return 1

    plan: dict = {"dry_run": args.dry_run, "maps_dir": str(maps_dir),
                  "remove_s2tw": [], "restore_backups": [], "errors": []}
    if maps_dir.is_dir():
        plan["remove_s2tw"] = sorted(
            p.name for p in maps_dir.glob("S2TW_*")
            if p.suffix.lower() in (".s2m", ".json"))
    else:
        plan["errors"].append(f"каталог Maps не найден: {maps_dir}")
    plan["restore_backups"] = _restore_backups(game_dir, args.dry_run)

    print(json.dumps(plan, ensure_ascii=False, indent=1))
    if args.dry_run:
        print("\nDRY-RUN: ничего не применено; повторите с --no-dry-run")
        return 0

    removed = 0
    for name in plan["remove_s2tw"]:
        try:
            (maps_dir / name).unlink()
            removed += 1
        except OSError as e:
            plan["errors"].append(f"{name}: {e}")
    print(json.dumps({"removed_s2tw": removed,
                      "restored": plan["restore_backups"],
                      "errors": plan["errors"]}, ensure_ascii=False, indent=1))
    return 1 if plan["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
