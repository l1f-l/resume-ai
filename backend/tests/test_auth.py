"""用户体系与数据隔离测试。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.security import create_token, hash_password, verify_password
from app.users import UserStore

from .conftest import make_user_client


# --------------------------------------------------------------------------- #
# 密码与 token 单元层
# --------------------------------------------------------------------------- #
def test_password_hash_roundtrip() -> None:
    stored = hash_password("Passw0rd123")
    assert stored.startswith("pbkdf2_sha256$")
    assert verify_password("Passw0rd123", stored)
    assert not verify_password("Passw0rd124", stored)
    # 同一密码两次哈希应不同（随机 salt）
    assert hash_password("Passw0rd123") != stored


def test_password_hash_rejects_garbage() -> None:
    assert not verify_password("x", "not-a-hash")
    assert not verify_password("x", "md5$1$abc$def")


def test_token_roundtrip_and_tamper() -> None:
    from app.security import decode_token

    token = create_token("user_abc")
    assert decode_token(token) == "user_abc"

    with pytest.raises(Exception):
        decode_token(token[:-4] + "aaaa")

    expired = create_token("user_abc", ttl_hours=-1)
    with pytest.raises(Exception):
        decode_token(expired)


def test_user_store_validation(tmp_path) -> None:
    store = UserStore(tmp_path / "u.db")
    with pytest.raises(ValueError):
        store.create("not-an-email", "Passw0rd123")
    with pytest.raises(ValueError):
        store.create("a@b.com", "short")
    with pytest.raises(ValueError):
        store.create("a@b.com", "onlyletters")

    user = store.create("A@B.com", "Passw0rd123")
    assert user["email"] == "a@b.com"  # 统一小写
    assert store.get_by_email("A@B.COM")
    assert store.authenticate("a@b.com", "Passw0rd123")
    assert store.authenticate("a@b.com", "wrong-pass1") is None


# --------------------------------------------------------------------------- #
# HTTP 层
# --------------------------------------------------------------------------- #
def test_register_login_me(anon_client: TestClient) -> None:
    email = "flow-user@example.com"
    reg = anon_client.post(
        "/api/auth/register",
        json={"email": email, "password": "Passw0rd123", "display_name": "流程用户"},
    )
    assert reg.status_code in (200, 409), reg.text
    if reg.status_code == 200:
        assert reg.json()["user"]["email"] == email
        assert reg.json()["token"]

    login = anon_client.post(
        "/api/auth/login", json={"email": email, "password": "Passw0rd123"}
    )
    assert login.status_code == 200
    token = login.json()["token"]

    me = anon_client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["email"] == email
    assert "password_hash" not in me.json()


def test_duplicate_email_rejected(anon_client: TestClient) -> None:
    payload = {"email": "dup@example.com", "password": "Passw0rd123"}
    first = anon_client.post("/api/auth/register", json=payload)
    assert first.status_code in (200, 409)
    second = anon_client.post("/api/auth/register", json=payload)
    assert second.status_code == 409


def test_wrong_password_401(anon_client: TestClient) -> None:
    anon_client.post(
        "/api/auth/register",
        json={"email": "wrongpw@example.com", "password": "Passw0rd123"},
    )
    resp = anon_client.post(
        "/api/auth/login", json={"email": "wrongpw@example.com", "password": "Passw0rd999"}
    )
    assert resp.status_code == 401


def test_protected_endpoints_require_login(anon_client: TestClient) -> None:
    for method, url in [
        ("get", "/api/sessions"),
        ("get", "/api/jobs"),
        ("get", "/api/applications"),
        ("get", "/api/auth/me"),
    ]:
        resp = getattr(anon_client, method)(url)
        assert resp.status_code == 401, f"{url} 应要求登录"


def test_cross_user_isolation() -> None:
    """A 的会话，B 一律看不到（列表 / 详情 / 匹配 / 投递 全路径）。"""
    a = make_user_client("alice")
    b = make_user_client("bob")
    try:
        pdf = open("samples/sample_resume.pdf", "rb").read()
        created = a.post(
            "/api/sessions",
            files={"file": ("r.pdf", pdf, "application/pdf")},
            data={"jd": "Java 后端开发，要求熟悉 Spring Boot 与 MySQL"},
        )
        assert created.status_code == 200, created.text
        sid = created.json()["session_id"]

        assert b.get(f"/api/sessions/{sid}").status_code == 404
        assert b.post(f"/api/sessions/{sid}/match").status_code == 404
        assert b.post(f"/api/sessions/{sid}/match/job_001").status_code == 404
        assert b.post(f"/api/sessions/{sid}/analyze").status_code == 404
        assert b.delete(f"/api/sessions/{sid}").status_code == 404

        listed = b.get("/api/sessions").json()["items"]
        assert all(item["id"] != sid for item in listed)

        # 本人可访问
        assert a.get(f"/api/sessions/{sid}").status_code == 200
    finally:
        a.__exit__(None, None, None)
        b.__exit__(None, None, None)


def test_session_binds_to_user_id() -> None:
    """落库时 user_id 必须写死为当前登录用户。"""
    c = make_user_client("binder")
    try:
        pdf = open("samples/sample_resume.pdf", "rb").read()
        resp = c.post(
            "/api/sessions",
            files={"file": ("r.pdf", pdf, "application/pdf")},
            data={"jd": "产品经理，要求有增长与 A/B 实验经验"},
        )
        sid = resp.json()["session_id"]
        from app.session import store

        session = store.get(sid)
        assert session is not None
        assert session.user_id == c.test_user["id"]
    finally:
        c.__exit__(None, None, None)
