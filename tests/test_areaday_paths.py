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
from areaday_paths import (  # noqa: E402
    CONFIG_DIR_VARIABLE,
    CREDENTIALS_FILENAME,
    DATA_DIR_VARIABLE,
    MODEL_DIR_VARIABLE,
    REGISTRY_FILENAME,
)


class AreaDayPathTests(unittest.TestCase):
    """Every file AreaDay owns lives inside the Skill unless the host says otherwise."""

    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name).resolve()
        self.skill = self.root / "AreaDay"
        self.skill.mkdir()
        patcher = patch.object(areaday_paths, "SKILL_ROOT", self.skill)
        patcher.start()
        self.addCleanup(patcher.stop)
        environment = patch.dict(os.environ, {}, clear=False)
        environment.start()
        self.addCleanup(environment.stop)
        for variable in (DATA_DIR_VARIABLE, CONFIG_DIR_VARIABLE, MODEL_DIR_VARIABLE):
            os.environ.pop(variable, None)

    # -- defaults live inside the Skill ------------------------------------

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

    # -- environment overrides --------------------------------------------

    def test_the_data_directory_can_be_relocated(self) -> None:
        relocated = self.root / "elsewhere"
        with patch.dict(os.environ, {DATA_DIR_VARIABLE: str(relocated)}):
            self.assertEqual(areaday_paths.data_root(), relocated)
            self.assertEqual(
                areaday_paths.registry_path(), relocated / REGISTRY_FILENAME
            )

    def test_the_configuration_directory_can_be_relocated(self) -> None:
        relocated = self.root / "config"
        with patch.dict(os.environ, {CONFIG_DIR_VARIABLE: str(relocated)}):
            self.assertEqual(
                areaday_paths.credentials_path(), relocated / CREDENTIALS_FILENAME
            )

    def test_the_model_directory_can_be_relocated(self) -> None:
        relocated = self.root / "models"
        with patch.dict(os.environ, {MODEL_DIR_VARIABLE: str(relocated)}):
            self.assertEqual(areaday_paths.model_root(), relocated)


class HardCodedLocationTests(unittest.TestCase):
    """Only ``areaday_paths`` may decide where AreaDay keeps its files."""

    def test_no_module_keeps_a_second_area_day_home(self) -> None:
        offenders = []
        for path in sorted((ROOT / "scripts").glob("*.py")):
            if path.name == "areaday_paths.py":
                continue
            text = path.read_text(encoding="utf-8")
            for marker in ('Path.home() / ".areaday"', "~/.researchramp", "PATH.home() / \".areaday\""):
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

    def test_the_skill_data_directory_is_never_committed(self) -> None:
        ignore_rules = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertIn("/data/", ignore_rules)


if __name__ == "__main__":
    unittest.main()
