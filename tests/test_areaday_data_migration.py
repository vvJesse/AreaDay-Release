from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from migrate_areaday_data import migrate_areaday_data  # noqa: E402
from domain_registry import default_registry_path  # noqa: E402


class AreaDayDataDirectoryTests(unittest.TestCase):
    def test_registry_ignores_a_relocation_variable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            selected = Path(temporary) / "AreaDayData"
            with patch.dict(os.environ, {"AREADAY_DATA_DIR": str(selected)}):
                self.assertEqual(
                    default_registry_path(),
                    ROOT / "data" / "real-domains.json",
                )

    def test_registry_defaults_inside_the_skill_without_an_override(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("AREADAY_DATA_DIR", None)
            self.assertEqual(
                default_registry_path(),
                ROOT / "data" / "real-domains.json",
            )

    def test_the_data_directory_is_created_when_it_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "data"

            result = migrate_areaday_data(destination)

            self.assertEqual(result["status"], "areaday_data_ready")
            self.assertEqual(result["data_directory"], str(destination.resolve()))
            self.assertTrue(destination.is_dir())
            self.assertEqual(list(destination.iterdir()), [])

    def test_existing_data_is_left_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "data"
            destination.mkdir()
            registry = destination / "real-domains.json"
            registry.write_text(json.dumps({"schema_version": 1}), encoding="utf-8")

            result = migrate_areaday_data(destination)

            self.assertEqual(result["status"], "areaday_data_ready")
            self.assertEqual(
                json.loads(registry.read_text(encoding="utf-8")),
                {"schema_version": 1},
            )


if __name__ == "__main__":
    unittest.main()
