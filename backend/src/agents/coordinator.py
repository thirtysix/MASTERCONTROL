"""Task coordinator — spawns Claude Code CLI and streams results.

Runs `claude -p` as a subprocess, parses the stream-json JSONL output,
and emits SSE events via an asyncio.Queue for the dashboard frontend.
"""
from __future__ import annotations

import asyncio
import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path

from src.config import settings
from src.process_registry import register, unregister

logger = logging.getLogger(__name__)

# SSE event type constants
EVENT_THINKING = "thinking"
EVENT_TOOL_CALL = "tool_call"
EVENT_TOOL_RESULT = "tool_result"
EVENT_COMPLETE = "complete"
EVENT_ERROR = "error"
EVENT_USAGE = "usage"
EVENT_TERMINAL = "terminal"


class TaskCoordinator:
    """Orchestrates a single task by running Claude Code as a subprocess."""

    def __init__(
        self, task_id: str, project_dir: Path, event_queue: asyncio.Queue
    ):
        self.task_id = task_id
        self.project_dir = project_dir
        self.event_queue = event_queue
        self.process: asyncio.subprocess.Process | None = None

        # Populated from the final "result" event
        self.total_cost_usd: float = 0.0
        self.total_input_tokens: int = 0
        self.total_output_tokens: int = 0
        self.num_turns: int = 0

        # Verify claude is installed
        if not shutil.which("claude"):
            raise RuntimeError(
                "Claude Code CLI not found. Install it with: npm install -g @anthropic-ai/claude-code"
            )

    async def emit(self, event_type: str, data: dict) -> None:
        """Push an SSE event onto the queue."""
        await self.event_queue.put({
            "event": event_type,
            "data": json.dumps({
                "task_id": self.task_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                **data,
            }),
        })

    async def run(self, task_description: str, project_name: str, append_prompt: str | None = None) -> str:
        """Spawn claude -p and stream results back via SSE.

        Returns the final text output from Claude Code.
        """
        cmd = [
            "claude", "-p", task_description,
            "--output-format", "stream-json",
            "--verbose",
            "--permission-mode", "bypassPermissions",
            "--no-session-persistence",
            "--max-budget-usd", str(settings.max_budget_usd),
            "--model", settings.claude_model,
        ]
        if append_prompt:
            cmd += ["--append-system-prompt", append_prompt]

        logger.info("Task %s: spawning claude in %s", self.task_id, self.project_dir)

        self.process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(self.project_dir),
        )
        register(self.process)

        result_text = ""

        try:
            async for raw_line in self.process.stdout:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line:
                    continue

                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    logger.warning("Non-JSON line from claude: %s", line[:200])
                    continue

                await self._handle_event(event)

                # Extract final result data
                if event.get("type") == "result":
                    result_text = event.get("result", "")
                    self.total_cost_usd = event.get("total_cost_usd", 0.0)
                    self.num_turns = event.get("num_turns", 0)
                    usage = event.get("usage", {})
                    self.total_input_tokens = (
                        usage.get("input_tokens", 0)
                        + usage.get("cache_read_input_tokens", 0)
                        + usage.get("cache_creation_input_tokens", 0)
                    )
                    self.total_output_tokens = usage.get("output_tokens", 0)

        except Exception:
            logger.exception("Error reading claude stdout for task %s", self.task_id)
            raise
        finally:
            # Read any stderr
            if self.process.stderr:
                stderr_data = await self.process.stderr.read()
                if stderr_data:
                    stderr_text = stderr_data.decode("utf-8", errors="replace").strip()
                    if stderr_text:
                        logger.warning("Claude stderr for task %s: %s", self.task_id, stderr_text[:500])

            await self.process.wait()
            unregister(self.process)

            if self.process.returncode != 0 and not result_text:
                raise RuntimeError(
                    f"Claude Code exited with code {self.process.returncode}"
                )

        return result_text

    async def _handle_event(self, event: dict) -> None:
        """Parse a JSONL event from Claude Code and emit SSE events."""
        event_type = event.get("type", "")

        if event_type == "system":
            # Initialization event
            model = event.get("model", "unknown")
            tools = event.get("tools", [])
            version = event.get("claude_code_version", "?")
            await self.emit(EVENT_TERMINAL, {
                "line_type": "system",
                "text": f"Claude Code v{version} | model: {model} | {len(tools)} tools",
            })

        elif event_type == "assistant":
            message = event.get("message", {})
            content_blocks = message.get("content", [])

            for block in content_blocks:
                if not isinstance(block, dict):
                    continue

                block_type = block.get("type", "")

                if block_type == "text":
                    text = block.get("text", "")
                    # Compact event for Panel 2 execution log
                    await self.emit(EVENT_THINKING, {
                        "text": text[:300],
                    })
                    # Full text for terminal overlay
                    await self.emit(EVENT_TERMINAL, {
                        "line_type": "assistant",
                        "text": text,
                    })

                elif block_type == "tool_use":
                    tool_name = block.get("name", "?")
                    tool_input = block.get("input", {})
                    if not isinstance(tool_input, dict):
                        tool_input = {}
                    input_summary = _summarize_tool_input(tool_name, tool_input)

                    # Compact event for Panel 2
                    await self.emit(EVENT_TOOL_CALL, {
                        "tool": tool_name,
                        "input": tool_input,
                        "risk_tier": 0,
                    })
                    # Terminal line
                    await self.emit(EVENT_TERMINAL, {
                        "line_type": "tool_call",
                        "text": f"{tool_name}({input_summary})",
                    })

            # Emit usage if present
            usage = message.get("usage") or {}
            if usage and isinstance(usage, dict):
                input_tok = (
                    usage.get("input_tokens", 0)
                    + usage.get("cache_read_input_tokens", 0)
                    + usage.get("cache_creation_input_tokens", 0)
                )
                output_tok = usage.get("output_tokens", 0)
                await self.emit(EVENT_USAGE, {
                    "input_tokens": input_tok,
                    "output_tokens": output_tok,
                })

        elif event_type == "user":
            # Tool result
            message = event.get("message", {})
            content_blocks = message.get("content", [])
            tool_result_extra = event.get("tool_use_result") or {}
            if not isinstance(tool_result_extra, dict):
                tool_result_extra = {}

            for block in content_blocks:
                if not isinstance(block, dict):
                    continue
                if block.get("type") != "tool_result":
                    continue

                is_error = block.get("is_error", False)
                content = block.get("content", "")

                # content can be a string or a list of content blocks
                if isinstance(content, list):
                    content = " ".join(
                        b.get("text", str(b)) if isinstance(b, dict) else str(b)
                        for b in content
                    )
                elif not isinstance(content, str):
                    content = str(content)

                # Use stdout/stderr from extra field if available
                stdout = tool_result_extra.get("stdout", "") or ""
                stderr = tool_result_extra.get("stderr", "") or ""
                display_text = stdout or content

                # Compact event
                await self.emit(EVENT_TOOL_RESULT, {
                    "tool": "result",
                    "success": not is_error,
                })
                # Terminal line — show output (truncated for large results)
                preview = display_text[:1000]
                if len(display_text) > 1000:
                    preview += f"\n... ({len(display_text)} chars total)"
                if stderr:
                    preview += f"\nstderr: {stderr[:300]}"

                await self.emit(EVENT_TERMINAL, {
                    "line_type": "tool_result" if not is_error else "error",
                    "text": preview,
                })

        elif event_type == "result":
            subtype = event.get("subtype", "")
            is_error = event.get("is_error", False)
            result_text = event.get("result", "")
            duration = event.get("duration_ms", 0)
            cost = event.get("total_cost_usd", 0)
            turns = event.get("num_turns", 0)

            if is_error:
                await self.emit(EVENT_ERROR, {"error": result_text})
                await self.emit(EVENT_TERMINAL, {
                    "line_type": "error",
                    "text": f"Failed: {result_text}",
                })
            else:
                await self.emit(EVENT_COMPLETE, {"result": result_text[:500]})
                duration_s = duration / 1000 if duration else 0
                await self.emit(EVENT_TERMINAL, {
                    "line_type": "result",
                    "text": f"Done in {duration_s:.1f}s | {turns} turns | ${cost:.4f}",
                })


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
    # Fallback: show first key=value
    for k, v in tool_input.items():
        return f"{k}: {str(v)[:60]}"
    return ""
