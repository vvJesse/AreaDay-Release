from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = SKILL_DIR / "scripts"
CONFIGURATOR = SCRIPTS_DIR / "configure_openalex.py"
sys.path.insert(0, str(SCRIPTS_DIR))

import configure_openalex as configurator  # noqa: E402
from areaday_core import (  # noqa: E402
    credentials_path,
    load_openalex_api_key,
)


class OpenAlexConfigurationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)

    def write_configuration(self, value: str, directory: Path | None = None) -> Path:
        target = (directory or self.root) / "credentials.ini"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"[openalex]\napi_key = {value}\n", encoding="utf-8")
        return target

    def load(self, directory: Path | None = None) -> str:
        target = (directory or self.root) / "credentials.ini"
        with patch("areaday_core.credentials_path", lambda: target):
            return load_openalex_api_key()

    def test_a_personal_key_is_returned(self) -> None:
        self.write_configuration("abcdefghijklmnop")
        self.assertEqual(self.load(), "abcdefghijklmnop")

    def test_a_missing_configuration_asks_for_a_key(self) -> None:
        with self.assertRaises(RuntimeError) as context:
            self.load()
        self.assertIn("needs a personal OpenAlex API key", str(context.exception))
        self.assertIn("credentials.ini", str(context.exception))

    def test_an_empty_value_asks_for_a_key(self) -> None:
        self.write_configuration("")
        with self.assertRaises(RuntimeError) as context:
            self.load()
        self.assertIn("needs a personal OpenAlex API key", str(context.exception))

    def test_the_anonymous_value_is_rejected(self) -> None:
        self.write_configuration("anonymous")
        with self.assertRaises(RuntimeError) as context:
            self.load()
        self.assertIn("no longer supports anonymous OpenAlex access", str(context.exception))

    def test_a_malformed_key_is_rejected(self) -> None:
        self.write_configuration("short")
        with self.assertRaises(ValueError):
            self.load()

    def test_the_key_file_cannot_be_moved_by_the_environment(self) -> None:
        with patch.dict(os.environ, {"AREADAY_CONFIG_DIR": "/tmp/from-env"}, clear=False):
            self.assertEqual(credentials_path(), SKILL_DIR / "data" / "credentials.ini")

    def test_a_key_in_the_environment_is_ignored(self) -> None:
        self.write_configuration("abcdefghijklmnop")
        with patch.dict(os.environ, {"OPENALEX_API_KEY": "environmentkey12345"}, clear=False):
            self.assertEqual(self.load(), "abcdefghijklmnop")

    def test_the_environment_cannot_replace_a_missing_key(self) -> None:
        with patch.dict(os.environ, {"OPENALEX_API_KEY": "environmentkey12345"}, clear=False):
            with self.assertRaises(RuntimeError) as context:
                self.load()
        self.assertIn("needs a personal OpenAlex API key", str(context.exception))


