#!/usr/bin/env python3
"""Set the OpenAlex API key that AreaDay uses to search papers.

The normal way (what a person does):

    python3 scripts/configure_openalex.py

It creates the credentials file if needed and opens it in the user's own text
editor, then exits immediately - it never waits for anything. The user pastes
the key after ``api_key =``, saves the file and carries on. To check the result:

    python3 scripts/configure_openalex.py --check

Agents should stop here and let the user do that, then run ``--check`` when the
user says they are done.

Non-interactive variants, for agents, sandboxes and automated setup:

    python3 scripts/configure_openalex.py --stdin        # key on standard input
    python3 scripts/configure_openalex.py --key-file /path/to/key.txt
    python3 scripts/configure_openalex.py --print-path   # where the key is read from
    python3 scripts/configure_openalex.py --paste        # type the key in the terminal

Exit codes: 0 the key is usable (or the file is ready to edit), 2 the key was
rejected, 3 OpenAlex was unreachable, 4 no key is configured yet, 1 usage or
filesystem problem.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

from areaday_paths import config_dir

SETTINGS_URL = "https://openalex.org/settings/api"
VERIFY_URL = "https://api.openalex.org/rate-limit"
CREDENTIALS_FILENAME = "credentials.ini"
HELP_PAGE = Path("assets/openalex-help.html")
SECTION_NAME = "openalex"
KEY_FIELD = "api_key"

KEY_PATTERN = re.compile(r"\A[A-Za-z0-9_-]{12,200}\Z")
KEY_LINE = re.compile(r"\A[ \t]*api_key[ \t]*=(?P<value>.*)\Z")
SECTION_LINE = re.compile(r"\A[ \t]*\[(?P<name>[^\]]+)\][ \t]*\Z")

STATUS_VERIFIED = "verified"
STATUS_INVALID = "invalid"
STATUS_UNREACHABLE = "unreachable"
STATUS_MISSING = "missing"
STATUS_READY = "ready_to_edit"

EXIT_OK = 0
EXIT_USAGE = 1
EXIT_INVALID = 2
EXIT_UNREACHABLE = 3
EXIT_MISSING = 4

MAX_ATTEMPTS = 5
SENSITIVE_MODE = 0o600
PRIVATE_DIRECTORY_MODE = 0o700

TEMPLATE = f"""\
# AreaDay - OpenAlex API key
#
# 1. Open {SETTINGS_URL} and copy your complete API key (about 22 characters).
#    打开上面的网址，登录后复制你的 API Key（约 22 个字符）。
# 2. Paste it after "api_key =" below. No quotes, no spaces.
#    把它粘贴到下面 api_key = 的后面，不要加引号和空格。
# 3. Save this file, then tell your agent to continue.
#    保存本文件（Command-S），然后回到对话告诉 Agent「填好了，继续」。
#
# The key stays on this computer and is sent only to OpenAlex.

