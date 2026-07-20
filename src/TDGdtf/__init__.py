from __future__ import annotations

from importlib import resources
from pathlib import Path

__all__ = [
    '__version__',
    '__td_requires_touchdesigner__',
    '__td_package_type__',
    '__td_collection__',
    'assetsPath',
    'toxPath',
    'toxPaths',
]

__version__ = "0.1.11"
__td_requires_touchdesigner__ = "2025.32779.24"
__td_package_type__ = "singleton"
__td_collection__ = {
    "TDGdtfFixture": Path(str(resources.files(__package__) / "tdgdtfFixture.tox")),
}


def toxPath(name: str | None = None) -> Path:
    """Return the path to the packaged root .tox file."""
    key = "TDGdtfFixture" if name is None else str(name)
    try:
        return __td_collection__[key]
    except KeyError as exc:
        raise KeyError(f"Unknown packaged .tox: {key}") from exc


def toxPaths() -> dict[str, Path]:
    """Return all packaged root .tox files keyed by name."""
    return dict(__td_collection__)


def assetsPath() -> Path:
    """Return the path to the packaged assets directory."""
    return Path(str(resources.files(__package__) / "assets"))