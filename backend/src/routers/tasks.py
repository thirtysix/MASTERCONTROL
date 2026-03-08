"""Task CRUD, execution, and SSE streaming endpoints."""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select
from sse_starlette.sse import EventSourceResponse

from src.agents.context import build_append_prompt
from src.agents.coordinator import TaskCoordinator
from src.config import settings
from src.db.database import engine, get_session
from src.db.models import Agent, Project, Task
from src.services.memory_service import (
    ensure_claude_md,
    get_recent_task_summaries,
    update_claude_md_after_task,
)
from src.services.session_service import find_matching_session, read_session_as_terminal_log

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tasks", tags=["tasks"])

# In-memory stores for active task streams
_active_queues: dict[str, "_LoggingQueue"] = {}
_task_event_logs: dict[str, list[dict]] = {}


class _LoggingQueue:
    """Queue wrapper that records events at put-time, not get-time.

    This ensures terminal logs are captured regardless of whether an
    SSE client is connected, and avoids race conditions between the
    background task finishing and the SSE consumer draining the queue.
    """

    def __init__(self, task_id: str):
        self._inner: asyncio.Queue = asyncio.Queue()
        self._task_id = task_id

    async def put(self, item):
        if item is not None:
            _task_event_logs.setdefault(self._task_id, []).append(item)
        await self._inner.put(item)

    async def get(self):
        return await self._inner.get()


# ── Request / Response models ─────────────────────────────────


class TaskCreate(BaseModel):
    project_id: str
    title: str
    description: str = ""
    spec: str = ""
    risk_tier: int = 1


class TaskOut(BaseModel):
    id: str
    project_id: str
    agent_id: str | None
    title: str
    description: str
    spec: str
    risk_tier: int
    status: str
    token_input: int
    token_output: int
    cost_usd: float
    result: str | None
    error: str | None
    session_id: str | None
    created_at: str
    started_at: str | None
    completed_at: str | None

    @classmethod
    def from_db(cls, t: Task) -> TaskOut:
        return cls(
            id=t.id,
            project_id=t.project_id,
            agent_id=t.agent_id,
            title=t.title,
            description=t.description,
            spec=t.spec,
            risk_tier=t.risk_tier,
            status=t.status,
            token_input=t.token_input,
            token_output=t.token_output,
            cost_usd=t.cost_usd,
            result=t.result,
            error=t.error,
            session_id=t.session_id,
            created_at=t.created_at.isoformat(),
            started_at=t.started_at.isoformat() if t.started_at else None,
            completed_at=t.completed_at.isoformat() if t.completed_at else None,
        )


# ── CRUD ──────────────────────────────────────────────────────


