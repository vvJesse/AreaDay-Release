#!/usr/bin/env python3
"""Create AreaDay's own data directory and report where it is."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from areaday_paths import data_root


def areaday_data_root() -> Path:
    """Return the AreaDay-owned data directory (see ``areaday_paths``)."""

    return data_root()


def migrate_areaday_data(destination: Path) -> dict[str, str]:
    destination = destination.expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    return {"status": "areaday_data_ready", "data_directory": str(destination)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path)
    args = parser.parse_args()
    destination = args.destination or areaday_data_root()
    print(json.dumps(migrate_areaday_data(destination), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
