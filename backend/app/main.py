"""FastAPI 入口。启动：uvicorn app.main:app --reload --port 8001"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .api import router
from .config import settings
from .jobs import job_store

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s | %(message)s",
)
log = logging.getLogger("main")

ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = Path(__file__).resolve().parents[1]


def _static_dir() -> Path | None:
    """前端静态导出产物目录。

    按「可能被部署成什么形态」依次探测，命中即用：
    - STATIC_DIR 环境变量（最优先，便于平台侧覆盖）
    - backend/web：随源码一起上传的产物目录（本项目的部署方式）
    - ./web：进程工作目录就是 backend 时
    - backend/web、frontend/out：本地 monorepo 布局
    都不存在时退化为纯 API 服务，本地双端口开发不受影响。
    """
    raw = os.getenv("STATIC_DIR", "").strip()
    candidates = [
        Path(raw) if raw else None,
        BACKEND_DIR / "web",
        Path.cwd() / "web",
        ROOT / "backend" / "web",
        ROOT / "frontend" / "out",
    ]
    for c in candidates:
        if c and (c / "index.html").is_file():
            return c
    return None


@asynccontextmanager
async def lifespan(_: FastAPI):
    """启动时幂等导入岗位池（50 条）并构建 Chroma 索引。"""
    try:
        count = job_store.seed()
        log.info("job pool ready: %d jobs, index=%s", count, job_store.backend)
    except Exception:  # noqa: BLE001 - 岗位池故障不应阻塞主流程
        log.exception("job pool seed failed")
    yield


app = FastAPI(
    title="ResumePilot Pro API",
    description="智能求职全链路平台（FastAPI + DeepSeek + RAG + JWT）",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)

app.include_router(router)

# 单端口部署：前端静态产物挂在根路径，/api/* 与 /docs 仍由 FastAPI 处理。
# 必须最后挂载，让已注册的 API 路由先匹配。
_web = _static_dir()
if _web:
    app.mount("/", StaticFiles(directory=_web, html=True), name="web")
    log.info("serving frontend from %s", _web)
else:

    @app.get("/")
    async def root() -> dict:  # pragma: no cover - 仅纯 API 模式
        return {
            "name": "ResumePilot API",
            "docs": "/docs",
            "health": "/api/health",
            "llm": settings.llm_label,
        }