class ConfigureOpenAlexScriptTests(unittest.TestCase):
    """The script a user (or an agent) runs to connect an OpenAlex key."""

    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)
        # The script runs in a copy of the Skill so the key file it writes lands
        # inside that copy instead of the checked-out Skill this test lives in.
        self.skill = self.root / "AreaDay"
        (self.skill / "scripts").mkdir(parents=True)
        (self.skill / "assets").mkdir()
        self.script = self.skill / "scripts" / "configure_openalex.py"
        shutil.copy2(CONFIGURATOR, self.script)
        shutil.copy2(
            SCRIPTS_DIR / "areaday_paths.py", self.skill / "scripts" / "areaday_paths.py"
        )
        shutil.copy2(
            SKILL_DIR / "assets" / "openalex-help.html",
            self.skill / "assets" / "openalex-help.html",
        )
        self.path = (self.skill / "data" / "credentials.ini").resolve()

    def run_script(self, *arguments: str, payload: str = "") -> subprocess.CompletedProcess:
        environment = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": str(self.root),
        }
        return subprocess.run(
            [sys.executable, str(self.script), *arguments],
            input=payload,
            capture_output=True,
            text=True,
            timeout=60,
            env=environment,
        )

    def test_the_printed_path_is_inside_the_skill_data_directory(self) -> None:
        result = self.run_script("--print-path")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), str(self.path))

    def test_a_missing_key_is_reported_without_changing_anything(self) -> None:
        result = self.run_script("--check", "--no-open")
        self.assertEqual(result.returncode, 4, result.stderr)
        self.assertIn("No OpenAlex key is configured", result.stdout)
        self.assertFalse(self.path.exists())

    def test_a_malformed_key_is_rejected_before_any_network_call(self) -> None:
        result = self.run_script("--stdin", "--no-open", payload="not a key")
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("does not look like a complete OpenAlex key", result.stdout)
        self.assertFalse(self.path.exists())

    def test_an_anonymous_value_is_rejected_on_standard_input(self) -> None:
        result = self.run_script("--stdin", "--no-open", payload="anonymous")
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn("no longer supports anonymous OpenAlex access", result.stdout)
        self.assertFalse(self.path.exists())

    def test_a_key_file_is_read_instead_of_the_terminal(self) -> None:
        source = self.root / "key.txt"
        source.write_text("not a key", encoding="utf-8")
        result = self.run_script("--key-file", str(source), "--no-open")
        self.assertEqual(result.returncode, 2, result.stdout)

    def test_json_output_is_machine_readable(self) -> None:
        result = self.run_script("--check", "--json", "--no-open")
        self.assertEqual(result.returncode, 4, result.stdout)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "missing")
        self.assertEqual(payload["credentials_path"], str(self.path))


class ConfigureOpenAlexHelpersTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)

    def test_the_retired_anonymous_note_is_dropped_and_other_comments_kept(self) -> None:
        text = "# keep me\n# 如果明确选择匿名额度，请填写 anonymous\napi_key = old\n"
        cleaned = configurator.without_stale_guidance(text)
        self.assertIn("# keep me", cleaned)
        self.assertIn("api_key = old", cleaned)
        self.assertNotIn("anonymous", cleaned)

    def test_a_pasted_key_is_normalised(self) -> None:
        self.assertEqual(configurator.normalise_key("  'abcdefghijklmnop'  \n"), "abcdefghijklmnop")
        self.assertEqual(configurator.normalise_key("Bearer abcdefghijklmnop"), "abcdefghijklmnop")
        self.assertEqual(
            configurator.normalise_key("OPENALEX_API_KEY=abcdefghijklmnop"), "abcdefghijklmnop"
        )

    def test_saving_a_key_keeps_the_rest_of_the_file_private(self) -> None:
        path = self.root / "credentials.ini"
        path.write_text("[openalex]\napi_key = old\n\n[other]\nkeep = yes\n", encoding="utf-8")
        configurator.save_key(path, "abcdefghijklmnop")
        text = path.read_text(encoding="utf-8")
        self.assertIn("api_key = abcdefghijklmnop", text)
        self.assertIn("keep = yes", text)
        self.assertNotIn("old", text)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_no_environment_variable_moves_the_configuration_file(self) -> None:
        with patch.dict(os.environ, {"AREADAY_CONFIG_DIR": "/tmp/from-env"}, clear=False):
            self.assertEqual(configurator.config_dir(), SKILL_DIR / "data")

    def test_the_key_problem_explains_what_to_fix(self) -> None:
        self.assertIn("No key was entered", configurator.key_problem(""))
        self.assertIn("anonymous", configurator.key_problem("anonymous").lower())
        self.assertIn("complete OpenAlex key", configurator.key_problem("short"))
        self.assertEqual(configurator.key_problem("abcdefghijklmnop"), "")


if __name__ == "__main__":
    unittest.main()