[{SECTION_NAME}]
{KEY_FIELD} =
"""


class ConfigurationError(Exception):
    """A problem the user has to fix before the key can be stored."""


def read_key(path: Path) -> str:
    """Read the OpenAlex key from a credentials file, tolerating hand edits."""
    if not path.is_file():
        return ""
    value = ""
    inside_openalex = False
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        section = SECTION_LINE.match(line)
        if section:
            inside_openalex = section.group("name").strip().lower() == SECTION_NAME
            continue
        field = KEY_LINE.match(line)
        if field and inside_openalex:
            value = field.group("value").strip()
    return value


def normalise_key(raw: str) -> str:
    """Trim the decorations people pick up when copying a key."""
    value = raw.strip()
    for wrapper in ('"', "'"):
        if len(value) >= 2 and value.startswith(wrapper) and value.endswith(wrapper):
            value = value[1:-1].strip()
    if value.lower().startswith("bearer "):
        value = value[len("bearer ") :].strip()
    for prefix in ("openalex_api_key", "api_key"):
        if value.lower().startswith(prefix):
            value = value.split("=", 1)[-1].strip()
    return value


def key_problem(key: str) -> str:
    """Return an explanation when the value cannot be an OpenAlex key."""
    if not key:
        return "No key was entered."
    if key.lower() == "anonymous":
        return (
            "AreaDay no longer supports anonymous OpenAlex access. "
            "Paste your personal API key instead."
        )
    if not KEY_PATTERN.match(key):
        return (
            "That does not look like a complete OpenAlex key. Copy the whole key "
            f"from {SETTINGS_URL} - no spaces, quotes or extra words."
        )
    return ""


def verify_key(key: str, timeout: float) -> tuple[str, str]:
    """Ask OpenAlex whether the key is valid. Never sends the key anywhere else."""
    request = urllib.request.Request(
        VERIFY_URL,
        headers={
            "Authorization": f"Bearer {key}",
            "User-Agent": "AreaDay-openalex-setup",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if response.status == 200:
                return STATUS_VERIFIED, "OpenAlex accepted the key."
            return STATUS_UNREACHABLE, f"OpenAlex answered HTTP {response.status}."
    except urllib.error.HTTPError as error:
        if error.code in (401, 403):
            return STATUS_INVALID, f"OpenAlex did not recognise this key (HTTP {error.code})."
        return STATUS_UNREACHABLE, f"OpenAlex answered HTTP {error.code}."
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        reason = getattr(error, "reason", error)
        return STATUS_UNREACHABLE, f"Could not reach OpenAlex: {reason}."


def without_stale_guidance(text: str) -> str:
    """Drop the retired note that told people to store the literal 'anonymous'."""
    kept = [
        line
        for line in text.splitlines()
        if not (line.lstrip().startswith(("#", ";")) and "anonymous" in line.lower())
    ]
    return "\n".join(kept).rstrip("\n") + "\n"


def write_private(path: Path, payload: str) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(payload)
        os.chmod(temporary, SENSITIVE_MODE)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def private_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path, PRIVATE_DIRECTORY_MODE)
    except OSError:
        pass


def has_openalex_section(lines: list[str]) -> bool:
    for line in lines:
        section = SECTION_LINE.match(line)
        if section and section.group("name").strip().lower() == SECTION_NAME:
            return True
    return False


def save_key(path: Path, key: str) -> None:
    """Store the key, keeping any other lines the user put in the file."""
    private_directory(path.parent)
    existing = path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""
    lines = without_stale_guidance(existing).splitlines() if existing else []
    replaced = False
    inside_openalex = False
    for index, line in enumerate(lines):
        section = SECTION_LINE.match(line)
        if section:
            inside_openalex = section.group("name").strip().lower() == SECTION_NAME
            continue
        if KEY_LINE.match(line) and inside_openalex:
            lines[index] = f"{KEY_FIELD} = {key}"
            replaced = True
            break

    if not replaced:
        if not has_openalex_section(lines):
            lines.append(f"[{SECTION_NAME}]")
        lines.append(f"{KEY_FIELD} = {key}")

    write_private(path, "\n".join(lines).rstrip("\n") + "\n")


def prepare_for_editing(path: Path) -> bool:
    """Make sure the file exists with an empty api_key line to fill in.

    Returns True when the file was created or completed, False when it was
    already waiting for a key.
    """
    private_directory(path.parent)
    if not path.is_file():
        write_private(path, TEMPLATE)
        return True

    text = without_stale_guidance(path.read_text(encoding="utf-8", errors="replace"))
    lines = text.splitlines()
    changed = text != path.read_text(encoding="utf-8", errors="replace")

    inside_openalex = False
    section_index: int | None = None
    field_index: int | None = None
    for index, line in enumerate(lines):
        section = SECTION_LINE.match(line)
        if section:
            inside_openalex = section.group("name").strip().lower() == SECTION_NAME
            if inside_openalex and section_index is None:
                section_index = index
            continue
        if KEY_LINE.match(line) and inside_openalex and field_index is None:
            field_index = index

    if section_index is None:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append(f"[{SECTION_NAME}]")
        lines.append(f"{KEY_FIELD} =")
        changed = True
    elif field_index is None:
        lines.insert(section_index + 1, f"{KEY_FIELD} =")
        changed = True

    if changed:
        write_private(path, "\n".join(lines).rstrip("\n") + "\n")
    return changed


def open_in_editor(path: Path) -> str:
    """Best effort: hand the file to the user's own editor. Never blocks."""
    if sys.platform == "darwin":
        command = ["open", "-e", str(path)]
    elif os.name == "nt":  # pragma: no cover - exercised on Windows only
        command = [
            "powershell.exe",
            "-NoProfile",
            "-Command",
            f"Invoke-Item -LiteralPath '{path}'",
        ]
    else:
        editor = os.environ.get("VISUAL") or os.environ.get("EDITOR")
        command = [editor, str(path)] if editor else ["xdg-open", str(path)]
    try:
        subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
        )
    except OSError:
        return ""
    return " ".join(command[:1])


