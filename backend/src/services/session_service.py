"""Claude Code session discovery service.

Discovers existing Claude Code sessions for a project by reading
~/.claude/projects/<encoded-path>/sessions-index.json or falling back
to scanning .jsonl conversation files.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


def get_claude_projects_dir(project_path: str) -> Path:
    """Compute Claude Code's project config directory for a given project path.

    Claude Code encodes project paths by replacing /, ., _ with -
    Example: /home/user/path/to_project -> ~/.claude/projects/-home-user-path-to-project/
    """
    encoded = re.sub(r"[/._]", "-", project_path)
    if not encoded.startswith("-"):
        encoded = "-" + encoded
    return Path.home() / ".claude" / "projects" / encoded


def list_sessions(project_path: str) -> list[dict]:
    """List Claude Code sessions for a project.

    Returns list of dicts sorted by last_active descending:
        {id, name, first_prompt, last_active, message_count, is_sidechain}

    Tries sessions-index.json first, falls back to scanning .jsonl files.
    """
    claude_dir = get_claude_projects_dir(project_path)
    if not claude_dir.is_dir():
        return []

    index_file = claude_dir / "sessions-index.json"
    if index_file.is_file():
        return _parse_sessions_index(index_file)

    return _scan_jsonl_sessions(claude_dir)


def _parse_sessions_index(index_file: Path) -> list[dict]:
    """Parse sessions-index.json (Claude Code's native format)."""
    try:
        data = json.loads(index_file.read_text())
    except (json.JSONDecodeError, OSError):
        logger.warning("Failed to parse %s", index_file)
        return []

    sessions = []
    for entry in data.get("entries", []):
        session = {
            "id": entry.get("sessionId", ""),
            "name": entry.get("summary", "") or _truncate(entry.get("firstPrompt", ""), 80),
            "first_prompt": _truncate(entry.get("firstPrompt", ""), 120),
            "last_active": entry.get("modified", entry.get("created", "")),
            "message_count": entry.get("messageCount", 0),
            "is_sidechain": entry.get("isSidechain", False),
        }
        if session["id"]:
            sessions.append(session)

    sessions.sort(key=lambda s: s["last_active"], reverse=True)
    return sessions[:20]


def _scan_jsonl_sessions(claude_dir: Path) -> list[dict]:
    """Fallback: scan .jsonl files to discover sessions.

    Only includes sessions that contain actual conversation messages
    (user/assistant), skipping files that only have file-history-snapshot
    or other metadata entries.
    """
    sessions = []

    for jsonl_file in claude_dir.glob("*.jsonl"):
        session_id = jsonl_file.stem
        # Skip non-UUID filenames
        if len(session_id) < 32:
            continue

        first_prompt = ""
        has_conversation = False
        try:
            with open(jsonl_file) as f:
                for line in f:
                    obj = json.loads(line.strip())
                    msg_type = obj.get("type", "")
                    if msg_type in ("user", "assistant"):
                        has_conversation = True
                    if msg_type == "user" and not first_prompt:
                        msg = obj.get("message", {})
                        content = msg.get("content", "")
                        if isinstance(content, str):
                            first_prompt = content
                        elif isinstance(content, list):
                            for block in content:
                                if isinstance(block, dict) and block.get("type") == "text":
                                    first_prompt = block.get("text", "")
                                    break
                    if has_conversation and first_prompt:
                        break
        except (json.JSONDecodeError, OSError):
            pass

        if not has_conversation:
            continue

        try:
            stat = jsonl_file.stat()
            mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()
        except OSError:
            mtime = ""

        sessions.append({
            "id": session_id,
            "name": _truncate(first_prompt, 80) or session_id[:12],
            "first_prompt": _truncate(first_prompt, 120),
            "last_active": mtime,
            "message_count": 0,  # Unknown without full parse
            "is_sidechain": False,
        })

    sessions.sort(key=lambda s: s["last_active"], reverse=True)
    return sessions[:20]


def _truncate(text: str, length: int) -> str:
    """Truncate text to length, adding ellipsis if needed."""
    text = text.strip().replace("\n", " ")
    if len(text) > length:
        return text[:length - 3] + "..."
    return text


# ── Session JSONL → Terminal Log ─────────────────────────────────


def read_session_as_terminal_log(
    project_path: str, session_id: str, max_lines: int = 2000
) -> list[dict]:
    """Read a Claude Code session JSONL file and convert to terminal log format.

    Returns list of {"line_type": ..., "text": ...} dicts suitable for the
    terminal overlay, matching the format used by agentic mode.
    """
    claude_dir = get_claude_projects_dir(project_path)
    jsonl_file = claude_dir / f"{session_id}.jsonl"
    if not jsonl_file.is_file():
        return []

    lines: list[dict] = []
    try:
        with open(jsonl_file) as f:
            for raw_line in f:
                raw_line = raw_line.strip()
                if not raw_line:
                    continue
                try:
                    entry = json.loads(raw_line)
                except json.JSONDecodeError:
                    continue

                new_lines = _convert_jsonl_entry(entry)
                lines.extend(new_lines)

                if len(lines) >= max_lines:
                    lines = lines[:max_lines]
                    break
    except OSError:
        logger.warning("Failed to read session JSONL: %s", jsonl_file)
        return []

    return lines


def _convert_jsonl_entry(entry: dict) -> list[dict]:
    """Convert a single JSONL entry to terminal log lines."""
    entry_type = entry.get("type", "")

    # Skip metadata-only entries
    if entry_type in ("progress", "file-history-snapshot", "system"):
        return []

    message = entry.get("message", {})
    content = message.get("content", "")

    if entry_type == "user":
        return _convert_user_entry(content)
    elif entry_type == "assistant":
        return _convert_assistant_entry(content)

    return []


def _convert_user_entry(content) -> list[dict]:
    """Convert a user message entry."""
    if isinstance(content, str):
        if not content.strip():
            return []
        return [{"line_type": "system", "text": f"> {_truncate(content, 500)}"}]

    if not isinstance(content, list):
        return []

    lines = []
    for block in content:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type", "")

        if block_type == "text":
            text = block.get("text", "").strip()
            if text:
                lines.append({"line_type": "system", "text": f"> {_truncate(text, 500)}"})

        elif block_type == "tool_result":
            tool_id = block.get("tool_use_id", "")
            is_error = block.get("is_error", False)
            result_content = block.get("content", "")

            if isinstance(result_content, list):
                parts = []
                for part in result_content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        parts.append(part.get("text", ""))
                result_text = "\n".join(parts)
            elif isinstance(result_content, str):
                result_text = result_content
            else:
                result_text = str(result_content)

            line_type = "error" if is_error else "tool_result"
            lines.append({
                "line_type": line_type,
                "text": _truncate(result_text, 1000),
            })

    return lines


def _convert_assistant_entry(content) -> list[dict]:
    """Convert an assistant message entry."""
    if isinstance(content, str):
        if not content.strip():
            return []
        return [{"line_type": "assistant", "text": content}]

    if not isinstance(content, list):
        return []

    lines = []
    for block in content:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type", "")

        if block_type == "text":
            text = block.get("text", "").strip()
            if text:
                lines.append({"line_type": "assistant", "text": text})

        elif block_type == "tool_use":
            tool_name = block.get("name", "unknown")
            tool_input = block.get("input", {})
            summary = _summarize_tool_input(tool_name, tool_input)
            lines.append({
                "line_type": "tool_call",
                "text": f"{tool_name}({summary})",
            })

        elif block_type == "thinking":
            # Skip thinking blocks — too verbose
            pass

    return lines


def _summarize_tool_input(tool_name: str, tool_input: dict) -> str:
    """Create a short summary of tool input for display."""
    if tool_name in ("Read", "read_file"):
        return tool_input.get("file_path", "?")
    if tool_name in ("Write", "write_file"):
        path = tool_input.get("file_path", "?")
        return f"{path} ({len(tool_input.get('content', ''))} chars)"
    if tool_name in ("Edit", "edit_file"):
        return tool_input.get("file_path", "?")
    if tool_name in ("Bash",):
        cmd = tool_input.get("command", "?")
        return cmd[:80]
    if tool_name in ("Grep", "search_files"):
        return tool_input.get("pattern", "?")
    if tool_name in ("Glob", "list_files"):
        return tool_input.get("pattern", tool_input.get("path", "?"))
    for k, v in tool_input.items():
        return f"{k}: {str(v)[:60]}"
    return ""


def find_matching_session(
    project_path: str, task_description: str, task_created_at: str | None = None
) -> str | None:
    """Find a session whose first_prompt matches a task description.

    Matches by checking if task description is contained in session first_prompt
    or vice versa. Uses closest timestamp as tiebreaker.
    Returns session_id or None.
    """
    sessions = list_sessions(project_path)
    if not sessions:
        return None

    task_desc_lower = task_description.lower().replace("\n", " ").strip()
    if not task_desc_lower:
        return None

    candidates = []
    for s in sessions:
        prompt = (s.get("first_prompt") or "").lower().strip()
        if not prompt:
            continue
        # Strip truncation ellipsis so prefix matching works
        prompt_clean = prompt.rstrip(".")
        # Check containment in either direction
        if task_desc_lower in prompt or prompt_clean in task_desc_lower:
            candidates.append(s)

    if not candidates:
        return None

    if len(candidates) == 1:
        return candidates[0]["id"]

    # Tiebreaker: closest timestamp to task_created_at
    if task_created_at:
        try:
            task_dt = datetime.fromisoformat(task_created_at.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            return candidates[0]["id"]

        def time_distance(s):
            try:
                s_dt = datetime.fromisoformat(s.get("last_active", "").replace("Z", "+00:00"))
                return abs((s_dt - task_dt).total_seconds())
            except (ValueError, AttributeError):
                return float("inf")

        candidates.sort(key=time_distance)

    return candidates[0]["id"]
