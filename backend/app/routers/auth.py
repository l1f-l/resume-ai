"""认证路由：注册 / 登录 / 当前用户 / 登出。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from ..config import settings
from ..security import create_token, get_current_user
from ..users import UserExists, user_store

router = APIRouter(prefix="/auth", tags=["auth"])


class RegisterIn(BaseModel):
    email: str = Field(min_length=3, max_length=120)
    password: str = Field(min_length=8, max_length=72)
    display_name: str = Field(default="", max_length=40)


class LoginIn(BaseModel):
    email: str = Field(min_length=3, max_length=120)
    password: str = Field(min_length=1, max_length=72)


def _issue(user: dict, response: Response) -> dict:
    token = create_token(user["id"])
    # 同时写 Cookie：iframe 预览与 <a> 下载无法自定义请求头，只能靠同源 Cookie 鉴权
    response.set_cookie(
        key=settings.jwt_cookie,
        value=token,
        max_age=settings.jwt_ttl_hours * 3600,
        httponly=True,
        samesite="lax",
        path="/",
    )
    return {"token": token, "user": user_store.public(user), "expires_in": settings.jwt_ttl_hours * 3600}


@router.post("/register")
async def register(body: RegisterIn, response: Response) -> dict:
    try:
        user = user_store.create(body.email, body.password, body.display_name)
    except UserExists as exc:
        raise HTTPException(status_code=409, detail="该邮箱已注册，请直接登录") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _issue(user, response)


@router.post("/login")
async def login(body: LoginIn, response: Response) -> dict:
    user = user_store.authenticate(body.email, body.password)
    if not user:
        raise HTTPException(status_code=401, detail="邮箱或密码不正确")
    return _issue(user, response)


@router.get("/me")
async def me(user: dict = Depends(get_current_user)) -> dict:
    return user_store.public(user) or {}


@router.post("/logout")
async def logout(response: Response) -> dict:
    response.delete_cookie(settings.jwt_cookie, path="/")
    return {"ok": True}
