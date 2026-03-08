from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from sqlmodel import Session, select, func

from src.db.database import get_session
from src.db.models import Agent, Project, Task
from src.services.project_scanner import scan_all
from src.services.session_service import find_matching_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/health")
def health():
    return {"status": "ok"}


@router.post("/scan")
def trigger_scan(session: Session = Depends(get_session)):
    projects = scan_all(session)
    return {"scanned": len(projects)}


@router.get("/stats")
def get_stats(session: Session = Depends(get_session)):
    total = session.exec(select(func.count(Project.id))).one()
    active = session.exec(
        select(func.count(Project.id)).where(Project.status == "active")
    ).one()
    agents_running = session.exec(
        select(func.count(Agent.id)).where(Agent.status == "busy")
    ).one()
    cost_total = session.exec(select(func.sum(Agent.total_cost_usd))).one() or 0.0
    return {
        "total_projects": total,
        "active_projects": active,
        "agents_running": agents_running,
        "cost_today_usd": round(cost_total, 4),
    }


@router.post("/backfill-sessions")
def backfill_sessions(session: Session = Depends(get_session)):
    """Link existing tasks to Claude Code sessions by matching prompts.

    Iterates through tasks that have no session_id, looks up the project path,
    and tries to find a matching session via first_prompt containment.
    """
    tasks = session.exec(
        select(Task).where(Task.session_id == None)  # noqa: E711
    ).all()

    matched = 0
    skipped = 0
    errors = []

    for task in tasks:
        project = session.get(Project, task.project_id)
        if not project:
            skipped += 1
            continue

        desc = task.description or task.title
        if not desc.strip():
            skipped += 1
            continue

        try:
            sid = find_matching_session(
                project.path,
                desc,
                task.created_at.isoformat() if task.created_at else None,
            )
        except Exception as e:
            logger.warning("Backfill error for task %s: %s", task.id, e)
            errors.append({"task_id": task.id, "error": str(e)})
            continue

        if sid:
            task.session_id = sid
            session.add(task)
            matched += 1
        else:
            skipped += 1

    session.commit()

    return {
        "total_checked": len(tasks),
        "matched": matched,
        "skipped": skipped,
        "errors": errors,
    }
