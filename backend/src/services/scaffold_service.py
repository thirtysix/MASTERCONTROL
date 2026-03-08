"""Scaffold service — creates universal base directories for projects."""
from __future__ import annotations

import logging
from pathlib import Path

from src.config import settings

logger = logging.getLogger(__name__)

_DATA_GITIGNORE = """\
# Large data files — keep out of git
*.csv
*.tsv
*.parquet
*.h5
*.hdf5
*.db
*.sqlite
*.pkl
*.pickle
*.npy
*.npz
*.zarr/
*.arrow
*.feather
"""

_LOGS_GITIGNORE = """\
*.log
*.log.*
"""

_MANIFEST_TEMPLATE = """\
project:
  name: "{name}"
  status: active

description: ""

tags: []
"""


def check_missing_base_dirs(project_path: Path) -> list[str]:
    """Return list of base directories missing from the project."""
    missing = []
    for d in settings.base_dirs:
        if not (project_path / d).is_dir():
            missing.append(d)
    return missing


def scaffold_base_dirs(project_path: Path, project_name: str) -> list[str]:
    """Create missing base directories in a project.

    Returns list of directories that were created.
    """
    created = []
    for d in settings.base_dirs:
        dir_path = project_path / d
        if dir_path.is_dir():
            continue

        dir_path.mkdir(parents=True, exist_ok=True)
        created.append(d)
        logger.info("Created %s in %s", d, project_path.name)

        # Seed directory-specific files
        if d == ".mastercontrol":
            manifest = dir_path / "manifest.yaml"
            if not manifest.exists():
                manifest.write_text(
                    _MANIFEST_TEMPLATE.format(name=project_name)
                )
        elif d == "data":
            gitignore = dir_path / ".gitignore"
            if not gitignore.exists():
                gitignore.write_text(_DATA_GITIGNORE)
            _ensure_gitkeep(dir_path)
        elif d == "logs":
            gitignore = dir_path / ".gitignore"
            if not gitignore.exists():
                gitignore.write_text(_LOGS_GITIGNORE)
            _ensure_gitkeep(dir_path)
        else:
            _ensure_gitkeep(dir_path)

    return created


def _ensure_gitkeep(dir_path: Path) -> None:
    """Add a .gitkeep if the directory is otherwise empty."""
    gitkeep = dir_path / ".gitkeep"
    if not gitkeep.exists() and not any(dir_path.iterdir()):
        gitkeep.touch()
