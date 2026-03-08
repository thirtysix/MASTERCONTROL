"""CLAUDE.md generation and update service.

Generates a CLAUDE.md file in each project root so that Claude Code
subprocesses auto-discover project context at session start, eliminating
redundant exploration.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

import yaml
from sqlmodel import Session, select

from src.db.models import Project, Task

logger = logging.getLogger(__name__)

CLAUDE_MD_FILENAME = "CLAUDE.md"
STALENESS_HOURS = 24
MAX_HISTORY_IN_FILE = 10
HISTORY_SECTION_HEADER = "## Recent Task History"


# ── Public API ────────────────────────────────────────────────


def ensure_claude_md(project: Project, session: Session, force: bool = False) -> Path:
    """Generate CLAUDE.md if missing or stale. Returns path to the file."""
    project_path = Path(project.path)
    claude_md_path = project_path / CLAUDE_MD_FILENAME

    if not force and claude_md_path.exists():
        age_hours = (
            datetime.now(timezone.utc).timestamp() - claude_md_path.stat().st_mtime
        ) / 3600
        if age_hours < STALENESS_HOURS:
            return claude_md_path

    task_summaries = _get_recent_task_summaries(project.id, session, MAX_HISTORY_IN_FILE)

    manifest_path = project_path / ".mastercontrol" / "manifest.yaml"
    if manifest_path.is_file():
        try:
            manifest = yaml.safe_load(manifest_path.read_text()) or {}
            content = _generate_from_manifest(project, manifest, task_summaries)
        except Exception:
            logger.warning("Bad manifest for %s, falling back to DB", project.name)
            content = _generate_from_db(project, task_summaries)
    else:
        content = _generate_from_db(project, task_summaries)

    claude_md_path.write_text(content)
    _ensure_gitignored(project_path)
    logger.info("Generated %s for %s", CLAUDE_MD_FILENAME, project.name)
    return claude_md_path


def update_claude_md_after_task(project_path: str, task: Task) -> None:
    """Append a completed task to the Recent Task History section of CLAUDE.md."""
    claude_md = Path(project_path) / CLAUDE_MD_FILENAME
    if not claude_md.exists():
        return

    new_entry = _format_task_entry(task)
    content = claude_md.read_text()

    if HISTORY_SECTION_HEADER in content:
        before, after = content.split(HISTORY_SECTION_HEADER, 1)
        # Parse existing entries (lines starting with "- [")
        lines = after.split("\n")
        entries = []
        rest = []
        in_entries = True
        for line in lines:
            stripped = line.strip()
            if in_entries:
                if stripped.startswith("- ["):
                    entries.append(stripped)
                elif stripped == "":
                    continue
                else:
                    in_entries = False
                    rest.append(line)
            else:
                rest.append(line)

        entries = [new_entry] + entries[: MAX_HISTORY_IN_FILE - 1]
        updated = (
            before
            + HISTORY_SECTION_HEADER
            + "\n"
            + "\n".join(entries)
            + "\n"
        )
        if rest:
            updated += "\n" + "\n".join(rest).lstrip("\n")
        claude_md.write_text(updated)
    else:
        content = (
            content.rstrip()
            + "\n\n"
            + HISTORY_SECTION_HEADER
            + "\n"
            + new_entry
            + "\n"
        )
        claude_md.write_text(content)


def get_recent_task_summaries(
    project_id: str, session: Session, limit: int = 5
) -> list[dict]:
    """Return recent completed task summaries for the append prompt."""
    tasks = session.exec(
        select(Task)
        .where(Task.project_id == project_id, Task.status == "completed")
        .order_by(Task.completed_at.desc())
        .limit(limit)
    ).all()

    summaries = []
    for t in tasks:
        date_str = t.completed_at.strftime("%Y-%m-%d") if t.completed_at else "?"
        result_preview = _first_line(t.result, 100) if t.result else ""
        summaries.append({
            "date": date_str,
            "title": t.title,
            "summary": result_preview,
        })
    return summaries


# ── Generators ────────────────────────────────────────────────


def _generate_from_manifest(
    project: Project, manifest: dict, task_summaries: list[str]
) -> str:
    """Generate CLAUDE.md from .mastercontrol/manifest.yaml (rich format)."""
    lines: list[str] = []
    proj = manifest.get("project", {})

    # Header
    lines.append(f"# {proj.get('name', project.name)}")
    lines.append("")
    desc = proj.get("description", project.description)
    if desc:
        lines.append(desc.strip())
        lines.append("")

    # Architecture / Structure
    structure = manifest.get("structure", {})
    architecture = manifest.get("architecture", {})
    if architecture or structure:
        lines.append("## Architecture")
        if isinstance(architecture, dict) and architecture.get("type"):
            lines.append(f"- **Type**: {architecture['type']}")
        # Services from architecture block
        for svc_name, svc in (architecture.get("services", {}) or {}).items():
            if isinstance(svc, dict):
                entry = svc.get("entry", "")
                desc = svc.get("description", "")
                port = svc.get("port", "")
                label = f"- **{svc_name}**: {desc}" if desc else f"- **{svc_name}**"
                if entry:
                    label += f" (entry: `{entry}`)"
                if port:
                    label += f" [port {port}]"
                lines.append(label)
        # Structure block
        for comp_name, comp in structure.items():
            if not isinstance(comp, dict):
                continue
            lang = comp.get("language", "")
            framework = comp.get("framework", "")
            entry = comp.get("entry_point", "")
            label = f"- **{comp_name.title()}**: {framework or lang}"
            if entry:
                label += f" (entry: `{entry}`)"
            lines.append(label)
        lines.append("")

    # Key files — try multiple manifest locations
    key_files = manifest.get("key_files", [])
    if not key_files:
        for comp in structure.values():
            if isinstance(comp, dict):
                for km in comp.get("key_modules", []):
                    key_files.append(km if isinstance(km, str) else km)
                for kc in comp.get("key_components", []):
                    key_files.append(kc if isinstance(kc, str) else kc)
    if not key_files:
        # Try modules block (trading-style manifest)
        for mod_name, mod in manifest.get("modules", {}).items():
            if isinstance(mod, dict):
                for comp_name, comp in mod.get("components", {}).items():
                    if isinstance(comp, dict) and comp.get("file"):
                        key_files.append({
                            "path": comp["file"],
                            "role": comp.get("description", ""),
                        })
    if key_files:
        lines.append("## Key Files")
        for kf in key_files[:15]:
            if isinstance(kf, dict):
                path = kf.get("path", "")
                role = kf.get("role", "")
                lines.append(f"- `{path}`{' -- ' + role if role else ''}")
            elif isinstance(kf, str):
                lines.append(f"- `{kf}`")
        lines.append("")

    # Services & ports
    services = manifest.get("services", {})
    ports = manifest.get("ports", {})
    if services or ports:
        lines.append("## Services")
        for svc_name, svc in services.items():
            if isinstance(svc, dict):
                port = svc.get("host_port", svc.get("port", ""))
                desc = svc.get("description", "")
                line = f"- **{svc_name}**: port {port}" if port else f"- **{svc_name}**"
                if desc:
                    line += f" -- {desc}"
                lines.append(line)
        for port_name, port_num in ports.items():
            if port_name not in services:
                lines.append(f"- **{port_name}**: port {port_num}")
        lines.append("")

    # Development commands
    dev = manifest.get("development", {})
    if dev and isinstance(dev, dict):
        lines.append("## Development")
        if dev.get("start_command"):
            lines.append(f"- **Start**: `{dev['start_command']}`")
        testing = dev.get("testing", {})
        if isinstance(testing, dict):
            for key, val in testing.items():
                if val and str(val) != "N/A":
                    lines.append(f"- **Test ({key})**: `{val}`")
        elif testing:
            lines.append(f"- **Test**: `{testing}`")
        linting = dev.get("linting", {})
        if isinstance(linting, dict):
            for key, val in linting.items():
                if val:
                    lines.append(f"- **Lint ({key})**: `{val}`")
        lines.append("")

    # Current status / phases
    phases = manifest.get("phases", [])
    _append_phases(lines, phases)

    # Task history
    if task_summaries:
        lines.append(HISTORY_SECTION_HEADER)
        for s in task_summaries:
            lines.append(s)
        lines.append("")

    return "\n".join(lines)


def _generate_from_db(project: Project, task_summaries: list[str]) -> str:
    """Generate CLAUDE.md from DB fields only (lean format)."""
    lines: list[str] = []

    lines.append(f"# {project.name}")
    lines.append("")
    if project.description:
        lines.append(project.description.strip())
        lines.append("")

    lines.append("## Project Info")
    tech = project.tech_stack_list
    if tech:
        lines.append(f"- **Tech stack**: {', '.join(tech)}")
    tags = project.tags_list
    if tags:
        lines.append(f"- **Tags**: {', '.join(tags)}")
    lines.append(f"- **Files**: ~{project.file_count} files ({project.dir_size_mb} MB)")
    if project.git_branch:
        dirty = " (uncommitted changes)" if project.git_dirty else ""
        lines.append(f"- **Git branch**: {project.git_branch}{dirty}")
    lines.append("")

    if task_summaries:
        lines.append(HISTORY_SECTION_HEADER)
        for s in task_summaries:
            lines.append(s)
        lines.append("")

    return "\n".join(lines)


# ── Helpers ───────────────────────────────────────────────────


def _get_recent_task_summaries(
    project_id: str, session: Session, limit: int = 10
) -> list[str]:
    """Query completed tasks and return formatted summary lines."""
    tasks = session.exec(
        select(Task)
        .where(Task.project_id == project_id, Task.status == "completed")
        .order_by(Task.completed_at.desc())
        .limit(limit)
    ).all()

    summaries = []
    for t in tasks:
        summaries.append(_format_task_entry(t))
    return summaries


def _format_task_entry(task: Task) -> str:
    """Format a single task as a history line."""
    date_str = task.completed_at.strftime("%Y-%m-%d") if task.completed_at else "?"
    result_preview = _first_line(task.result, 100) if task.result else ""
    return f"- [{date_str}] **{task.title}**: {result_preview}"


def _first_line(text: str, max_len: int = 100) -> str:
    """Extract first non-empty line, truncated."""
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped:
            if len(stripped) > max_len:
                return stripped[:max_len] + "..."
            return stripped
    return ""


def _append_phases(lines: list[str], phases) -> None:
    """Extract current phase/status from manifest phases field."""
    if isinstance(phases, list):
        current = [
            p for p in phases
            if isinstance(p, dict) and p.get("status") == "in_progress"
        ]
        if current:
            lines.append("## Current Status")
            for p in current:
                lines.append(f"- Phase {p.get('id', '?')}: {p.get('name', '?')}")
            lines.append("")
    elif isinstance(phases, dict):
        current = phases.get("current", [])
        if current:
            lines.append("## Current Status")
            if isinstance(current, list):
                for p in current:
                    lines.append(f"- {p}")
            else:
                lines.append(f"- {current}")
            lines.append("")


def _ensure_gitignored(project_path: Path) -> None:
    """Add CLAUDE.md to .gitignore if the project is a git repo."""
    if not (project_path / ".git").is_dir():
        return
    gitignore = project_path / ".gitignore"
    if gitignore.exists():
        content = gitignore.read_text()
        if CLAUDE_MD_FILENAME in content:
            return
        with open(gitignore, "a") as f:
            f.write(f"\n# Auto-generated project context for Claude Code\n{CLAUDE_MD_FILENAME}\n")
    else:
        gitignore.write_text(
            f"# Auto-generated project context for Claude Code\n{CLAUDE_MD_FILENAME}\n"
        )
