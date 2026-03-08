"""Deep scanner for projects in the projects directory.

Detects tech stack, git state, Docker status, README description,
file count, and directory size. Populates the SQLite cache from
filesystem state.
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import yaml
from sqlmodel import Session

from src.config import settings
from src.db.models import Project
from src.services.scaffold_service import check_missing_base_dirs

logger = logging.getLogger(__name__)

# Tags auto-detected from tech stack
_TECH_TAG_MAP: dict[str, list[str]] = {
    "elasticsearch": ["search"],
    "fastapi": ["web"],
    "react": ["web"],
    "docker": ["infra"],
    "pytorch": ["ml"],
    "transformers": ["ml", "nlp"],
    "peft": ["fine-tuning", "ml"],
    "unsloth": ["fine-tuning", "ml"],
    "tensorflow": ["ml"],
    "plotly": ["visualization"],
    "d3": ["visualization"],
    "netlify": ["web"],
    "flask": ["web"],
    "express": ["web"],
}


def scan_all(session: Session) -> list[Project]:
    """Scan all project directories and upsert into database."""
    projects_dir = settings.projects_dir
    if not projects_dir.is_dir():
        logger.error("Projects directory does not exist: %s", projects_dir)
        return []

    projects = []
    for entry in sorted(projects_dir.iterdir()):
        if not entry.is_dir():
            continue
        if entry.name in settings.skip_dirs:
            continue

        try:
            project = _scan_project(entry)
            if project:
                _upsert_project(session, project)
                projects.append(project)
        except Exception:
            logger.exception("Failed to scan %s", entry.name)

    session.commit()

    # Generate CLAUDE.md for all projects
    from src.services.memory_service import ensure_claude_md

    for project in projects:
        try:
            ensure_claude_md(project, session)
        except Exception:
            logger.warning("Failed to generate CLAUDE.md for %s", project.name)

    return projects


def scan_one(session: Session, project_id: str) -> Project | None:
    """Deep scan a single project by ID."""
    existing = session.get(Project, project_id)
    if not existing:
        return None
    path = Path(existing.path)
    if not path.is_dir():
        return None
    project = _scan_project(path)
    if project:
        _upsert_project(session, project)
        session.commit()

        # Regenerate CLAUDE.md after rescan
        from src.services.memory_service import ensure_claude_md

        try:
            ensure_claude_md(project, session, force=True)
        except Exception:
            logger.warning("Failed to generate CLAUDE.md for %s", project.name)

    return project


def _scan_project(path: Path) -> Project | None:
    """Scan a single project directory and return a Project object."""
    project_id = path.name.lower().replace(" ", "-").replace("_", "-")
    name = path.name.replace("_", " ").replace("-", " ").title()

    # Check for .mastercontrol/manifest.yaml (authoritative)
    manifest_path = path / ".mastercontrol" / "manifest.yaml"
    manifest = {}
    if manifest_path.is_file():
        try:
            manifest = yaml.safe_load(manifest_path.read_text()) or {}
        except Exception:
            logger.warning("Bad manifest.yaml in %s", path.name)

    # Tech stack detection
    tech_stack = _detect_tech_stack(path)

    # Auto-generate tags from tech stack if no manifest tags
    tags = manifest.get("tags", [])
    if not tags:
        tags = _auto_tags(path, tech_stack)

    # Git info
    git_branch, git_last_commit, git_dirty = _git_info(path)

    # Docker status
    docker_status = _docker_status(path)

    # README description
    description = manifest.get("description", "") or _readme_description(path)

    # File count and size
    file_count, dir_size_mb = _dir_stats(path)

    # Last modified
    last_modified = _last_modified(path)

    # Check for missing base directories
    missing = check_missing_base_dirs(path)

    return Project(
        id=manifest.get("id", project_id),
        name=manifest.get("name", name),
        path=str(path),
        description=description,
        tags=json.dumps(tags),
        status=manifest.get("status", "active"),
        tech_stack=json.dumps(tech_stack),
        git_branch=git_branch,
        git_last_commit=git_last_commit,
        git_dirty=git_dirty,
        docker_status=docker_status,
        has_mastercontrol=manifest_path.is_file(),
        missing_base_dirs=json.dumps(missing),
        file_count=file_count,
        dir_size_mb=dir_size_mb,
        last_modified=last_modified,
        scanned_at=datetime.now(timezone.utc),
    )


def _detect_tech_stack(path: Path) -> list[str]:
    """Detect technologies used in a project."""
    stack = []

    if (path / "package.json").is_file():
        stack.append("node")
        try:
            pkg = json.loads((path / "package.json").read_text())
            deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
            if "react" in deps:
                stack.append("react")
            if "vue" in deps:
                stack.append("vue")
            if "vite" in deps:
                stack.append("vite")
            if "tailwindcss" in deps or "@tailwindcss/vite" in deps:
                stack.append("tailwind")
            if "express" in deps:
                stack.append("express")
            if "typescript" in deps:
                stack.append("typescript")
        except Exception:
            pass

    if (path / "pyproject.toml").is_file() or (path / "requirements.txt").is_file():
        stack.append("python")
        # Check for common Python packages
        req_text = ""
        if (path / "requirements.txt").is_file():
            req_text = (path / "requirements.txt").read_text().lower()
        if (path / "pyproject.toml").is_file():
            req_text += (path / "pyproject.toml").read_text().lower()
        for pkg in ["fastapi", "flask", "django", "pytorch", "transformers",
                     "peft", "unsloth", "elasticsearch", "plotly", "pandas"]:
            if pkg in req_text:
                stack.append(pkg)

    if (path / "docker-compose.yml").is_file() or (path / "docker-compose.yaml").is_file():
        stack.append("docker")
    elif (path / "Dockerfile").is_file():
        stack.append("docker")

    if (path / ".git").is_dir():
        stack.append("git")

    return stack


def _auto_tags(path: Path, tech_stack: list[str]) -> list[str]:
    """Generate tags from project name and tech stack."""
    tags: list[str] = []
    name_lower = path.name.lower()

    # Name-based heuristics
    if "rag" in name_lower:
        tags.append("rag")
    if "pubmed" in name_lower or "biomedical" in name_lower:
        tags.append("biomedical")
    if "finetune" in name_lower or "fine_tune" in name_lower:
        tags.append("fine-tuning")
    if "trading" in name_lower:
        tags.append("finance")
    if "rtl" in name_lower or "sdr" in name_lower:
        tags.append("hardware")
    if "netlify" in name_lower:
        tags.append("web")
    if "scview" in name_lower or "sc_view" in name_lower:
        tags.extend(["visualization", "biomedical"])
    if "manuscript" in name_lower:
        tags.extend(["nlp", "web"])
    if "master" in name_lower and "control" in name_lower:
        tags.extend(["meta", "web"])

    # Tech-stack-based tags
    for tech in tech_stack:
        for mapped_tag in _TECH_TAG_MAP.get(tech, []):
            if mapped_tag not in tags:
                tags.append(mapped_tag)

    return tags or ["other"]


def _git_info(path: Path) -> tuple[str | None, str | None, bool]:
    """Get git branch, last commit message, and dirty status."""
    if not (path / ".git").is_dir():
        return None, None, False
    try:
        branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=path, capture_output=True, text=True, timeout=5,
        ).stdout.strip() or None

        last_commit = subprocess.run(
            ["git", "log", "-1", "--format=%s"],
            cwd=path, capture_output=True, text=True, timeout=5,
        ).stdout.strip() or None

        dirty_out = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=path, capture_output=True, text=True, timeout=5,
        ).stdout.strip()
        dirty = bool(dirty_out)

        return branch, last_commit, dirty
    except Exception:
        return None, None, False


def _docker_status(path: Path) -> str | None:
    """Check if Docker containers are running for this project."""
    compose_file = path / "docker-compose.yml"
    if not compose_file.is_file():
        compose_file = path / "docker-compose.yaml"
    if not compose_file.is_file():
        return None

    try:
        result = subprocess.run(
            ["docker", "compose", "ps", "--format", "json"],
            cwd=path, capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return "stopped"
        output = result.stdout.strip()
        if not output:
            return "stopped"
        return "running"
    except FileNotFoundError:
        return None  # docker not installed
    except Exception:
        return "stopped"


def _readme_description(path: Path) -> str:
    """Extract first paragraph from README.md."""
    for name in ["README.md", "readme.md", "README.txt"]:
        readme = path / name
        if readme.is_file():
            try:
                text = readme.read_text(errors="replace")
                # Skip title lines and blank lines, get first paragraph
                lines = text.split("\n")
                para_lines = []
                started = False
                for line in lines:
                    stripped = line.strip()
                    if not started:
                        if stripped and not stripped.startswith("#") and not stripped.startswith("=") and not stripped.startswith("-") and not all(c == '=' for c in stripped) and not all(c == '-' for c in stripped):
                            started = True
                            para_lines.append(stripped)
                    else:
                        if not stripped:
                            break
                        para_lines.append(stripped)
                desc = " ".join(para_lines)
                return desc[:300] if desc else ""
            except Exception:
                pass
    return ""


def _dir_stats(path: Path) -> tuple[int, float]:
    """Count files and total size in MB (shallow, skip heavy dirs)."""
    file_count = 0
    total_bytes = 0
    skip = {"node_modules", ".git", "__pycache__", ".venv", "venv", ".next"}
    try:
        for root, dirs, files in os.walk(path):
            dirs[:] = [d for d in dirs if d not in skip]
            for f in files:
                file_count += 1
                try:
                    total_bytes += (Path(root) / f).stat().st_size
                except OSError:
                    pass
            if file_count > 10000:
                break  # safety limit for huge projects
    except Exception:
        pass
    return file_count, round(total_bytes / (1024 * 1024), 1)


def _last_modified(path: Path) -> datetime | None:
    """Get most recent modification time of files in the project."""
    latest = 0.0
    skip = {"node_modules", ".git", "__pycache__", ".venv", "venv"}
    try:
        for root, dirs, files in os.walk(path):
            dirs[:] = [d for d in dirs if d not in skip]
            for f in files:
                try:
                    mtime = (Path(root) / f).stat().st_mtime
                    if mtime > latest:
                        latest = mtime
                except OSError:
                    pass
            if latest > 0:
                # Only check first level deep for speed
                break
    except Exception:
        pass
    if latest > 0:
        return datetime.fromtimestamp(latest, tz=timezone.utc)
    return None


def _upsert_project(session: Session, project: Project) -> None:
    """Insert or update a project in the database."""
    existing = session.get(Project, project.id)
    if existing:
        for field in project.model_fields:
            if field != "created_at":
                setattr(existing, field, getattr(project, field))
        session.add(existing)
    else:
        session.add(project)
