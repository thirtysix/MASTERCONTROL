"""Global registry of running subprocesses for graceful shutdown."""
from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)

_running: set[asyncio.subprocess.Process] = set()


def register(proc: asyncio.subprocess.Process) -> None:
    """Track a subprocess for cleanup on shutdown."""
    _running.add(proc)


def unregister(proc: asyncio.subprocess.Process) -> None:
    """Remove a subprocess from tracking (it finished normally)."""
    _running.discard(proc)


async def terminate_all() -> None:
    """Terminate all tracked subprocesses. Called during server shutdown."""
    for proc in list(_running):
        if proc.returncode is None:
            logger.info("Terminating subprocess PID %d", proc.pid)
            try:
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    logger.warning("Force-killing subprocess PID %d", proc.pid)
                    proc.kill()
            except ProcessLookupError:
                pass
    _running.clear()
