"""Where AreaDay keeps the files it owns outside a research workspace.

AreaDay owns exactly three things: the domain registry (with the global learning
database next to it), the OpenAlex key, and the pinned embedding model. They all
default to this Skill's own ``data/`` directory, so a sandbox only has to allow
writes inside the folder the Skill was installed into.

Each area keeps its own environment override, and anything an earlier version
wrote to the system application-data directory (or to ``~/.areaday``) is reused
in place: nothing is copied, moved or deleted, and the reuse is announced once so
that moving the files into ``data/`` stays a deliberate step.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Iterable


SKILL_ROOT = Path(__file__).resolve().parents[1]

DATA_DIRECTORY_NAME = "data"
MODELS_DIRECTORY_NAME = "models"
MODEL_DIRECTORY_NAME = "sentence-transformers"
REGISTRY_FILENAME = "real-domains.json"
CREDENTIALS_FILENAME = "credentials.ini"
GLOBAL_LEARNING_FILENAME = "global-learning.sqlite3"
JSON_SUFFIX = ".json"

DATA_DIR_VARIABLE = "AREADAY_DATA_DIR"
CONFIG_DIR_VARIABLE = "AREADAY_CONFIG_DIR"
MODEL_DIR_VARIABLE = "AREADAY_MODEL_DIR"

AREADAY_DIRECTORY = Path.home() / ".areaday"
RESEARCHRAMP_CREDENTIALS = Path.home() / ".researchramp" / "credentials.ini"

_ANNOUNCED: set[str] = set()


def reset_announcements() -> None:
    """Forget which notices were printed (used by the test suite)."""

    _ANNOUNCED.clear()


def _announce(area: str, used: Path, preferred: Path) -> None:
    if area in _ANNOUNCED:
        return
    _ANNOUNCED.add(area)
    print(
        f"AreaDay keeps using {area} from {used}, because the new default "
        f"{preferred} does not exist yet. Nothing was moved or deleted.",
        file=sys.stderr,
    )


def _first_existing(
    candidates: Iterable[Path], predicate
) -> Path | None:
    for candidate in candidates:
        try:
            if predicate(candidate):
                return candidate
        except OSError:
            continue
    return None


def _environment_path(variable: str, *, resolve: bool = False) -> Path | None:
    """Return the path a host configured, or ``None`` when it is unset.

    Directory variables keep the exact spelling the host gave so that messages
    quote back what the host typed; the data directory has always been resolved
    (callers compare it against other resolved paths).
    """

    value = os.environ.get(variable, "").strip()
    if not value:
        return None
    path = Path(value).expanduser()
    return path.resolve() if resolve else path


def skill_root() -> Path:
    """Return the directory this Skill is installed in."""

    return SKILL_ROOT


def data_directory() -> Path:
    """Return the directory AreaDay owns inside the Skill."""

    return SKILL_ROOT / DATA_DIRECTORY_NAME


def legacy_data_roots(platform_name: str | None = None) -> tuple[Path, ...]:
    """Return the application-data directories earlier versions wrote to."""

    platform = (platform_name or sys.platform).lower()
    roots: list[Path] = []
    if platform in {"darwin", "mac", "macos"}:
        roots.append(
            Path.home() / "Library" / "Application Support" / "AreaDay" / "data"
        )
    elif platform in {"win32", "windows", "win"}:
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            roots.append(Path(local_app_data) / "AreaDay" / "data")
    return tuple(roots)


def legacy_credentials_candidates() -> tuple[Path, ...]:
    """Return the key files earlier versions wrote, newest location first."""

    return (AREADAY_DIRECTORY / CREDENTIALS_FILENAME, RESEARCHRAMP_CREDENTIALS)


def legacy_model_roots() -> tuple[Path, ...]:
    """Return the model directories earlier versions installed into."""

    return (AREADAY_DIRECTORY / MODELS_DIRECTORY_NAME / MODEL_DIRECTORY_NAME,)


def data_root(platform_name: str | None = None) -> Path:
    """Return the directory holding the registry and the global learning data."""

    override = _environment_path(DATA_DIR_VARIABLE, resolve=True)
    if override is not None:
        return override
    preferred = data_directory()
    if (preferred / REGISTRY_FILENAME).is_file():
        return preferred
    legacy = _first_existing(
        legacy_data_roots(platform_name),
        lambda root: (root / REGISTRY_FILENAME).is_file(),
    )
    if legacy is not None:
        _announce("the domain registry", legacy, preferred)
        return legacy
    return preferred


def registry_path(platform_name: str | None = None) -> Path:
    """Return the default domain registry file."""

    return data_root(platform_name) / REGISTRY_FILENAME


def global_learning_path(platform_name: str | None = None) -> Path:
    """Return the default global learning database."""

    return data_root(platform_name) / GLOBAL_LEARNING_FILENAME


def credentials_path() -> Path:
    """Return the default OpenAlex configuration file."""

    override = _environment_path(CONFIG_DIR_VARIABLE)
    if override is not None:
        return override / CREDENTIALS_FILENAME
    preferred = data_directory() / CREDENTIALS_FILENAME
    if preferred.is_file():
        return preferred
    legacy = _first_existing(
        legacy_credentials_candidates(), lambda path: path.is_file()
    )
    if legacy is not None:
        _announce("the OpenAlex key", legacy, preferred)
        return legacy
    return preferred


def config_dir() -> Path:
    """Return the directory holding the OpenAlex configuration file."""

    return credentials_path().parent


def model_root() -> Path:
    """Return the directory holding the pinned embedding model snapshots."""

    override = _environment_path(MODEL_DIR_VARIABLE)
    if override is not None:
        return override
    preferred = data_directory() / MODELS_DIRECTORY_NAME / MODEL_DIRECTORY_NAME
    if preferred.is_dir():
        return preferred
    legacy = _first_existing(legacy_model_roots(), lambda root: root.is_dir())
    if legacy is not None:
        _announce("the embedding model", legacy, preferred)
        return legacy
    return preferred
