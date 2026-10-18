"""FastAPI application for Company Brain.

Per ARCHITECTURE.md Section 12, 13, 14, 16, 18b & Task B7:
- Lifespan: loads settings, connects to FalkorDB, runs schema.check_meta(),
  spawns MCP child over stdio and lists its tools.
- If FalkorDB is unreachable at startup or later, app starts; routes return 503 GRAPH_UNAVAILABLE
  and /api/health reports falkordb=false.
- Strict error handling: Every non-2xx response is formatted as ErrorResponse.
- Optional static file mounting for SPA demo deployment when SERVE_STATIC=true.
"""

from contextlib import asynccontextmanager
import logging
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from brain_api.exceptions import AppException, NotFoundException
from brain_api.mcp_manager import mcp_manager
from brain_api.routes import (
    chat,
    decisions,
    demo,
    graph,
    health,
    ingest,
    modules,
    reviews,
)
from brain_core.config import get_settings
from brain_core.db import get_db, get_graph
from brain_core.models import ErrorBody, ErrorResponse
from brain_core.schema import check_meta

logger = logging.getLogger("brain_api")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan: connects to FalkorDB, checks Meta, and spawns MCP child."""
    logger.info("Initializing Company Brain API...")
    cfg = get_settings()

    # 1. FalkorDB connection & Meta check
    try:
        db = get_db()
        db.connection.ping()
        g = get_graph()
        check_meta(graph=g, settings=cfg)
        logger.info("FalkorDB connection and Meta guard verified successfully.")
    except Exception as exc:
        logger.warning(
            f"FalkorDB connection or Meta check failed at startup (app starting in degraded state): {exc}"
        )

    # 2. Spawns child MCP process and lists its tools
    try:
        await mcp_manager.start()
        session = await mcp_manager.get_session()
        tools_list = await session.list_tools()
        names = [t.name for t in tools_list.tools]
        logger.info(f"Child MCP server process started with {len(names)} tools: {', '.join(names)}")
    except Exception as exc:
        logger.warning(f"Could not start child MCP process or list tools at startup: {exc}")

    yield

    logger.info("Shutting down Company Brain API...")
    await mcp_manager.stop()


def create_app() -> FastAPI:
    """Build and configure the FastAPI application instance."""
    app = FastAPI(
        title="Company Brain API",
        description="Graph-backed organizational intelligence agent and REST API.",
        version="1.0.0",
        lifespan=lifespan,
    )

    # --- Exception Handlers ---

    @app.exception_handler(AppException)
    async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=exc.to_response_model().model_dump(),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code_map = {
            400: "BAD_REQUEST",
            404: "NOT_FOUND",
            429: "RATE_LIMITED",
            500: "INTERNAL",
            502: "LLM_ERROR",
            503: "GRAPH_UNAVAILABLE",
        }
        err_code = code_map.get(exc.status_code, "INTERNAL")
        message = str(exc.detail) if exc.detail else "HTTP Error"
        error_resp = ErrorResponse(error=ErrorBody(code=err_code, message=message))  # type: ignore[arg-type]
        return JSONResponse(
            status_code=exc.status_code,
            content=error_resp.model_dump(),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Normalize 422 to 400 BAD_REQUEST per ARCHITECTURE.md Section 14
        details = "; ".join(f"{err.get('loc')}: {err.get('msg')}" for err in exc.errors())
        error_resp = ErrorResponse(error=ErrorBody(code="BAD_REQUEST", message=f"Validation failed: {details}"))
        return JSONResponse(
            status_code=400,
            content=error_resp.model_dump(),
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.error(f"Unhandled exception on {request.method} {request.url.path}: {exc}", exc_info=True)
        error_resp = ErrorResponse(error=ErrorBody(code="INTERNAL", message="An unexpected internal error occurred."))
        return JSONResponse(
            status_code=500,
            content=error_resp.model_dump(),
        )

    # --- Register API Routers ---
    app.include_router(health.router, prefix="/api")
    app.include_router(modules.router, prefix="/api")
    app.include_router(graph.router, prefix="/api")
    app.include_router(decisions.router, prefix="/api")
    app.include_router(reviews.router, prefix="/api")
    app.include_router(demo.router, prefix="/api")
    app.include_router(ingest.router, prefix="/api")
    app.include_router(chat.router, prefix="/api")

    # --- Optional Static Assets Serving for Production (Section 18b) ---
    cfg = get_settings()
    if cfg.SERVE_STATIC:
        static_dir = Path("/app/static")
        if not static_dir.exists():
            static_dir = Path(__file__).resolve().parent.parent.parent / "web" / "dist"
        if static_dir.exists() and static_dir.is_dir():
            index_file = static_dir / "index.html"
            assets_dir = static_dir / "assets"
            if assets_dir.exists() and assets_dir.is_dir():
                app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

            @app.get("/{full_path:path}", include_in_schema=False)
            async def spa_fallback(request: Request, full_path: str):
                if full_path.startswith("api/") or full_path == "api":
                    raise NotFoundException(f"API endpoint '/{full_path}' not found")
                target_file = static_dir / full_path
                if target_file.exists() and target_file.is_file():
                    return FileResponse(str(target_file))
                return FileResponse(str(index_file))

    return app


app = create_app()