@router.post("", response_model=TaskOut, status_code=201)
def create_task(body: TaskCreate, session: Session = Depends(get_session)):
    project = session.get(Project, body.project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    task = Task(
        id=str(uuid.uuid4())[:8],
        project_id=body.project_id,
        title=body.title,
        description=body.description,
        spec=body.spec,
        risk_tier=body.risk_tier,
    )
    session.add(task)
    session.commit()
    session.refresh(task)
    return TaskOut.from_db(task)


@router.get("", response_model=list[TaskOut])
def list_tasks(
    project_id: str | None = None,
    status: str | None = None,
    session: Session = Depends(get_session),
):
    query = select(Task).order_by(Task.created_at.desc())
    if project_id:
        query = query.where(Task.project_id == project_id)
    if status:
        query = query.where(Task.status == status)
    tasks = session.exec(query).all()
    return [TaskOut.from_db(t) for t in tasks]


@router.get("/{task_id}", response_model=TaskOut)
def get_task(task_id: str, session: Session = Depends(get_session)):
    task = session.get(Task, task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    return TaskOut.from_db(task)


@router.delete("/{task_id}", status_code=204)
def delete_task(task_id: str, session: Session = Depends(get_session)):
    task = session.get(Task, task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    if task.status == "running":
        raise HTTPException(409, "Cannot delete a running task")
    session.delete(task)
    session.commit()


class TaskStatusUpdate(BaseModel):
    status: str
    session_id: str | None = None


@router.patch("/{task_id}/status", response_model=TaskOut)
def update_task_status(task_id: str, body: TaskStatusUpdate, session: Session = Depends(get_session)):
    """Manually update a task's status (e.g. dispatched → completed)."""
    task = session.get(Task, task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    if task.status == "running":
        raise HTTPException(409, "Cannot manually update a running task")

    allowed = {"pending", "dispatched", "completed", "failed"}
    if body.status not in allowed:
        raise HTTPException(400, f"Status must be one of: {', '.join(sorted(allowed))}")

    task.status = body.status
    if body.session_id:
        task.session_id = body.session_id
    if body.status in ("completed", "failed"):
        task.completed_at = datetime.now(timezone.utc)
    session.add(task)
    session.commit()
    session.refresh(task)
    return TaskOut.from_db(task)


# ── Execution ─────────────────────────────────────────────────


@router.post("/{task_id}/execute")
async def execute_task(task_id: str):
    """Start executing a task. Returns immediately; progress streams via SSE."""
    with Session(engine) as session:
        task = session.get(Task, task_id)
        if not task:
            raise HTTPException(404, "Task not found")
        if task.status == "running":
            raise HTTPException(409, "Task already running")

        project = session.get(Project, task.project_id)
        if not project:
            raise HTTPException(404, "Project not found")

        project_path = project.path
        project_name = project.name

        # Auto-create agent
        agent_id = f"agent-{task_id}"
        agent = Agent(
            id=agent_id,
            name=f"Claude ({task.title[:30]})",
            provider="claude-code",
            model=settings.claude_model,
            role="developer",
            status="busy",
        )
        session.add(agent)

        task.agent_id = agent_id
        task.status = "running"
        task.started_at = datetime.now(timezone.utc)
        session.add(task)
        session.commit()

    # Create event queue and launch background coroutine
    queue = _LoggingQueue(task_id)
    _active_queues[task_id] = queue
    _task_event_logs[task_id] = []

    asyncio.create_task(
        _run_task_background(task_id, project_path, project_name, queue)
    )

    return {
        "status": "started",
        "task_id": task_id,
        "stream_url": f"/api/tasks/{task_id}/stream",
    }


async def _run_task_background(
    task_id: str, project_path: str, project_name: str, queue: asyncio.Queue
) -> None:
    """Background coroutine that runs Claude Code and updates DB."""
    from pathlib import Path

    try:
        coordinator = TaskCoordinator(task_id, Path(project_path), queue)

        with Session(engine) as session:
            task = session.get(Task, task_id)
            task_desc = task.description or task.title
            task_title = task.title

            # Ensure CLAUDE.md exists for this project
            project = session.get(Project, task.project_id)
            if project:
                try:
                    ensure_claude_md(project, session)
                except Exception:
                    logger.warning("Failed to generate CLAUDE.md for %s", project_name)

            # Build append prompt with recent task history
            recent_tasks = get_recent_task_summaries(task.project_id, session, limit=5)

        append_prompt = build_append_prompt(
            project_name, project_path, task_desc, recent_tasks
        )

        # Run Claude Code subprocess
        result = await coordinator.run(task_desc, project_name, append_prompt)

        # Collect terminal events for persistence
        terminal_events = _extract_terminal_events(task_id)

        # Update task and agent with results from Claude Code
        with Session(engine) as session:
            task = session.get(Task, task_id)
            task.status = "completed"
            task.result = result[:5000] if result else None
            task.token_input = coordinator.total_input_tokens
            task.token_output = coordinator.total_output_tokens
            task.cost_usd = coordinator.total_cost_usd
            task.terminal_log = json.dumps(terminal_events) if terminal_events else None
            task.completed_at = datetime.now(timezone.utc)
            session.add(task)

            agent = session.get(Agent, task.agent_id)
            if agent:
                agent.status = "idle"
                agent.total_tokens_in += coordinator.total_input_tokens
                agent.total_tokens_out += coordinator.total_output_tokens
                agent.total_cost_usd += coordinator.total_cost_usd
                session.add(agent)

            session.commit()

        # Update CLAUDE.md with completed task
        try:
            with Session(engine) as session:
                completed_task = session.get(Task, task_id)
                if completed_task:
                    update_claude_md_after_task(project_path, completed_task)
        except Exception:
            logger.warning("Failed to update CLAUDE.md after task %s", task_id)

    except Exception as e:
        logger.exception("Task %s failed", task_id)
        # Send error event to SSE stream so the frontend sees it
        await queue.put({
            "event": "error",
            "data": json.dumps({"error": str(e)}),
        })
        terminal_events = _extract_terminal_events(task_id)
        with Session(engine) as session:
            task = session.get(Task, task_id)
            if task:
                task.status = "failed"
                task.error = str(e)[:2000]
                task.terminal_log = json.dumps(terminal_events) if terminal_events else None
                task.completed_at = datetime.now(timezone.utc)
                session.add(task)

                agent = session.get(Agent, task.agent_id)
                if agent:
                    agent.status = "error"
                    session.add(agent)

                session.commit()

    finally:
        # Signal end of stream
        await queue.put(None)
        # Allow late SSE connections to drain
        await asyncio.sleep(5)
        _active_queues.pop(task_id, None)


# ── SSE Streaming ─────────────────────────────────────────────


@router.get("/{task_id}/stream")
async def stream_task(task_id: str):
    """SSE endpoint that streams execution events for a running task."""
    queue = _active_queues.get(task_id)
    if not queue:
        raise HTTPException(404, "No active stream for this task")

    async def event_generator():
        while True:
            event = await queue.get()
            if event is None:
                break
            yield event

    return EventSourceResponse(event_generator())


@router.get("/{task_id}/events")
def get_task_events(task_id: str):
    """Get the event log for a task (replay after completion)."""
    events = _task_event_logs.get(task_id, [])
    return {"task_id": task_id, "events": events}


@router.get("/{task_id}/terminal")
def get_task_terminal(task_id: str, session: Session = Depends(get_session)):
    """Get the terminal log for a completed task.

    First checks in-memory cache, then falls back to the DB.
    """
    # Check in-memory first (still around if server hasn't restarted)
    events = _task_event_logs.get(task_id)
    if events:
        terminal = _filter_terminal_events(events)
        return {"task_id": task_id, "lines": terminal}

    # Fall back to DB
    task = session.get(Task, task_id)
    if not task:
        raise HTTPException(404, "Task not found")

    if task.terminal_log:
        return {"task_id": task_id, "lines": json.loads(task.terminal_log)}

    # Fallback: read from Claude Code session JSONL (interactive mode)
    project = session.get(Project, task.project_id)
    if project:
        sid = task.session_id
        if not sid:
            sid = find_matching_session(
                project.path,
                task.description or task.title,
                task.created_at.isoformat() if task.created_at else None,
            )
            # Cache detected session_id for future lookups
            if sid:
                task.session_id = sid
                session.add(task)
                session.commit()

        if sid:
            lines = read_session_as_terminal_log(project.path, sid)
            if lines:
                return {"task_id": task_id, "lines": lines}

    return {"task_id": task_id, "lines": []}


def _filter_terminal_events(events: list[dict]) -> list[dict]:
    """Extract terminal-type events from the full event log."""
    lines = []
    for ev in events:
        if ev.get("event") != "terminal":
            continue
        try:
            data = json.loads(ev["data"]) if isinstance(ev.get("data"), str) else ev.get("data", {})
            lines.append({
                "line_type": data.get("line_type", "system"),
                "text": data.get("text", ""),
            })
        except (json.JSONDecodeError, KeyError):
            continue
    return lines


def _extract_terminal_events(task_id: str) -> list[dict]:
    """Extract terminal lines from in-memory event log for DB persistence."""
    events = _task_event_logs.get(task_id, [])
    return _filter_terminal_events(events)
