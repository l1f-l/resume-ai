"""用户仓储：注册、登录查询、公开信息脱敏。

只做数据访问与校验，不签发 token（那是 security.py 的事），避免职责混淆。
"""
from __future__ import annotations

import re
import time
import uuid

from .config import settings
from .db import Database
from .security import hash_password, password_problem, verify_password

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")

PUBLIC_FIELDS = ("id", "email", "display_name", "phone", "created_at", "last_login_at")


class UserExists(ValueError):
    pass


class UserStore:
    def __init__(self, db_path: str | None = None) -> None:
        self.db = Database(db_path or settings.db_path)

    # ------------------------------------------------------------------ #
    @staticmethod
    def public(user: dict | None) -> dict | None:
        if not user:
            return None
        return {k: user.get(k) for k in PUBLIC_FIELDS}

    def create(self, email: str, password: str, display_name: str = "") -> dict:
        email = (email or "").strip().lower()
        if not EMAIL_RE.match(email):
            raise ValueError("邮箱格式不正确")
        problem = password_problem(password)
        if problem:
            raise ValueError(problem)
        if self.get_by_email(email):
            raise UserExists("该邮箱已注册")

        uid = uuid.uuid4().hex[:12]
        now = time.time()
        self.db.execute(
            "INSERT INTO users (id, email, password_hash, display_name, phone, created_at) "
            "VALUES (?,?,?,?,?,?)",
            (uid, email, hash_password(password), (display_name or email.split("@")[0]).strip()[:40],
             "", now),
        )
        return self.get(uid) or {}

    def get(self, user_id: str) -> dict | None:
        return self.db.one("SELECT * FROM users WHERE id = ?", (user_id,))

    def get_by_email(self, email: str) -> dict | None:
        return self.db.one("SELECT * FROM users WHERE email = ?", ((email or "").strip().lower(),))

    def authenticate(self, email: str, password: str) -> dict | None:
        """凭据正确返回 user，否则 None（调用方统一抛 401，不暴露具体原因）。"""
        user = self.get_by_email(email)
        if not user or not verify_password(password, user["password_hash"]):
            return None
        self.db.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (time.time(), user["id"]))
        return self.get(user["id"])

    def count(self) -> int:
        return int(self.db.scalar("SELECT COUNT(*) FROM users") or 0)


user_store = UserStore()
