"""S1.2: сверка exe игры с эталоном сборки (ref/build_fingerprint.json).

Пишет отчёт по каркасу 03 §3.11 в experiments/reports/V5.json (metrics —
цифры сверки; решение по track2 принимает человек после вечера V5).
"""
from __future__ import annotations

import hashlib
import json
import struct
import zlib
from datetime import datetime, timezone
from pathlib import Path

from .paths import REPO_ROOT, Paths

FINGERPRINT = REPO_ROOT / "ref" / "build_fingerprint.json"


def measure(exe: Path) -> dict:
    data = exe.read_bytes()
    pe_off = struct.unpack_from("<I", data, 0x3C)[0]
    ts = struct.unpack_from("<I", data, pe_off + 8)[0]  # COFF TimeDateStamp
    return {
        "size_bytes": len(data),
        "pe_timedatestamp": hex(ts),
        "md5": hashlib.md5(data).hexdigest(),
        "crc32": hex(zlib.crc32(data) & 0xFFFFFFFF),
    }


def check_build(paths: Paths, report_path: Path | None = None) -> dict:
    ref = json.loads(FINGERPRINT.read_text(encoding="utf-8"))
    exp = {k.lower(): str(v).lower() for k, v in ref["expected"].items()}
    got = measure(paths.exe_path)
    checks = {}
    for k, v in got.items():
        checks[k] = {"expected": exp.get(k), "actual": str(v).lower(),
                     "match": exp.get(k) == str(v).lower()}
    all_match = all(c["match"] for c in checks.values())
    verdict = "совпадает с v1.5.0 (track2 совместим ожидаемо)" if all_match \
        else "РАСХОЖДЕНИЕ — track2 под вопросом, вечер V5 обязателен до патчей"
    report = {
        "v_id": "V5",
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "performer": "agent (агрегатная сверка) + human (вечер V5: установка патча, Ctrl+Shift+O)",
        "hypothesis": "exe == Steam v1.5.0 → патч/оверхол/лорд-редатор совместимы",
        "result": verdict,
        "metrics": {"exe": str(paths.exe_path), "checks": checks},
        "decision": "UNKNOWN (ждёт вечер V5 — человек)",
        "attachments": [],
    }
    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=1),
                               encoding="utf-8")
    return report
