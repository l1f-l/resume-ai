"""鉴权：PBKDF2 密码哈希 + HS256 JWT + FastAPI 依赖注入。

取舍：
- 密码哈希用标准库 hashlib.pbkdf2_hmac（20 万轮），不引入 bcrypt/passlib 的编译依赖；
  存储格式 ``pbkdf2_sha256$迭代数$salt_b64$hash_b64``，自带版本前缀，将来换算法可平滑迁移。
- Token 采用「Bearer 头优先，Cookie 兜底」：前端 fetch 带 Authorization，
  页面级路由守卫靠 Cookie（middleware 读不到 localStorage）。
- 任何校验失败统一抛 401，不区分「用户不存在」和「密码错误」，避免账号枚举。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import time

import jwt
from fastapi import HTTPException, Request, status

from .config import settings

ALGO = "HS256"
PBKDF2_ITER = 200_000
MIN_PASSWORD = 8


# --------------------------------------------------------------------------- #
# 密码
# --------------------------------------------------------------------------- #
def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITER)
    return "pbkdf2_sha256${}${}${}".format(
        PBKDF2_ITER,
        base64.b64encode(salt).decode(),
        base64.b64encode(digest).decode(),
    )


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iter_s, salt_b64, hash_b64 = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iter_s))
        return hmac.compare_digest(digest, expected)
    except (ValueError, TypeError):
        return False


def password_problem(password: str) -> str | None:
    """返回错误文案，None 表示通过。"""
    if len(password) < MIN_PASSWORD:
        return f"密码至少 {MIN_PASSWORD} 位"
    if password.isdigit() or password.isalpha():
        return "密码需同时包含字母和数字"
    return None


# --------------------------------------------------------------------------- #
# JWT
# --------------------------------------------------------------------------- #
def create_token(user_id: str, *, ttl_hours: int | None = None) -> str:
    now = int(time.time())
    ttl = (ttl_hours if ttl_hours is not None else settings.jwt_ttl_hours) * 3600
    payload = {"sub": user_id, "iat": now, "exp": now + ttl, "typ": "access"}
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGO)


def decode_token(token: str) -> str:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[ALGO])
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录") from exc
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="登录凭证无效") from exc
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="登录凭证无效")
    return str(user_id)


def _extract_token(request: Request) -> str:
    header = request.headers.get("authorization") or ""
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    cookie = request.cookies.get(settings.jwt_cookie)
    if cookie:
        return cookie
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="请先登录",
        headers={"WWW-Authenticate": "Bearer"},
    )


# --------------------------------------------------------------------------- #
# 依赖
# --------------------------------------------------------------------------- #
async def get_current_user(request: Request) -> dict:
    """FastAPI 依赖：解析 token → 查用户 → 挂到 request.state。"""
    from .users import user_store  # noqa: PLC0415 - 避免循环导入

    user_id = decode_token(_extract_token(request))
    user = user_store.get(user_id)
    if not user:
        raise HTTPException(status_code=401, detail="账号不存在或已注销")
    request.state.user = user
    return user


async def optional_user(request: Request) -> dict | None:
    """公开接口可选登录（如岗位广场），无 token 返回 None 而不是 401。"""
    from .users import user_store  # noqa: PLC0415

    try:
        user_id = decode_token(_extract_token(request))
    except HTTPException:
        return None
    return user_store.get(user_id)
