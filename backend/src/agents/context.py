"""Project context builder for Claude Code append prompts."""
from __future__ import annotations


def build_append_prompt(
    project_name: str,
    project_path: str,
    task_description: str,
    recent_tasks: list[dict] | None = None,
) -> str:
    """Build an append-system-prompt for Claude Code.

    This is appended to Claude Code's default prompt (which already handles
    CLAUDE.md discovery). Kept short — project architecture lives in CLAUDE.md.
    """
    prompt = f"""You are working on "{project_name}" ({project_path}).

Your task: {task_description}

Instructions:
- Refer to CLAUDE.md in the project root for architecture, key files, and prior task history.
- Do not re-explore the project structure if CLAUDE.md already covers it.
- Do not modify files outside the project directory.
- Provide a concise summary of what you did when the task is complete."""

    if recent_tasks:
        prompt += "\n\nRecent completed tasks on this project:"
        for t in recent_tasks[:5]:
            prompt += f"\n- [{t['date']}] {t['title']}: {t['summary']}"

    return prompt
