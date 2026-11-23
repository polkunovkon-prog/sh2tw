"""launcher.py — запуск игры со сценой (S3.7; ТЗ 05 §5.7 «лестница»).

Лестница (закрывается V2, до того — инструкция человеку):
  (a) os.startfile(карта) — если ассоциация .s2m зарегистрирована
      (Steam-установка; в репаке ассоциаций нет — G12). Только Windows.
  (b) запуск Stronghold2.exe + человек выбирает карту в меню
      (имя S2TW_* сортируется в начало списка — 05 §5.7).
  (c) AutoHotkey-нажатия — НЕ реализовано (только с согласия человека, 05).

Правило 00 §0.7: любой запуск — с планом в --dry-run; агент игру сам не
запускает (00 §0.8) — запуск инициирует человек (оболочка/CLI).
"""
from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass
class LaunchPlan:
    mode: str            # startfile | exe | instruction
    map_path: Path
    exe_path: Path | None
    instruction: str
    command: list[str] | None = None

    def as_dict(self) -> dict:
        return {"mode": self.mode, "map": str(self.map_path),
                "exe": str(self.exe_path) if self.exe_path else None,
                "instruction": self.instruction}


class LauncherError(Exception):
    """Запуск невозможен (нет exe/карты)."""


def plan_launch(map_path: Path, exe_path: Path | None,
                use_startfile: bool = False) -> LaunchPlan:
    """План запуска по лестнице: (a) startfile, (b) exe+инструкция."""
    map_path = Path(map_path)
    if not map_path.exists():
        raise LauncherError(f"карта не найдена: {map_path}")
    if not map_path.name.startswith("S2TW_"):
        raise LauncherError(f"имя карты {map_path.name} без префикса S2TW_ "
                            f"(03 §3.13) — генератор так не пишет")
    if use_startfile and sys.platform == "win32" and os.path.exists(map_path):
        return LaunchPlan(mode="startfile", map_path=map_path, exe_path=None,
                          instruction=f"os.startfile({map_path}) — ассоциация "
                                      f".s2m (Steam-установка, V2)")
    if exe_path is None:
        return LaunchPlan(mode="instruction", map_path=map_path, exe_path=None,
                          instruction=(
                              f"Запустите Stronghold 2, в меню карт выберите "
                              f"«{map_path.name}» (сортируется в начало списка). "
                              f"Каталог Maps: {map_path.parent}"))
    exe_path = Path(exe_path)
    if not exe_path.exists():
        raise LauncherError(f"exe игры не найден: {exe_path} (проверьте "
                            f"config/project.ini → game_dir)")
    return LaunchPlan(mode="exe", map_path=map_path, exe_path=exe_path,
                      instruction=(f"Игра: {exe_path.name}; карта «{map_path.name}» "
                                   f"в списке карт (имя сортируется в начало)"),
                      command=[str(exe_path)])


def execute_plan(plan: LaunchPlan, dry_run: bool = True,
                 cwd: Path | None = None) -> dict:
    """Исполнение плана. dry_run=True (умолчание, 00 §0.7) — только печать
    плана; реальный запуск возвращает процесс (watchdog.py берёт его)."""
    if dry_run:
        return {"launched": False, "plan": plan.as_dict()}
    if plan.mode == "startfile":
        if sys.platform != "win32":  # pragma: no cover - Windows-only
            raise LauncherError("os.startfile доступен только на Windows")
        os.startfile(str(plan.map_path))  # type: ignore[attr-defined]
        return {"launched": True, "plan": plan.as_dict()}
    if plan.mode == "exe" and plan.command:
        proc = subprocess.Popen(plan.command, cwd=str(cwd or plan.exe_path.parent))
        return {"launched": True, "pid": proc.pid, "plan": plan.as_dict()}
    raise LauncherError(f"план {plan.mode!r} не исполняем — дайте человеку "
                        f"инструкцию: {plan.instruction}")


def launch(map_path: Path, exe_path: Path | None, dry_run: bool = True,
           use_startfile: bool = False) -> dict:
    """CLI-точка входа: план + исполнение."""
    return execute_plan(plan_launch(map_path, exe_path, use_startfile),
                        dry_run=dry_run)
