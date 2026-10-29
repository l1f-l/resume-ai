import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# 必须在导入 app 之前固定运行模式：无网络、零延迟、独立数据库，保证 CI 可重复
_TMP = Path(tempfile.mkdtemp(prefix="resumepilot_test_"))
os.environ["MOCK_LLM"] = "1"
os.environ["MOCK_STREAM_DELAY"] = "0"
os.environ["RAG_ENABLED"] = "0"
os.environ["DB_PATH"] = str(_TMP / "sessions.db")
os.environ["OCR_ENABLED"] = "0"  # 需要 OCR 的用例自行打开

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

SAMPLE_PDF = ROOT / "samples" / "sample_resume.pdf"
SAMPLE_SCANNED = ROOT / "samples" / "scanned_resume.pdf"
SAMPLE_JD = ROOT / "samples" / "sample_jd.txt"


@pytest.fixture(scope="session")
def client() -> TestClient:
    """默认客户端已登录：Pro 版所有业务接口都要求鉴权，既有用例无需逐个加头。"""
    from uuid import uuid4

    with TestClient(app) as c:
        email = f"main-{uuid4().hex[:8]}@example.com"
        resp = c.post(
            "/api/auth/register",
            json={"email": email, "password": "Passw0rd123", "display_name": "主测试账号"},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        c.headers.update({"Authorization": f"Bearer {data['token']}"})
        c.test_user = data["user"]  # type: ignore[attr-defined]
        c.test_email = email  # type: ignore[attr-defined]
        yield c


def make_user_client(nick: str = "user") -> TestClient:
    """独立登录态的客户端，用于「未登录 401」与「跨用户隔离」测试。"""
    from uuid import uuid4

    c = TestClient(app)
    c.__enter__()
    email = f"{nick}-{uuid4().hex[:8]}@example.com"
    resp = c.post(
        "/api/auth/register",
        json={"email": email, "password": "Passw0rd123", "display_name": nick},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    c.headers.update({"Authorization": f"Bearer {data['token']}"})
    c.test_user = data["user"]  # type: ignore[attr-defined]
    c.test_email = email  # type: ignore[attr-defined]
    return c


@pytest.fixture()
def anon_client() -> TestClient:
    """未登录客户端：不带任何 Authorization。"""
    c = TestClient(app)
    c.__enter__()
    yield c
    c.__exit__(None, None, None)


@pytest.fixture(scope="session")
def pdf_bytes() -> bytes:
    if not SAMPLE_PDF.exists():
        pytest.fail("缺少 samples/sample_resume.pdf，请先运行 python -m scripts.make_sample")
    return SAMPLE_PDF.read_bytes()


@pytest.fixture(scope="session")
def scanned_pdf_bytes() -> bytes:
    if not SAMPLE_SCANNED.exists():
        pytest.skip("缺少 samples/scanned_resume.pdf，请先运行 python -m scripts.make_sample")
    return SAMPLE_SCANNED.read_bytes()


@pytest.fixture(scope="session")
def jd_text() -> str:
    return SAMPLE_JD.read_text(encoding="utf-8")


def parse_sse(raw: str) -> list[tuple[str, dict]]:
    """把 text/event-stream 解析成 [(event, data), ...]。"""
    import json

    events: list[tuple[str, dict]] = []
    for block in raw.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        event, data = "message", {}
        for line in block.splitlines():
            if line.startswith("event:"):
                event = line[len("event:"):].strip()
            elif line.startswith("data:"):
                payload = line[len("data:"):].strip()
                data = json.loads(payload) if payload else {}
        events.append((event, data))
    return events


def upload(client: TestClient, pdf_bytes: bytes, jd: str, name: str = "sample_resume.pdf") -> str:
    resp = client.post(
        "/api/sessions",
        files={"file": (name, pdf_bytes, "application/pdf")},
        data={"jd": jd},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["session_id"]


def optimize(client: TestClient, sid: str, answers: list[str] | None = None) -> None:
    """跑完诊断 + 全部追问，直到进入 OPTIMIZED。"""
    client.post(f"/api/sessions/{sid}/analyze")
    answers = answers or [
        "覆盖 320 万用户，带动 GMV 提升 28%",
        "触达转化率从 2.1% 提升到 3.4%",
        "提前 2 周上线，节省约 40 人天",
        "看板服务 60 多名运营，日均查看 300 次",
        "方案被 3 个团队复用",
    ]
    for i, ans in enumerate(answers):
        resp = client.post(f"/api/sessions/{sid}/chat", json={"message": ans})
        events = [e for e, _ in parse_sse(resp.text)]
        if "rewrite" in events:
            return
        assert "gap" in events, f"第 {i} 轮既没有追问也没有重写：{events}"
    raise AssertionError("追问轮次用尽仍未触发重写")
