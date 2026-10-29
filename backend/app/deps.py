"""会话级依赖：鉴权用户 + 会话归属校验。

所有「按 session_id 操作」的接口都走 current_session，保证任何路径下
A 用户都拿不到 B 用户的简历（越权一律 404，不泄露会话是否存在）。
"""
from __future__ import annotations

from fastapi import Depends, HTTPException, Query

from .security import get_current_user
from .session import Session, store


def get_session(sid: str, user: dict) -> Session:
    s = store.get(sid)
    if not s or s.user_id != user["id"]:
        raise HTTPException(status_code=404, detail="会话不存在或已过期，请重新上传简历")
    return s


async def current_session(
    sid: str,
    user: dict = Depends(get_current_user),
) -> Session:
    return get_session(sid, user)


async def current_user_session(
    sid: str = Query(..., alias="sid"),
    user: dict = Depends(get_current_user),
) -> Session:
    """查询参数取 sid 的变体（导出/预览链接用，方便直接拼在 URL 上）。"""
    return get_session(sid, user)
