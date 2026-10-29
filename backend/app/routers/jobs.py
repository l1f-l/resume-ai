"""岗位广场路由：列表 / 详情 / 筛选项。登录后可访问，浏览本身不区分用户。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from ..jobs import job_store
from ..security import get_current_user

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("")
async def list_jobs(
    user: dict = Depends(get_current_user),
    q: str = "",
    city: str = "",
    seniority: str = "",
    limit: int = Query(default=20, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
) -> dict:
    items, total = job_store.list(
        q=q, city=city, seniority=seniority, limit=limit, offset=offset
    )
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/filters")
async def job_filters(user: dict = Depends(get_current_user)) -> dict:
    return job_store.filters()


@router.get("/{job_id}")
async def job_detail(job_id: str, user: dict = Depends(get_current_user)) -> dict:
    job = job_store.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="岗位不存在")
    return job
