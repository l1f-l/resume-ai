"""FastAPI 入口。启动：uvicorn app.main:app --reload --port 8000"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import router
from .config import settings
from .jobs import job_store

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s | %(message)s",
)
log = logging.getLogger("main")


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


@app.get("/")
async def root() -> dict:
    return {
        "name": "ResumePilot API",
        "docs": "/docs",
        "health": "/api/health",
        "llm": settings.llm_label,
    }
