"""Standalone FastAPI entry point."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.routes import build_router
from app.mcp_server.server import create_mcp_server
from app.services.runtime import build_runtime

runtime = build_runtime()
mcp_http = create_mcp_server(runtime, http_path="/")


@asynccontextmanager
async def lifespan(app: FastAPI):
    runtime.reminders.start()
    try:
        async with mcp_http.session_manager.run():
            yield
    finally:
        runtime.close()


app = FastAPI(title="LearningFlow Agent", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type"],
)
app.include_router(build_router(runtime))
app.mount("/mcp", mcp_http.streamable_http_app(), name="mcp")
from pathlib import Path
frontend_dir = Path(__file__).resolve().parents[2] / "frontend"
app.mount("/ui", StaticFiles(directory=str(frontend_dir)), name="ui")


@app.get("/")
def root():
    from fastapi.responses import FileResponse
    return FileResponse(frontend_dir / "index.html")
