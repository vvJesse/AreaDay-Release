from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PlatformInstallerContractTests(unittest.TestCase):
    def test_macos_installer_runs_data_migration_after_runtime_creation(self) -> None:
        script = (ROOT / "scripts" / "install.sh").read_text(encoding="utf-8")
        self.assertIn('MIGRATION_SCRIPT="$SCRIPT_DIR/migrate_areaday_data.py"', script)
        self.assertIn('"$VENV_DIR/bin/python" "$MIGRATION_SCRIPT"', script)
        self.assertIn("UV_VERSION=\"0.12.6\"", script)
        self.assertIn("--runtime-only", script)
        self.assertIn('AreaDay-runtime-$PLATFORM_ID-*.zip', script)
        self.assertIn("ditto -x -k", script)
        self.assertIn("failed verification after installation", script)
        self.assertIn("base-python/bin/python3.12", script)
        self.assertIn("com.apple.quarantine", script)
        self.assertIn("prepare_portable_runtime.py", script)
        self.assertIn('OPENALEX_CONFIG="$DATA_DIR/credentials.ini"', script)
        self.assertIn("personal OpenAlex API key", script)

    def test_macos_openalex_setup_writes_inside_the_skill(self) -> None:
        wrapper = (ROOT / "scripts" / "configure_openalex.sh").read_text(encoding="utf-8")
        configurator = (ROOT / "scripts" / "configure_openalex.py").read_text(encoding="utf-8")
        self.assertIn('exec "$PYTHON" "$SCRIPT_DIR/configure_openalex.py" "$@"', wrapper)
        self.assertNotIn("anonymous", wrapper.lower())
        self.assertIn("from areaday_paths import config_dir", configurator)
        self.assertIn("no longer supports anonymous OpenAlex access", configurator)
        self.assertNotIn("OpenAlex anonymous access selected", configurator)

    def test_macos_installation_does_not_wait_for_the_key_by_default(self) -> None:
        script = (ROOT / "scripts" / "install.sh").read_text(encoding="utf-8")
        self.assertIn('if [ "$MODE" = "--install" ] && [ "$WITH_OPENALEX" -eq 1 ]; then', script)
        self.assertIn("report_openalex_next_step", script)
        self.assertIn("--with-openalex", script)
        self.assertIn("scripts/configure_openalex.py", script)

    def test_installers_keep_areaday_data_inside_the_skill(self) -> None:
        shell = (ROOT / "scripts" / "install.sh").read_text(encoding="utf-8")
        windows = (ROOT / "scripts" / "install.ps1").read_text(encoding="utf-8")
        windows_config = (ROOT / "scripts" / "configure_openalex.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn('DATA_DIR="$SKILL_DIR/data"', shell)
        self.assertIn('MODEL_DIR="$DATA_DIR/models/sentence-transformers"', shell)
        self.assertIn('$DataDir = Join-Path $SkillDir "data"', windows)
        self.assertIn('Join-Path $DataDir "models\\sentence-transformers"', windows)
        self.assertIn("$OpenAlexConfigDir = $DataDir", windows)
        self.assertIn('$ConfigDir = Join-Path $SkillDir "data"', windows_config)
        for text in (shell, windows, windows_config):
            for marker in (
                "AREADAY_DATA_DIR",
                "AREADAY_CONFIG_DIR",
                "AREADAY_MODEL_DIR",
                "OPENALEX_API_KEY",
            ):
                self.assertNotIn(marker, text)
        self.assertNotIn("$HOME/.areaday", shell)
        self.assertNotIn('Join-Path $HOME ".areaday"', windows + windows_config)

    def test_windows_x64_installer_uses_windows_runtime_and_data_migration(self) -> None:
        script = (ROOT / "scripts" / "install.ps1").read_text(encoding="utf-8")
        self.assertNotIn("then run this setup again", script)
        self.assertIn("One setup step remains", script)
        self.assertIn('Join-Path $LocalUvDir "uv.exe"', script)
        self.assertIn('Join-Path $VenvDir "Scripts\\python.exe"', script)
        self.assertIn("$MigrationScript", script)
        self.assertIn("AreaDay data migration did not complete", script)
        self.assertIn('AreaDay-runtime-windows-x64-*.zip', script)
        self.assertIn("Assert-BundledRuntime", script)
        self.assertIn("Get-FileHash", script)
        self.assertIn("tar.exe", script)
        self.assertIn("Select-Object -First 1", script)
        self.assertIn("Assert-WindowsRuntimePath", script)
        self.assertIn("[IO.Path]::GetTempPath()", script)
        self.assertIn('"runtime-only"', script)
        self.assertIn("$BackupVenv", script)
        self.assertIn("$VenvReplacementStarted", script)
        self.assertIn("shutil.rmtree", script)
        self.assertIn("base-python\\python.exe", script)
        self.assertIn("prepare_portable_runtime.py", script)
        self.assertIn("configure_openalex.ps1", script)
        self.assertIn("needs a personal OpenAlex API key before it can search", script)
        self.assertNotIn("-Anonymous", script)
        self.assertNotIn("WaitForExit", script)
        self.assertNotIn("$OpenAlexSetupProcess", script)
        self.assertNotIn("/usr/", script)

    def test_windows_openalex_setup_opens_the_configuration_file(self) -> None:
        script = (ROOT / "scripts" / "configure_openalex.ps1").read_text(encoding="utf-8")
        self.assertIn("Start-Process $ConfigPath", script)
        self.assertIn("Ensure-ConfigurationTemplate", script)
        self.assertIn('$Content = "[openalex]`napi_key = $ApiKey`n"', script)
        self.assertIn("[switch]$Reconfigure", script)
        self.assertIn("no longer supports anonymous OpenAlex access", script)
        self.assertNotIn("[switch]$Anonymous", script)
        self.assertNotIn('Save-Configuration "anonymous"', script)
        self.assertNotIn("Read-Host", script)


if __name__ == "__main__":
    unittest.main()
