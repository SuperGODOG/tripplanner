"""FastAPI 主应用"""
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from ..config import get_settings, Settings
from .trip import router as trip_router
from .session import router as session_router

try:
    settings = get_settings()
except Exception:
    settings = Settings(llm_api_key="mock_key_for_test")

app = FastAPI(
    title="TripPlanner",
    version=settings.app_version,
    description="多智能体旅行规划系统 — 4 Agent + LangGraph + MCP",
    docs_url="/docs",
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(trip_router)
app.include_router(session_router)

# 静态文件（前端 MVP）
static_dir = Path(__file__).parent.parent.parent / "static"
if static_dir.exists():
    app.mount("/app", StaticFiles(directory=str(static_dir), html=True), name="static")


@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.get("/")
async def root():
    return {
        "name": "TripPlanner",
        "version": settings.app_version,
        "docs": "/docs",
        "app": "/app",
    }
