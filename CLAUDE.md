# Master Control

Multi-project, multi-agent control panel for AI/research projects.

## Architecture
- **Backend**: FastAPI + SQLModel/SQLite + Pydantic Settings (`MASTERCTL_` prefix)
- **Frontend**: Vanilla JS + D3.js (no framework), served as static files by FastAPI
- **Agent**: Claude Code CLI subprocess (`claude -p --output-format stream-json --verbose`)
- **Data authority**: `.mastercontrol/` files per project are authoritative; SQLite is a rebuild-able cache

## Running
```bash
cd backend && uvicorn src.main:app --reload    # development
./mastercontrol.sh start                        # production (background)
```

## Key directories
- `backend/src/` — FastAPI app, routers, services, agents, DB models
- `app/` — Frontend (templates/index.html, static/*.js, static/style.css)
- `.mastercontrol/` — Project manifest (single source of truth)
