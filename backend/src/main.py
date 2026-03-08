import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.requests import Request
from sqlmodel import Session

from src.config import settings
from src.db.database import engine, init_db
from src.process_registry import terminate_all
from src.routers import agents, projects, system, tasks
from src.services.project_scanner import scan_all

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

APP_DIR = Path(__file__).resolve().parent.parent.parent / "app"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: init DB and scan projects
    init_db()
    with Session(engine) as session:
        projects = scan_all(session)
        logger.info("Scanned %d projects", len(projects))
    yield

    # Shutdown: clean up running subprocesses
    logger.info("Shutting down MASTER CONTROL...")
    await terminate_all()

    # Remove PID file if it belongs to this process
    pid_file = settings.base_dir / "data" / "mastercontrol.pid"
    if pid_file.exists():
        try:
            stored_pid = int(pid_file.read_text().strip())
            if stored_pid == os.getpid():
                pid_file.unlink()
                logger.info("Removed PID file")
        except (ValueError, OSError):
            pass

    logger.info("Shutdown complete.")


app = FastAPI(title="MASTER CONTROL", lifespan=lifespan)

# CORS — localhost only
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:8000", "http://localhost:8000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(projects.router)
app.include_router(system.router)
app.include_router(tasks.router)
app.include_router(agents.router)

# Static files and templates
app.mount("/static", StaticFiles(directory=str(APP_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(APP_DIR / "templates"))


@app.get("/")
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})