def describe_source(path: Path, saved: str) -> tuple[str, str]:
    """Return (source, key) for the key AreaDay would use right now."""
    return str(path), saved


def report(args, status: str, message: str, path: Path, source: str, extra: dict | None = None) -> int:
    if args.json:
        payload = {
            "status": status,
            "message": message,
            "credentials_path": str(path),
            "key_source": source,
        }
        if extra:
            payload.update(extra)
        print(json.dumps(payload, ensure_ascii=False))
    else:
        print(message)
    return {
        STATUS_VERIFIED: EXIT_OK,
        STATUS_READY: EXIT_OK,
        STATUS_INVALID: EXIT_INVALID,
        STATUS_UNREACHABLE: EXIT_UNREACHABLE,
        STATUS_MISSING: EXIT_MISSING,
    }[status]


def read_supplied_key(args) -> str:
    if args.key_file is not None:
        source = Path(args.key_file).expanduser()
        if not source.is_file():
            raise ConfigurationError(f"Key file not found: {source}")
        return source.read_text(encoding="utf-8", errors="replace")
    return sys.stdin.read()


def hand_over(path: Path, skill_dir: Path, args) -> int:
    """Open the file for the user and return immediately - no waiting."""
    created = prepare_for_editing(path)
    opened = "" if args.no_open else open_in_editor(path)
    guide = skill_dir / HELP_PAGE
    lines = [
        f"OpenAlex key file: {path}",
    ]
    if opened:
        lines.append(f"Opened it with {opened}. Paste the key after 'api_key =' and save the file.")
    else:
        lines.append("Paste the key after 'api_key =' in that file and save it.")
    lines.append(f"Get the key from {SETTINGS_URL} (free; about 22 characters).")
    if guide.is_file():
        lines.append(f"Illustrated steps: {guide}")
    if not created:
        lines.append("The file already had an api_key line; re-run with --check when the key is saved.")
    lines.append("Nothing is waiting for input. Check with: --check")
    return report(
        args,
        STATUS_READY,
        "\n".join(lines),
        path,
        str(path),
        extra={"created": created, "opened_with": opened},
    )


def prompt_for_key(path: Path, args) -> str:
    print("AreaDay searches papers with your own OpenAlex API key, which is free.")
    print(f"  1. Sign in at {SETTINGS_URL} and copy the complete key.")
    print(f"  2. Paste it below. It is saved to {path} and never printed back.")
    print("  Press Control-C to cancel.")
    print()
    try:
        return getpass.getpass("Paste your OpenAlex API key: ")
    except (EOFError, KeyboardInterrupt):
        print("\nCancelled: no key was entered.")
        return ""


def interactive_key(path: Path, args) -> tuple[str, str]:
    """Ask until OpenAlex accepts a key or the user gives up (--paste only)."""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        entered = normalise_key(
            prompt_for_key(path, args) if attempt == 1 else _paste_again(attempt)
        )
        if not entered:
            return STATUS_MISSING, "No key was entered."
        problem = key_problem(entered)
        if problem:
            print(f"{problem}\n")
            continue
        status, message = verify_key(entered, args.timeout)
        if status == STATUS_VERIFIED:
            save_key(path, entered)
            return STATUS_VERIFIED, f"OpenAlex accepted the key. Saved to {path}"
        if status == STATUS_INVALID:
            print(f"{message} Copy the complete key from {SETTINGS_URL} and try again.\n")
            continue
        print(message)
        if args.accept_unverified or confirm_accept_unverified():
            save_key(path, entered)
            return (
                STATUS_UNREACHABLE,
                f"Saved to {path} without verification. AreaDay will check the key on first use.",
            )
        return STATUS_UNREACHABLE, "Nothing was saved. Run this again when OpenAlex is reachable."
    print("Too many attempts: nothing was saved.")
    return STATUS_MISSING, "Too many attempts: nothing was saved."


