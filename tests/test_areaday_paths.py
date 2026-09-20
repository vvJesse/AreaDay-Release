from __future__ import annotations

import contextlib
import io
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
        self.legacy = self.root / "legacy"
        self.legacy.mkdir()
        areaday_paths.reset_announcements()
        self.addCleanup(areaday_paths.reset_announcements)
        for target, value in (
            ("SKILL_ROOT", self.skill),
            ("legacy_data_roots", lambda platform_name=None: ()),
            ("legacy_credentials_candidates", lambda: ()),
            ("legacy_model_roots", lambda: ()),
        ):
            patcher = patch.object(areaday_paths, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        environment = patch.dict(os.environ, {}, clear=False)
        environment.start()
        self.addCleanup(environment.stop)
        for variable in (DATA_DIR_VARIABLE, CONFIG_DIR_VARIABLE, MODEL_DIR_VARIABLE):
            os.environ.pop(variable, None)

    def use_legacy(self, kind: str, relative: str) -> Path:
        """Point one legacy location at a prepared directory."""

        target = self.legacy / relative
        if "data_roots" in kind:
            patcher = patch.object(
                areaday_paths, "legacy_data_roots", lambda platform_name=None: (target,)
            )
        elif "credentials" in kind:
            patcher = patch.object(
                areaday_paths,
                "legacy_credentials_candidates",
                lambda: (target / CREDENTIALS_FILENAME,),
            )
        else:
            patcher = patch.object(
                areaday_paths, "legacy_model_roots", lambda: (target,)
            )
        patcher.start()
        self.addCleanup(patcher.stop)
        return target

    def capture_notices(self) -> tuple[str, object]:
        stream = io.StringIO()
        return stream, contextlib.redirect_stderr(stream)

    # -- defaults live inside the Skill ------------------------------------

    def test_the_registry_lives_in_the_skill_data_directory(self) -> None:
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

    # -- earlier locations are reused in place -----------------------------

    def test_an_older_registry_is_reused_without_being_moved(self) -> None:
        legacy = self.use_legacy("data_roots", "application-data")
        legacy.mkdir(parents=True)
        registry = legacy / REGISTRY_FILENAME
        registry.write_text('{"schema_version": 1}', encoding="utf-8")

        stream = io.StringIO()
        with contextlib.redirect_stderr(stream):
            first = areaday_paths.data_root()
            second = areaday_paths.data_root()

        self.assertEqual(first, legacy)
        self.assertEqual(second, legacy)
        self.assertTrue(registry.is_file())
        self.assertFalse((self.skill / "data").exists())
        notices = stream.getvalue()
        self.assertIn(str(legacy), notices)
        self.assertIn("Nothing was moved or deleted", notices)
        self.assertEqual(notices.count("the domain registry"), 1)

    def test_an_older_key_is_reused_without_being_moved(self) -> None:
        legacy = self.use_legacy("credentials", "areaday")
        legacy.mkdir(parents=True)
        key = legacy / CREDENTIALS_FILENAME
        key.write_text("[openalex]\napi_key = abcdefghijklmnop\n", encoding="utf-8")

        stream = io.StringIO()
        with contextlib.redirect_stderr(stream):
            resolved = areaday_paths.credentials_path()

        self.assertEqual(resolved, key)
        self.assertTrue(key.is_file())
        self.assertIn("the OpenAlex key", stream.getvalue())

    def test_an_older_model_directory_is_reused(self) -> None:
        legacy = self.use_legacy("model_roots", "models/sentence-transformers")
        legacy.mkdir(parents=True)

        stream = io.StringIO()
        with contextlib.redirect_stderr(stream):
            resolved = areaday_paths.model_root()

        self.assertEqual(resolved, legacy)
        self.assertIn("the embedding model", stream.getvalue())

    def test_the_skill_directory_wins_once_it_holds_the_data(self) -> None:
        legacy = self.use_legacy("data_roots", "application-data")
        legacy.mkdir(parents=True)
        (legacy / REGISTRY_FILENAME).write_text("{}", encoding="utf-8")
        data = self.skill / "data"
        data.mkdir(parents=True)
        (data / REGISTRY_FILENAME).write_text("{}", encoding="utf-8")

        stream = io.StringIO()
        with contextlib.redirect_stderr(stream):
            resolved = areaday_paths.data_root()

        self.assertEqual(resolved, data)
        self.assertEqual(stream.getvalue(), "")

    def test_an_environment_override_ignores_the_older_locations(self) -> None:
        legacy = self.use_legacy("data_roots", "application-data")
        legacy.mkdir(parents=True)
        (legacy / REGISTRY_FILENAME).write_text("{}", encoding="utf-8")
        relocated = self.root / "elsewhere"

        stream = io.StringIO()
        with contextlib.redirect_stderr(stream), patch.dict(
            os.environ, {DATA_DIR_VARIABLE: str(relocated)}
        ):
            self.assertEqual(areaday_paths.data_root(), relocated)

        self.assertEqual(stream.getvalue(), "")


class HardCodedLocationTests(unittest.TestCase):
    """Only ``areaday_paths`` may decide where AreaDay keeps its files."""

    def test_no_module_defines_its_own_area_day_home(self) -> None:
        offenders = []
        for path in sorted((ROOT / "scripts").glob("*.py")):
            if path.name == "areaday_paths.py":
                continue
            if 'Path.home() / ".areaday"' in path.read_text(encoding="utf-8"):
                offenders.append(path.name)
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

    def test_the_skill_data_directory_is_never_committed(self) -> None:
        ignore_rules = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertIn("/data/", ignore_rules)


if __name__ == "__main__":
    unittest.main()
