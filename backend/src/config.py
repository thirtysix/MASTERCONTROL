from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings

_BASE_DIR = Path(__file__).resolve().parent.parent.parent  # MASTER_CONTROL/


class Settings(BaseSettings):
    # Base directory (MASTER_CONTROL/)
    base_dir: Path = _BASE_DIR

    # Projects directory (parent of all managed projects)
    projects_dir: Path = _BASE_DIR.parent  # defaults to 002.AI_projects/

    # Server
    host: str = "127.0.0.1"
    port: int = 8000

    # Database (SQLite cache — files are authoritative)
    db_path: Path = _BASE_DIR / "data" / "master_control.db"

    # Claude Code agent settings
    claude_model: str = "sonnet"
    max_budget_usd: float = 0.50

    # Terminal command
    terminal_cmd: str = "gnome-terminal"

    # Scanner settings
    skip_dirs: list[str] = ["backups", "models", "test", "__pycache__", "node_modules", ".git", ".venv"]
    sensitive_patterns: list[str] = [".env", "credentials", "secret", "token", ".pem", ".key"]

    # Universal base directories for all projects
    base_dirs: list[str] = [".mastercontrol", "docs", "scripts", "data", "logs", "tests"]

    model_config = {
        "env_prefix": "MASTERCTL_",
        "env_file": str(_BASE_DIR / ".env"),
    }


settings = Settings()