def _paste_again(attempt: int) -> str:
    try:
        return getpass.getpass(f"Paste your OpenAlex API key (attempt {attempt}): ")
    except (EOFError, KeyboardInterrupt):
        print("\nCancelled: no key was entered.")
        return ""


def confirm_accept_unverified() -> bool:
    try:
        answer = input("Save the key without verification? [y/N] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    return answer in {"y", "yes"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Configure the OpenAlex API key that AreaDay searches with.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python3 scripts/configure_openalex.py              # open the file for the user to fill in\n"
            "  python3 scripts/configure_openalex.py --check      # report whether a usable key is saved\n"
            "  python3 scripts/configure_openalex.py --stdin < key.txt\n"
        ),
    )
    parser.add_argument(
        "--reconfigure",
        action="store_true",
        help="open the file for editing even when a valid key is already saved",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="report the current configuration and exit without changing anything",
    )
    parser.add_argument(
        "--stdin", action="store_true", help="read the key from standard input instead of opening the file"
    )
    parser.add_argument(
        "--key-file", type=Path, help="read the key from this file instead of opening the editor"
    )
    parser.add_argument(
        "--paste",
        action="store_true",
        help="type the key into this terminal instead of editing the file",
    )
    parser.add_argument(
        "--timeout", type=float, default=20.0, help="seconds to wait for OpenAlex (default: 20)"
    )
    parser.add_argument("--no-open", action="store_true", help="do not launch a text editor")
    parser.add_argument(
        "--accept-unverified",
        action="store_true",
        help="store a pasted key even when OpenAlex cannot be reached to verify it",
    )
    parser.add_argument("--json", action="store_true", help="print the result as JSON")
    parser.add_argument("--print-path", action="store_true", help="print the credentials path and exit")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    skill_dir = Path(__file__).resolve().parent.parent
    path = config_dir() / CREDENTIALS_FILENAME

    if args.print_path:
        print(path)
        return EXIT_OK

    saved = read_key(path)
    source, effective = describe_source(path, saved)

    if args.check:
        if not effective:
            message = (
                f"No OpenAlex key is configured yet ({path}). "
                f"Run: python3 scripts/configure_openalex.py"
            )
            return report(args, STATUS_MISSING, message, path, source)
        problem = key_problem(effective)
        if problem:
            return report(args, STATUS_INVALID, f"{problem} (key source: {source})", path, source)
        status, message = verify_key(effective, args.timeout)
        return report(args, status, f"{message} (key source: {source})", path, source)

    if args.stdin or args.key_file is not None:
        try:
            supplied = normalise_key(read_supplied_key(args))
        except ConfigurationError as error:
            return report(args, STATUS_MISSING, str(error), path, str(path))
        problem = key_problem(supplied)
        if problem:
            return report(args, STATUS_INVALID, problem, path, str(path))
        status, message = verify_key(supplied, args.timeout)
        if status == STATUS_INVALID:
            return report(args, STATUS_INVALID, message, path, str(path))
        if status == STATUS_UNREACHABLE and not args.accept_unverified:
            return report(
                args,
                STATUS_UNREACHABLE,
                f"{message} Nothing was saved. Re-run with --accept-unverified to store it anyway.",
                path,
                str(path),
            )
        save_key(path, supplied)
        return report(
            args,
            STATUS_VERIFIED if status == STATUS_VERIFIED else STATUS_UNREACHABLE,
            f"{message} Saved to {path}",
            path,
            str(path),
        )

    if args.paste:
        if not sys.stdin.isatty():
            message = (
                f"No terminal is attached, so a key cannot be typed here ({path}). "
                "Open the file instead, or pass --stdin / --key-file."
            )
            return report(args, STATUS_MISSING, message, path, str(path))
        status, message = interactive_key(path, args)
        return report(args, status, message, path, str(path))

    if effective and not args.reconfigure:
        status, message = verify_key(effective, args.timeout)
        if status == STATUS_VERIFIED:
            return report(
                args,
                STATUS_VERIFIED,
                f"A usable OpenAlex key is already configured (key source: {source}).",
                path,
                source,
            )
        print(f"{message} Opening the file so a working key can be saved.\n")

    return hand_over(path, skill_dir, args)


if __name__ == "__main__":
    sys.exit(main())
