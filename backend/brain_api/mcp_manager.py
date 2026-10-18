"""Child MCP server process manager with auto-restart.

Per ARCHITECTURE.md Section 11, 14 & User Requirement:
- Spawns python -m mcp_server as a single child process via stdio transport.
- Auto-restarts the child process if it crashes or terminates unexpectedly.
- Background watchdog loop monitors process health during development.
- Provides thread-safe / async access to the active ClientSession and auto-retrying tool invocation.
"""

import asyncio
import logging
import os
from pathlib import Path
import sys
from typing import Any, Optional

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

logger = logging.getLogger("brain_api.mcp_manager")

BACKEND_DIR = Path(__file__).resolve().parent.parent


class MCPProcessManager:
    """Manages the lifecycle, auto-recovery, and watchdog of the stdio child MCP server."""

    def __init__(self) -> None:
        self._session: Optional[ClientSession] = None
        self._client_context = None
        self._lock = asyncio.Lock()
        self._is_running = False
        self._watchdog_task: Optional[asyncio.Task] = None

    def _get_process(self) -> Any:
        """Extract the child subprocess instance from the stdio context generator."""
        if not self._client_context:
            return None
        gen = getattr(self._client_context, "gen", None)
        if gen and getattr(gen, "ag_frame", None):
            return gen.ag_frame.f_locals.get("process")
        return None

    def is_healthy(self) -> bool:
        """Return True if MCP session is active and child process is running."""
        if not self._is_running or self._session is None:
            return False
        proc = self._get_process()
        if proc is not None and getattr(proc, "returncode", None) is not None:
            return False
        return True

    async def start(self) -> None:
        """Start the MCP child process and initialize ClientSession and watchdog."""
        async with self._lock:
            await self._start_locked()
        if self._watchdog_task is None or self._watchdog_task.done():
            self._watchdog_task = asyncio.create_task(self._watchdog_loop())

    async def _start_locked(self) -> None:
        if self.is_healthy():
            return

        # Ensure previous context/session is cleaned up safely
        await self._teardown_locked()

        env = os.environ.copy()
        python_path = str(BACKEND_DIR)
        if "PYTHONPATH" in env:
            env["PYTHONPATH"] = f"{python_path}{os.pathsep}{env['PYTHONPATH']}"
        else:
            env["PYTHONPATH"] = python_path

        server_params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "mcp_server"],
            env=env,
            cwd=str(BACKEND_DIR),
        )

        logger.info("Spawning child MCP server process (python -m mcp_server)...")
        try:
            self._client_context = stdio_client(server_params)
            read_stream, write_stream = await self._client_context.__aenter__()
            self._session = ClientSession(read_stream, write_stream)
            await self._session.__aenter__()
            await self._session.initialize()
            self._is_running = True
            proc = self._get_process()
            pid = getattr(proc, "pid", "unknown")
            logger.info(f"Child MCP server process started (PID={pid}) and initialized successfully.")
        except Exception as exc:
            await self._teardown_locked()
            logger.error(f"Failed to start child MCP server: {exc}", exc_info=True)
            raise

    async def _teardown_locked(self) -> None:
        """Internal teardown of existing session and transport context without hanging."""
        if self._session is not None:
            try:
                await asyncio.wait_for(self._session.__aexit__(None, None, None), timeout=1.5)
            except Exception as exc:
                logger.debug(f"Exception during MCP session exit: {exc}")
            finally:
                self._session = None

        if self._client_context is not None:
            try:
                await asyncio.wait_for(self._client_context.__aexit__(None, None, None), timeout=2.0)
            except Exception as exc:
                logger.debug(f"Exception during MCP transport exit: {exc}")
            finally:
                self._client_context = None

    async def _watchdog_loop(self) -> None:
        """Background watchdog to auto-restart the child MCP process if it crashes unexpectedly."""
        logger.info("Child MCP watchdog monitor started.")
        while self._is_running:
            try:
                await asyncio.sleep(1.0)
                if not self._is_running:
                    break

                if not self.is_healthy():
                    proc = self._get_process()
                    rc = getattr(proc, "returncode", "unknown")
                    logger.warning(
                        f"Child MCP server process crashed or exited unexpectedly (returncode={rc}). Auto-restarting..."
                    )
                    async with self._lock:
                        if self._is_running and not self.is_healthy():
                            await self._start_locked()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(f"Error in MCP watchdog loop: {exc}", exc_info=True)
        logger.info("Child MCP watchdog monitor stopped.")

    async def stop(self) -> None:
        """Gracefully shut down the child MCP server process and watchdog."""
        self._is_running = False
        if self._watchdog_task and not self._watchdog_task.done():
            self._watchdog_task.cancel()
            try:
                await self._watchdog_task
            except asyncio.CancelledError:
                pass
            self._watchdog_task = None

        async with self._lock:
            await self._teardown_locked()
            logger.info("Child MCP server process stopped.")

    async def get_session(self) -> ClientSession:
        """Retrieve active ClientSession, auto-restarting if terminated."""
        async with self._lock:
            if not self.is_healthy():
                logger.warning("MCP server is not healthy. Attempting auto-restart...")
                await self._start_locked()

            assert self._session is not None
            return self._session

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        """Invoke an MCP tool with automatic retry and auto-restart on child process failure."""
        for attempt in range(2):
            try:
                session = await self.get_session()
                return await session.call_tool(tool_name, arguments)
            except Exception as exc:
                logger.warning(f"MCP tool call '{tool_name}' failed on attempt {attempt + 1}: {exc}")
                if attempt == 0:
                    async with self._lock:
                        logger.warning("Auto-restarting crashed child MCP process before retrying tool call...")
                        await self._start_locked()
                else:
                    raise


# Global singleton instance
mcp_manager = MCPProcessManager()
