"""campaigns_data.py — загрузка конфигураций кампаний и сводка (S8.1–S8.3).

Реюз контракта оболочки: shell.state.validate_config (схема 03 §3.1, связность
BFS, симметрия соседств, persona ИИ, victory.short) + normalize_config
(дефолты блоков). Здесь добавлены проверки полной кампании: нет изолированных
вершин графа, стартовые регионы лордов не пересекаются, victory.full.count
не превосходит числа регионов.
"""
from __future__ import annotations

import json
from pathlib import Path

from .shell.state import ConfigError, normalize_config, validate_config


def load_campaign_config(path: Path | str) -> dict:
    """Прочитать campaign_config.json, провалидировать (validate_config +
    дополнительные проверки) и вернуть нормализованную копию (03 §3.1).
    Бросает ValueError, если файла нет, JSON битый или контракт нарушен."""
    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise ValueError(f"{path}: не читается как JSON — {e}") from e
    try:
        validate_config(raw)
        _extra_checks(raw)
    except ConfigError as e:
        raise ValueError(str(e)) from e
    return normalize_config(raw)


def _extra_checks(config: dict) -> None:
    """Дополнительные проверки связности и контракта полной кампании."""
    for region in config["regions"]:
        if not (region.get("neighbors") or []):
            raise ConfigError(f"region {region['id']}: изолированная вершина "
                              f"(нет соседей)")
    starts = [lord["start_region"] for lord in config["lords"]]
    if len(set(starts)) != len(starts):
        raise ConfigError(f"lords: стартовые регионы пересекаются: {starts}")
    full = (config.get("victory") or {}).get("full") or {}
    count = full.get("count")
    if count is not None and int(count) > len(config["regions"]):
        raise ConfigError(f"victory.full.count {count} больше числа регионов "
                          f"{len(config['regions'])}")


def describe_campaign(config: dict) -> dict:
    """Сводка кампании для README/тестов: регионы, лорды, победы."""
    regions = config["regions"]
    return {
        "campaign_id": config.get("campaign_id"),
        "title": config.get("title"),
        "regions": len(regions),
        "lords": len(config["lords"]),
        "castles": sum(1 for r in regions if r.get("type") == "castle"),
        "villages": sum(1 for r in regions if r.get("type") == "village"),
        "victory_short": (config.get("victory") or {}).get("short"),
        "victory_full": (config.get("victory") or {}).get("full"),
    }
