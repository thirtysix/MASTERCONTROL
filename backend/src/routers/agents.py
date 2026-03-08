"""Agent listing and stats endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import Session, select

from src.db.database import get_session
from src.db.models import Agent

router = APIRouter(prefix="/api/agents", tags=["agents"])


class AgentOut(BaseModel):
    id: str
    name: str
    provider: str
    model: str
    role: str
    status: str
    total_tokens_in: int
    total_tokens_out: int
    total_cost_usd: float
    created_at: str


@router.get("", response_model=list[AgentOut])
def list_agents(session: Session = Depends(get_session)):
    agents = session.exec(select(Agent).order_by(Agent.created_at.desc())).all()
    return [_to_out(a) for a in agents]


@router.get("/stats")
def agent_stats(session: Session = Depends(get_session)):
    agents = session.exec(select(Agent)).all()
    return {
        "total_agents": len(agents),
        "busy_agents": sum(1 for a in agents if a.status == "busy"),
        "total_tokens_in": sum(a.total_tokens_in for a in agents),
        "total_tokens_out": sum(a.total_tokens_out for a in agents),
        "total_cost_usd": round(sum(a.total_cost_usd for a in agents), 6),
    }


def _to_out(a: Agent) -> AgentOut:
    return AgentOut(
        id=a.id,
        name=a.name,
        provider=a.provider,
        model=a.model,
        role=a.role,
        status=a.status,
        total_tokens_in=a.total_tokens_in,
        total_tokens_out=a.total_tokens_out,
        total_cost_usd=a.total_cost_usd,
        created_at=a.created_at.isoformat(),
    )
