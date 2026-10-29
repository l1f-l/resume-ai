"""投递闭环测试：前置校验、模拟发送、重复投递、状态流转、附件下载。"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.applications import ApplicationStore, ApplicationError
from app.config import settings
from app.jobs import job_store

from .conftest import parse_sse


def _optimized_session(client: TestClient, job_id: str = "job_017") -> str:
    """跑完「选岗 → 诊断 → 追问 → 重写」，得到可投递的会话。"""
    pdf = open("samples/sample_resume.pdf", "rb").read()
    resp = client.post(
        "/api/sessions",
        files={"file": ("resume.pdf", pdf, "application/pdf")},
        data={"jd": "", "job_id": job_id},
    )
    assert resp.status_code == 200, resp.text
    sid = resp.json()["session_id"]

    client.post(f"/api/sessions/{sid}/match/{job_id}")
    for i in range(6):
        r = client.post(f"/api/sessions/{sid}/chat", json={"message": f"覆盖 {200 + i * 30} 万用户，提升 {15 + i}%"})
        if "rewrite" in [e for e, _ in parse_sse(r.text)]:
            break
    summary = client.get(f"/api/sessions/{sid}").json()
    assert summary["stage"] in {"OPTIMIZED", "REVIEWED"}, summary["stage"]
    return sid


def test_apply_requires_optimized_resume(client: TestClient) -> None:
    pdf = open("samples/sample_resume.pdf", "rb").read()
    resp = client.post(
        "/api/sessions",
        files={"file": ("resume.pdf", pdf, "application/pdf")},
        data={"jd": "产品经理，增长方向"},
    )
    sid = resp.json()["session_id"]
    blocked = client.post("/api/applications", json={"session_id": sid, "job_id": "job_017"})
    assert blocked.status_code == 409
    assert "优化" in blocked.json()["detail"]


def test_apply_success_and_simulated_mail(client: TestClient) -> None:
    sid = _optimized_session(client, "job_017")
    resp = client.post(
        "/api/applications", json={"session_id": sid, "job_id": "job_017", "note": "内推"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    app = body["application"]
    assert app["status"] == "applied"
    assert app["status_label"] == "已投递"
    assert app["job_id"] == "job_017"
    assert app["email_subject"]

    # 未配置 SMTP 时应走模拟发送，且收件人固定为注册邮箱
    if not settings.smtp_ready:
        assert body["mail"]["status"] == "simulated"
        assert app["mail_status"] == "simulated"
    assert app["email_to"] == client.test_email  # type: ignore[attr-defined]

    # 附件留档存在
    assert app["attachment"]
    path = settings.data_dir.parent / app["attachment"]
    assert path.exists() and path.suffix == ".pdf"

    # 邮件正文是 HTML 且包含候选人信息
    assert "<p>" in body["mail"]["preview"]
    assert "张明" in body["mail"]["preview"]


def test_duplicate_application_rejected(client: TestClient) -> None:
    sid = _optimized_session(client, "job_018")
    first = client.post("/api/applications", json={"session_id": sid, "job_id": "job_018"})
    assert first.status_code == 200
    second = client.post("/api/applications", json={"session_id": sid, "job_id": "job_018"})
    assert second.status_code == 409


def test_status_flow_and_events(client: TestClient) -> None:
    sid = _optimized_session(client, "job_019")
    created = client.post("/api/applications", json={"session_id": sid, "job_id": "job_019"}).json()
    app_id = created["application"]["id"]

    moved = client.patch(
        f"/api/applications/{app_id}", json={"status": "interviewing", "note": "约面周五 14:00"}
    )
    assert moved.status_code == 200
    assert moved.json()["application"]["status_label"] == "已邀面"

    illegal = client.patch(f"/api/applications/{app_id}", json={"status": "applied"})
    assert illegal.status_code == 409

    events = client.get(f"/api/applications/{app_id}/events").json()["items"]
    assert [e["to_status"] for e in events] == ["applied", "interviewing"]
    assert events[-1]["note"].startswith("约面")


def test_board_summary_counts(client: TestClient) -> None:
    sid = _optimized_session(client, "job_020")
    client.post("/api/applications", json={"session_id": sid, "job_id": "job_020"})
    body = client.get("/api/applications").json()
    assert body["summary"]["total"] >= 1
    assert body["summary"]["applied"] >= 1
    assert all(item["status"] in {"applied", "interviewing", "offer", "rejected", "withdrawn"}
               for item in body["items"])


def test_download_attachment(client: TestClient) -> None:
    sid = _optimized_session(client, "job_021")
    app_id = client.post(
        "/api/applications", json={"session_id": sid, "job_id": "job_021"}
    ).json()["application"]["id"]
    resp = client.get(f"/api/applications/{app_id}/resume")
    assert resp.status_code == 200
    assert resp.content.startswith(b"%PDF")
    assert len(resp.content) > 5000


def test_apply_cross_user_blocked() -> None:
    from .conftest import make_user_client

    a = make_user_client("applicant-a")
    b = make_user_client("applicant-b")
    try:
        sid = _optimized_session(a, "job_022")
        assert b.post("/api/applications", json={"session_id": sid, "job_id": "job_022"}).status_code == 404
    finally:
        a.__exit__(None, None, None)
        b.__exit__(None, None, None)


def test_unknown_job_rejected(client: TestClient) -> None:
    sid = _optimized_session(client, "job_023")
    resp = client.post("/api/applications", json={"session_id": sid, "job_id": "job_999"})
    assert resp.status_code == 404


def test_store_transitions_unit(tmp_path: Path) -> None:
    store = ApplicationStore(tmp_path / "apps.db")
    row = store.create(user_id="u1", session_id="s1", job_id="job_001")
    assert row["status"] == "applied"

    with pytest.raises(ApplicationError):
        store.create(user_id="u1", session_id="s1", job_id="job_001")  # 重复投递

    store.update_status(row["id"], "u1", "interviewing")
    store.update_status(row["id"], "u1", "offer")
    with pytest.raises(ApplicationError):
        store.update_status(row["id"], "u1", "rejected")  # offer 是终态
