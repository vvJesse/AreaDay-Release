"""Where AreaDay keeps the files it owns outside a research workspace.

AreaDay owns exactly three things: the domain registry (with the global learning
database next to it), the OpenAlex key, and the pinned embedding model. They all
live in this Skill's own ``data/`` directory, so a sandbox only has to allow
writes inside the folder the Skill was installed into. Each area also has an
environment override for hosts that keep the data somewhere else.
"""

from __future__ import annotations

import os
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]

DATA_DIRECTORY_NAME = "data"
MODELS_DIRECTORY_NAME = "models"
MODEL_DIRECTORY_NAME = "sentence-transformers"
REGISTRY_FILENAME = "real-domains.json"
CREDENTIALS_FILENAME = "credentials.ini"
GLOBAL_LEARNING_FILENAME = "global-learning.sqlite3"

DATA_DIR_VARIABLE = "AREADAY_DATA_DIR"
CONFIG_DIR_VARIABLE = "AREADAY_CONFIG_DIR"
MODEL_DIR_VARIABLE = "AREADAY_MODEL_DIR"


def _environment_path(variable: str, *, resolve: bool = False) -> Path | None:
    """Return the path a host configured, or ``None`` when it is unset.

    Directory variables keep the exact spelling the host gave so that messages
    quote back what the host typed; the data directory is resolved because
    callers compare it against other resolved paths.
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


def data_root() -> Path:
    """Return the directory holding the registry and the global learning data."""

    override = _environment_path(DATA_DIR_VARIABLE, resolve=True)
    return data_directory() if override is None else override


def registry_path() -> Path:
    """Return the default domain registry file."""

    return data_root() / REGISTRY_FILENAME


def global_learning_path() -> Path:
    """Return the default global learning database."""

    return data_root() / GLOBAL_LEARNING_FILENAME


def credentials_path() -> Path:
    """Return the default OpenAlex configuration file."""

    override = _environment_path(CONFIG_DIR_VARIABLE)
    if override is not None:
        return override / CREDENTIALS_FILENAME
    return data_directory() / CREDENTIALS_FILENAME


def config_dir() -> Path:
    """Return the directory holding the OpenAlex configuration file."""

    return credentials_path().parent


def model_root() -> Path:
    """Return the directory holding the pinned embedding model snapshots."""

    override = _environment_path(MODEL_DIR_VARIABLE)
    if override is not None:
        return override
    return data_directory() / MODELS_DIRECTORY_NAME / MODEL_DIRECTORY_NAME
