from __future__ import annotations

import json
import shlex
import subprocess
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from src.config import settings
from src.db.database import get_session
from src.db.models import Project
from src.services.project_scanner import scan_one
from src.services.scaffold_service import scaffold_base_dirs
from src.services.session_service import list_sessions
from src.services.window_manager import find_and_activate

router = APIRouter(prefix="/api/projects", tags=["projects"])


class ProjectUpdate(BaseModel):
    tags: list[str] | None = None
    status: str | None = None
    description: str | None = None


class ProjectOut(BaseModel):
    id: str
    name: str
    path: str
    description: str
    tags: list[str]
    status: str
    tech_stack: list[str]
    git_branch: str | None
    git_last_commit: str | None
    git_dirty: bool
    docker_status: str | None
    has_mastercontrol: bool
    missing_base_dirs: list[str]
    file_count: int
    dir_size_mb: float
    last_modified: str | None
    scanned_at: str | None

    @classmethod
    def from_db(cls, p: Project) -> ProjectOut:
        return cls(
            id=p.id,
            name=p.name,
            path=p.path,
            description=p.description,
            tags=p.tags_list,
            status=p.status,
            tech_stack=p.tech_stack_list,
            git_branch=p.git_branch,
            git_last_commit=p.git_last_commit,
            git_dirty=p.git_dirty,
            docker_status=p.docker_status,
            has_mastercontrol=p.has_mastercontrol,
            missing_base_dirs=json.loads(p.missing_base_dirs),
            file_count=p.file_count,
            dir_size_mb=p.dir_size_mb,
            last_modified=p.last_modified.isoformat() if p.last_modified else None,
            scanned_at=p.scanned_at.isoformat() if p.scanned_at else None,
        )


@router.get("", response_model=list[ProjectOut])
def list_projects(session: Session = Depends(get_session)):
    projects = session.exec(select(Project).order_by(Project.name)).all()
    return [ProjectOut.from_db(p) for p in projects]


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(project_id: str, session: Session = Depends(get_session)):
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    return ProjectOut.from_db(project)


@router.patch("/{project_id}", response_model=ProjectOut)
def update_project(project_id: str, body: ProjectUpdate, session: Session = Depends(get_session)):
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    if body.tags is not None:
        project.tags = json.dumps(body.tags)
    if body.status is not None:
        project.status = body.status
    if body.description is not None:
        project.description = body.description
    session.add(project)
    session.commit()
    session.refresh(project)
    return ProjectOut.from_db(project)


@router.post("/{project_id}/rescan", response_model=ProjectOut)
def rescan_project(project_id: str, session: Session = Depends(get_session)):
    project = scan_one(session, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    return ProjectOut.from_db(project)


@router.post("/{project_id}/scaffold")
def scaffold_project(project_id: str, session: Session = Depends(get_session)):
    """Create missing base directories in a project."""
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    path = Path(project.path)
    if not path.is_dir():
        raise HTTPException(400, "Project directory not found")

    created = scaffold_base_dirs(path, project.name)

    # Rescan to update missing_base_dirs
    updated = scan_one(session, project_id)

    return {
        "created": created,
        "project": ProjectOut.from_db(updated) if updated else None,
    }


@router.post("/{project_id}/terminal")
def open_terminal(project_id: str, session: Session = Depends(get_session)):
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    path = Path(project.path)
    if not path.is_dir():
        raise HTTPException(400, "Project directory not found")

    # Validate path is within projects_dir
    try:
        path.resolve().relative_to(settings.projects_dir.resolve())
    except ValueError:
        raise HTTPException(400, "Path outside projects directory")

    try:
        subprocess.Popen(
            [settings.terminal_cmd, "--working-directory", str(path)],
            start_new_session=True,
        )
    except FileNotFoundError:
        # Fallback: try xterm
        try:
            subprocess.Popen(
                ["xterm", "-e", f"cd '{path}' && bash"],
                start_new_session=True,
            )
        except FileNotFoundError:
            raise HTTPException(500, "No terminal emulator found")

    return {"status": "ok", "path": str(path)}


# ── Claude Code Sessions ──────────────────────────────────────


@router.get("/{project_id}/sessions")
def list_project_sessions(project_id: str, session: Session = Depends(get_session)):
    """List Claude Code sessions for a project."""
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    sessions = list_sessions(project.path)
    return {"project_id": project_id, "sessions": sessions}


class ClaudeTerminalRequest(BaseModel):
    session_id: str | None = None
    task_text: str | None = None
    fork: bool = False
    plan_mode: bool = False


@router.post("/{project_id}/claude-terminal")
def open_claude_terminal(
    project_id: str,
    body: ClaudeTerminalRequest,
    session: Session = Depends(get_session),
):
    """Open Claude Code in a gnome-terminal for a project.

    If a terminal with a matching title already exists, it will be
    brought to the foreground (and moved to the current workspace)
    instead of spawning a new one.
    """
    project = session.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    path = Path(project.path)
    if not path.is_dir():
        raise HTTPException(400, "Project directory not found")

    try:
        path.resolve().relative_to(settings.projects_dir.resolve())
    except ValueError:
        raise HTTPException(400, "Path outside projects directory")

    # Build a distinctive window title for tracking
    session_short = body.session_id[:12] if body.session_id else "new"
    win_title = f"MC:{project.name}:{session_short}"

    # Try to find and activate an existing terminal window first
    if body.session_id and not body.task_text:
        activated = find_and_activate(win_title)
        if activated:
            return {"status": "activated", "window_title": win_title, "path": str(path)}

    # Build the claude command
    claude_cmd = "claude"
    if body.plan_mode:
        claude_cmd += " --permission-mode plan"
    if body.session_id:
        claude_cmd += f" --resume {shlex.quote(body.session_id)}"
        if body.fork:
            claude_cmd += " --fork-session"
    if body.task_text:
        claude_cmd += f" {shlex.quote(body.task_text)}"

    # Wrap in bash -c with exec bash to keep terminal open
    inner_cmd = f"cd {shlex.quote(str(path))} && {claude_cmd}; exec bash"

    try:
        subprocess.Popen(
            [settings.terminal_cmd, "--title", win_title,
             "--", "bash", "-c", inner_cmd],
            start_new_session=True,
        )
    except FileNotFoundError:
        raise HTTPException(500, f"Terminal emulator '{settings.terminal_cmd}' not found")

    return {"status": "ok", "command": claude_cmd, "window_title": win_title, "path": str(path)}
