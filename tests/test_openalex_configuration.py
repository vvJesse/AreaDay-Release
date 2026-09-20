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


class _Editor:
    """Stand-in for the launcher subprocess."""

    def __init__(self, returncode: int | None = None, stays_open: bool = False) -> None:
        self.returncode = returncode
        self.stays_open = stays_open

    def wait(self, timeout: float | None = None) -> int | None:
        if self.stays_open:
            raise subprocess.TimeoutExpired(cmd="open", timeout=timeout or 0)
        return self.returncode


class EditorLaunchTests(unittest.TestCase):
    """A launcher that did not open anything must never be reported as success."""

    def patch_launchers(self, outcomes: list[object]) -> list[list[str]]:
        launched: list[list[str]] = []

        def fake_popen(command, **_kwargs):
            outcome = outcomes[len(launched)]
            launched.append(command)
            if isinstance(outcome, OSError):
                raise outcome
            return outcome

        patcher = patch("configure_openalex.subprocess.Popen", side_effect=fake_popen)
        patcher.start()
        self.addCleanup(patcher.stop)
        platform = patch.object(configurator.sys, "platform", "darwin")
        platform.start()
        self.addCleanup(platform.stop)
        return launched

    def test_the_first_launcher_that_works_is_reported(self) -> None:
        launched = self.patch_launchers([_Editor(returncode=0)])
        self.assertEqual(
            configurator.open_in_editor(Path("/tmp/credentials.ini")), "open -e"
        )
        self.assertEqual(launched, [["open", "-e", "/tmp/credentials.ini"]])

    def test_a_launcher_that_fails_falls_through_to_the_next_one(self) -> None:
        launched = self.patch_launchers([_Editor(returncode=1), _Editor(returncode=0)])
        self.assertEqual(
            configurator.open_in_editor(Path("/tmp/credentials.ini")), "open -t"
        )
        self.assertEqual(
            launched,
            [["open", "-e", "/tmp/credentials.ini"], ["open", "-t", "/tmp/credentials.ini"]],
        )

    def test_a_launcher_that_cannot_start_is_skipped(self) -> None:
        launched = self.patch_launchers([OSError("no such file"), _Editor(returncode=0)])
        self.assertEqual(configurator.open_in_editor(Path("/tmp/k.ini")), "open -t")
        self.assertEqual(len(launched), 2)

    def test_an_editor_that_stays_open_counts_as_opened(self) -> None:
        self.patch_launchers([_Editor(stays_open=True)])
        self.assertEqual(configurator.open_in_editor(Path("/tmp/k.ini")), "open -e")

    def test_nothing_opened_is_reported_as_nothing(self) -> None:
        launched = self.patch_launchers(
            [_Editor(returncode=1), _Editor(returncode=1), _Editor(returncode=1)]
        )
        self.assertEqual(configurator.open_in_editor(Path("/tmp/k.ini")), "")
        self.assertEqual(len(launched), 3)

    def test_the_preferred_editor_is_used_first_off_macos(self) -> None:
        launched: list[list[str]] = []

        def fake_popen(command, **_kwargs):
            launched.append(command)
            return _Editor(returncode=0)

        with patch("configure_openalex.subprocess.Popen", side_effect=fake_popen), patch.object(
            configurator.sys, "platform", "linux"
        ), patch.dict(os.environ, {"EDITOR": "myeditor --wait"}, clear=False):
            self.assertEqual(
                configurator.open_in_editor(Path("/tmp/k.ini")), "myeditor --wait"
            )
        self.assertEqual(launched, [["myeditor", "--wait", "/tmp/k.ini"]])

    def test_a_missing_editor_falls_back_to_the_desktop_opener(self) -> None:
        launched: list[list[str]] = []

        def fake_popen(command, **_kwargs):
            launched.append(command)
            return _Editor(returncode=0)

        environment = dict(os.environ)
        environment.pop("EDITOR", None)
        environment.pop("VISUAL", None)
        with patch("configure_openalex.subprocess.Popen", side_effect=fake_popen), patch.object(
            configurator.sys, "platform", "linux"
        ), patch.dict(os.environ, environment, clear=True):
            self.assertEqual(configurator.open_in_editor(Path("/tmp/k.ini")), "xdg-open")
        self.assertEqual(launched, [["xdg-open", "/tmp/k.ini"]])


if __name__ == "__main__":
    unittest.main()
