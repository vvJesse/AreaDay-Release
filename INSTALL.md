# Install AreaDay

This file is the installation entry point for Codex and WorkBuddy agents.

## Instruction to the agent

When the user provides an AreaDay GitHub repository link, GitHub Release link,
delivery ZIP, or GitHub Actions artifact ZIP and asks you to install it, perform
the installation for them. The user does not need to identify the correct file
or explain the procedure. Do not ask the user to extract files, move folders,
run terminal commands, install Python, or install dependencies.

The user needs only the platform delivery ZIP named
`AreaDay-<platform>-v<version>.zip`. GitHub's automatically generated
`Source code (zip)` and `Source code (tar.gz)` files are not part of AreaDay and
must not be installed. A standalone file named
`AreaDay-runtime-<platform>-v<version>.zip` is an internal component and must
not be installed by itself.

### 1. Resolve the delivery ZIP

If the user supplied a repository URL, open its latest published GitHub Release.
If the user supplied a Release URL, use that Release. Detect the current
computer and download exactly one matching delivery asset:

- Windows x64: `AreaDay-windows-x64-v<version>.zip`
- Apple silicon Mac: `AreaDay-macos-arm64-v<version>.zip`

Match the exact delivery filename. Do not select a Source code archive, a
checksum text file, or a filename containing `-runtime-`.

If the supplied ZIP is a GitHub Actions artifact wrapper rather than the
delivery ZIP, extract the wrapper to a temporary directory and select its one
matching `AreaDay-<platform>-v<version>.zip`. Ignore the sibling standalone
Runtime ZIP and checksum file.

### 2. Validate the package

Extract the attached ZIP to a temporary directory and require all of the
following before changing an existing installation:

- one top-level `areaday` directory;
- `areaday/SKILL.md`;
- `areaday/release.json` whose product is `areaday`;
- exactly one archive under `areaday/runtime-packs/`;
- a package platform matching the current computer:
  - `windows-x64` for 64-bit Windows on Intel or AMD;
  - `macos-arm64` for an Apple silicon Mac.

Intel Macs are not supported. Never try to install the Apple silicon package
through Rosetta or substitute a standalone Runtime archive for the delivery
ZIP.

### 3. Select the host Skill directory

Install the complete extracted `areaday` directory as a user-level Skill:

- Codex: `$CODEX_HOME/skills/areaday` when `CODEX_HOME` is set; otherwise
  `~/.codex/skills/areaday`.
- WorkBuddy: `~/.workbuddy/skills/areaday` on macOS, or
  `%USERPROFILE%\.workbuddy\skills\areaday` on Windows.

Use the directory for the application in which this task is running. Do not
install separate copies for both applications unless the user explicitly asks.

For an upgrade, first move the existing `areaday` directory to a temporary
sibling backup. Copy the new complete directory into place without flattening
or adding a second `areaday` nesting level. Keep the backup until every check
below succeeds. If any step fails, remove the incomplete new directory and
restore the backup.

### 4. Run the included setup

Run the setup from the installed Skill directory, not from the temporary
extraction directory:

- macOS: `sh scripts/install.sh`
- Windows: `powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\install.ps1`

Allow the setup to finish. Setup writes inside the Skill directory - its `data`
directory holds the registry, the global learning state, the OpenAlex
configuration and the embedding model - and to the workspaces the customer
registers, and it may reach the network; request those permissions before
starting it. The delivery ZIP already contains
Python, packages, and models; do not download or independently resolve Python
dependencies.

OpenAlex works only with the customer's own API key, and setup no longer falls
back to anonymous access. Setup itself finishes without that key and prints the
one remaining step:

- macOS: `cd <installed Skill directory> && .venv/bin/python scripts/configure_openalex.py`
- Windows: `powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\configure_openalex.ps1`

That command creates `data/credentials.ini` inside the installed Skill directory
when it does not exist, opens
it in the customer's own text editor and returns immediately - it never waits for
input. The customer pastes the key after `api_key =`, saves the file and says the
agent may continue; the agent then runs `--check` and carries on once it reports
a usable key. Never ask them to paste an OpenAlex API key into chat, and never
print or expose the saved value. Useful variants: `--check` reports the configured
key without changing anything, `--stdin` and `--key-file` work when no editor is
available, `--print-path` prints the file to open, `--paste` types the key at a
prompt instead, and `--reconfigure` reopens the file later. Setup opens the file
itself when it is started with `--with-openalex`.

### 5. Verify

The included setup verifies its own work: require the `Installation verified`
line from step 4. To re-check the installed runtime at any time without
downloading anything, run this from the installed Skill directory:

- macOS: `.venv/bin/python scripts/setup_dependencies.py`
- Windows: `.\\.venv\\Scripts\\python.exe scripts\\setup_dependencies.py`

A successful check ends with `Python packages: verified` and the NLP model path.

Installation needs no license, activation key, device code, or account step. If
the user offers a credential file or an activation key, tell them that the
installed AreaDay needs none, and do not read, store, or forward it.

After verification, delete the temporary extraction and the upgrade backup.

Finally, ask the user to reopen the desktop application or start a new task if
the newly installed Skill is not yet visible. The ordinary invocation is:

`使用 $areaday`
