from __future__ import annotations

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

import areaday_paths  # noqa: E402
from areaday_paths import CREDENTIALS_FILENAME, REGISTRY_FILENAME  # noqa: E402


# Names AreaDay used to accept from the environment or the command line. The
# Skill has exactly one place for every file it owns, so nothing here may be
# read anywhere in the code any more.
RETIRED_VARIABLES = (
    "AREADAY_DATA_DIR",
    "AREADAY_CONFIG_DIR",
    "AREADAY_MODEL_DIR",
    "AREADAY_WORKBENCH_PORT",
    "OPENALEX_API_KEY",
)


class AreaDayPathTests(unittest.TestCase):
    """Every file AreaDay owns lives inside the Skill, and nowhere else."""

    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name).resolve()
        self.skill = self.root / "AreaDay"
        self.skill.mkdir()
        patcher = patch.object(areaday_paths, "SKILL_ROOT", self.skill)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_registry_lives_in_the_skill_data_directory(self) -> None:
        self.assertEqual(areaday_paths.data_root(), self.skill / "data")
        self.assertEqual(
            areaday_paths.registry_path(),
            self.skill / "data" / REGISTRY_FILENAME,
        )
        self.assertEqual(
            areaday_paths.global_learning_path(),
            self.skill / "data" / "global-learning.sqlite3",
        )

    def test_the_key_lives_in_the_skill_data_directory(self) -> None:
        self.assertEqual(
            areaday_paths.credentials_path(),
            self.skill / "data" / CREDENTIALS_FILENAME,
        )
        self.assertEqual(areaday_paths.config_dir(), self.skill / "data")

    def test_the_embedding_model_lives_in_the_skill_data_directory(self) -> None:
        self.assertEqual(
            areaday_paths.model_root(),
            self.skill / "data" / "models" / "sentence-transformers",
        )

    def test_no_environment_variable_moves_a_file(self) -> None:
        elsewhere = self.root / "elsewhere"
        configured = {name: str(elsewhere) for name in RETIRED_VARIABLES}
        with patch.dict(os.environ, configured):
            self.assertEqual(areaday_paths.data_root(), self.skill / "data")
            self.assertEqual(
                areaday_paths.registry_path(),
                self.skill / "data" / REGISTRY_FILENAME,
            )
            self.assertEqual(
                areaday_paths.global_learning_path(),
                self.skill / "data" / "global-learning.sqlite3",
            )
            self.assertEqual(
                areaday_paths.credentials_path(),
                self.skill / "data" / CREDENTIALS_FILENAME,
            )
            self.assertEqual(areaday_paths.config_dir(), self.skill / "data")
            self.assertEqual(
                areaday_paths.model_root(),
                self.skill / "data" / "models" / "sentence-transformers",
            )


class HardCodedLocationTests(unittest.TestCase):
    """Only ``areaday_paths`` may decide where AreaDay keeps its files."""

    def test_no_module_keeps_a_second_area_day_home(self) -> None:
        offenders = []
        for path in sorted((ROOT / "scripts").glob("*.py")):
            if path.name == "areaday_paths.py":
                continue
            text = path.read_text(encoding="utf-8")
            for marker in (
                'Path.home() / ".areaday"',
                "~/.researchramp",
                'PATH.home() / ".areaday"',
                "researchramp.sqlite3",
            ):
                if marker in text:
                    offenders.append(f"{path.name}: {marker}")
        self.assertEqual(offenders, [])

    def test_no_module_reads_a_retired_variable(self) -> None:
        offenders = []
        for path in sorted((ROOT / "scripts").glob("*.py")):
            if path.name == "areaday_paths.py":
                continue
            text = path.read_text(encoding="utf-8")
            for marker in RETIRED_VARIABLES:
                if marker in text:
                    offenders.append(f"{path.name}: {marker}")
        self.assertEqual(offenders, [])

    def test_no_installer_hardcodes_the_home_directory(self) -> None:
        for name in (
            "install.sh",
            "install.ps1",
            "configure_openalex.sh",
            "configure_openalex.ps1",
        ):
            text = (ROOT / "scripts" / name).read_text(encoding="utf-8")
            self.assertNotIn("$HOME/.areaday", text, name)
            self.assertNotIn('Join-Path $HOME ".areaday"', text, name)
            self.assertNotIn("researchramp", text.lower(), name)

    def test_no_installer_reads_a_retired_variable(self) -> None:
        for name in (
            "install.sh",
            "install.ps1",
            "configure_openalex.sh",
            "configure_openalex.ps1",
        ):
            text = (ROOT / "scripts" / name).read_text(encoding="utf-8")
            for marker in RETIRED_VARIABLES:
                self.assertNotIn(marker, text, f"{name}: {marker}")

    def test_the_skill_data_directory_is_never_committed(self) -> None:
        ignore_rules = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertIn("/data/", ignore_rules)


if __name__ == "__main__":
    unittest.main()
