"""Where AreaDay keeps the files it owns outside a research workspace.

AreaDay owns exactly three things: the domain registry (with the global learning
database next to it), the OpenAlex key, and the pinned embedding model. They all
live in this Skill's own ``data/`` directory, and this module is the only place
that decides so: a sandbox only has to allow writes inside the folder the Skill
was installed into, and no environment variable can move these files somewhere
else.
"""

from __future__ import annotations

from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]

DATA_DIRECTORY_NAME = "data"
MODELS_DIRECTORY_NAME = "models"
MODEL_DIRECTORY_NAME = "sentence-transformers"
REGISTRY_FILENAME = "real-domains.json"
CREDENTIALS_FILENAME = "credentials.ini"
GLOBAL_LEARNING_FILENAME = "global-learning.sqlite3"


def skill_root() -> Path:
    """Return the directory this Skill is installed in."""

    return SKILL_ROOT


def data_directory() -> Path:
    """Return the directory AreaDay owns inside the Skill."""

    return SKILL_ROOT / DATA_DIRECTORY_NAME


def data_root() -> Path:
    """Return the directory holding the registry and the global learning data."""

    return data_directory()


def registry_path() -> Path:
    """Return the default domain registry file."""

    return data_root() / REGISTRY_FILENAME


def global_learning_path() -> Path:
    """Return the default global learning database."""

    return data_root() / GLOBAL_LEARNING_FILENAME


def credentials_path() -> Path:
    """Return the OpenAlex configuration file."""

    return data_directory() / CREDENTIALS_FILENAME


def config_dir() -> Path:
    """Return the directory holding the OpenAlex configuration file."""

    return credentials_path().parent


def model_root() -> Path:
    """Return the directory holding the pinned embedding model snapshots."""

    return data_directory() / MODELS_DIRECTORY_NAME / MODEL_DIRECTORY_NAME
