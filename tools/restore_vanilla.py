#!/usr/bin/env python3
"""Обёртка запуска restore_vanilla (docs/install.md): python tools/restore_vanilla.py [--no-dry-run]."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sh2tw.restore_vanilla import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
