from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, SQLModel


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Project(SQLModel, table=True):
    id: str = Field(primary_key=True)
    name: str
    path: str
    description: str = ""
    tags: str = "[]"  # JSON array
    status: str = "active"  # active | idle | archived | new
    tech_stack: str = "[]"  # JSON array
    git_branch: Optional[str] = None
    git_last_commit: Optional[str] = None
    git_dirty: bool = False
    docker_status: Optional[str] = None  # running | stopped | none
    has_mastercontrol: bool = False
    missing_base_dirs: str = "[]"  # JSON array
    file_count: int = 0
    dir_size_mb: float = 0.0
    last_modified: Optional[datetime] = None
    scanned_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=_now)

    @property
    def tags_list(self) -> list[str]:
        return json.loads(self.tags)

    @property
    def tech_stack_list(self) -> list[str]:
        return json.loads(self.tech_stack)

    @property
    def primary_tag(self) -> str:
        tags = self.tags_list
        return tags[0] if tags else "other"


class Agent(SQLModel, table=True):
    id: str = Field(primary_key=True)
    name: str
    provider: str  # anthropic | openai | deepinfra
    model: str
    role: str = "developer"  # architect | developer | reviewer | ops
    status: str = "idle"  # idle | busy | error
    total_tokens_in: int = 0
    total_tokens_out: int = 0
    total_cost_usd: float = 0.0
    created_at: datetime = Field(default_factory=_now)


class Task(SQLModel, table=True):
    id: str = Field(primary_key=True)
    project_id: str = Field(foreign_key="project.id")
    agent_id: Optional[str] = Field(default=None, foreign_key="agent.id")
    title: str
    description: str = ""
    spec: str = ""
    risk_tier: int = 1  # 1=read-only, 2=modify, 3=create, 4=destructive
    level: int = 0
    status: str = "pending"  # pending | assigned | running | review | completed | failed
    files_owned: str = "[]"  # JSON array
    depends_on: str = "[]"  # JSON array of task IDs
    token_input: int = 0
    token_output: int = 0
    cost_usd: float = 0.0
    result: Optional[str] = None
    error: Optional[str] = None
    terminal_log: Optional[str] = None  # JSON array of SSE terminal events
    session_id: Optional[str] = None  # Claude Code session ID (interactive mode)
    created_at: datetime = Field(default_factory=_now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class AuditEntry(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    task_id: str = Field(foreign_key="task.id")
    agent_id: str
    action: str  # file_read | file_write | llm_call | command_exec
    detail: str = "{}"  # JSON
    timestamp: datetime = Field(default_factory=_now)


class FileLock(SQLModel, table=True):
    file_path: str = Field(primary_key=True)
    task_id: str = Field(foreign_key="task.id")
    agent_id: str
    acquired_at: datetime = Field(default_factory=_now)
