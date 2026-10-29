"""会话持久化：重启后仍能通过 GET /api/sessions/{id} 恢复完整进度。"""
from __future__ import annotations

import sqlite3

import pytest

from app import api as api_module
from app.config import settings
from app.session import SessionStore
from tests.conftest import optimize, parse_sse, upload


def _restart(monkeypatch) -> SessionStore:
    """模拟进程重启：换一个全新的 Store 实例，只共享磁盘上的同一个 db 文件。"""
    fresh = SessionStore(str(settings.db_path))
    monkeypatch.setattr(api_module, "store", fresh)
    return fresh


def test_session_row_is_written_on_upload(client, pdf_bytes, jd_text, monkeypatch) -> None:
    sid = upload(client, pdf_bytes, jd_text)

    conn = sqlite3.connect(settings.db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM sessions WHERE id = ?", (sid,)).fetchone()
    conn.close()

    assert row is not None
    assert row["stage"] == "PARSED"
    assert row["jd_text"].startswith("用户增长产品经理")
    assert "张明" in row["resume_json"]
    assert row["updated_at"] >= row["created_at"]


def test_progress_survives_restart(client, pdf_bytes, jd_text, monkeypatch) -> None:
    sid = upload(client, pdf_bytes, jd_text)
    analyze = parse_sse(client.post(f"/api/sessions/{sid}/analyze").text)
    gaps = next(d for e, d in analyze if e == "diagnosis")["gap_questions"]
    assert gaps

    # 回答第一条追问，然后「重启」
    client.post(f"/api/sessions/{sid}/chat", json={"message": "覆盖 320 万用户，GMV 提升 28%"})
    _restart(monkeypatch)

    recovered = client.get(f"/api/sessions/{sid}")
    assert recovered.status_code == 200, "重启后会话丢失"
    data = recovered.json()

    assert data["stage"] == "CLARIFYING"
    assert data["id"] == sid
    assert data["answered_gaps"] == 1
    assert data["total_gaps"] == len(gaps)
    assert data["diagnosis"]["match_score"] > 0
    assert any(g["answered"] for g in data["diagnosis"]["gap_questions"])
    assert data["resume"]["basics"]["name"] == "张明"
    assert data["messages"], "聊天记录没有持久化"


def test_optimized_resume_survives_restart(client, pdf_bytes, jd_text, monkeypatch) -> None:
    sid = upload(client, pdf_bytes, jd_text)
    optimize(client, sid)

    before = client.get(f"/api/sessions/{sid}").json()
    assert before["stage"] == "OPTIMIZED"

    _restart(monkeypatch)
    after = client.get(f"/api/sessions/{sid}").json()

    assert after["stage"] == "OPTIMIZED"
    assert after["resume"]["summary"]["optimized"] == before["resume"]["summary"]["optimized"]
    changed_before = [b["optimized"] for e in before["resume"]["experiences"] for b in e["bullets"]]
    changed_after = [b["optimized"] for e in after["resume"]["experiences"] for b in e["bullets"]]
    assert changed_before == changed_after
    assert all(x.strip() for x in changed_after)


def test_interview_state_survives_restart(client, pdf_bytes, jd_text, monkeypatch) -> None:
    sid = upload(client, pdf_bytes, jd_text)
    optimize(client, sid)
    client.post(f"/api/sessions/{sid}/interview/start")
    client.post(
        f"/api/sessions/{sid}/interview/answer",
        json={"answer": "当时日活 200 万，我主导引导链路改版，7 日留存从 31% 提升到 39%。"},
    )

    _restart(monkeypatch)
    data = client.get(f"/api/sessions/{sid}").json()

    assert data["stage"] == "INTERVIEWING"
    assert len(data["questions"]) == 5
    assert data["interview_answered"] == 1
    assert data["feedbacks"][0]["score"] > 0
    # 继续作答仍然可用（游标没丢）
    resp = client.post(
        f"/api/sessions/{sid}/chat",
        json={"message": "第二题：我当时做了三层拆解，最终转化率提升 12%。"},
    )
    assert "feedback" in [e for e, _ in parse_sse(resp.text)]


def test_stage_history_is_recorded(client, pdf_bytes, jd_text) -> None:
    sid = upload(client, pdf_bytes, jd_text)
    client.post(f"/api/sessions/{sid}/analyze")

    conn = sqlite3.connect(settings.db_path)
    rows = conn.execute(
        "SELECT stage FROM stage_history WHERE session_id = ? ORDER BY id", (sid,)
    ).fetchall()
    conn.close()

    stages = [r[0] for r in rows]
    assert stages[0] == "NEW"
    assert "PARSED" in stages
    assert "DIAGNOSED" in stages
    assert stages == list(dict.fromkeys(stages)), "同一阶段不应重复记录"


def test_delete_removes_session(client, pdf_bytes, jd_text) -> None:
    sid = upload(client, pdf_bytes, jd_text)
    assert client.delete(f"/api/sessions/{sid}").json()["ok"] is True
    assert client.get(f"/api/sessions/{sid}").status_code == 404

    conn = sqlite3.connect(settings.db_path)
    n = conn.execute("SELECT COUNT(*) FROM sessions WHERE id = ?", (sid,)).fetchone()[0]
    conn.close()
    assert n == 0


def test_recent_sessions_list(client, pdf_bytes, jd_text) -> None:
    sid = upload(client, pdf_bytes, jd_text)
    items = client.get("/api/sessions?limit=5").json()["items"]
    assert any(i["id"] == sid for i in items)


def test_store_roundtrip_preserves_models(client, pdf_bytes, jd_text, monkeypatch) -> None:
    """直接测 Store：对象写进去、拿出来，领域模型字段不丢。"""
    sid = upload(client, pdf_bytes, jd_text)
    client.post(f"/api/sessions/{sid}/analyze")

    store = SessionStore(str(settings.db_path))
    s = store.get(sid)
    assert s is not None
    assert s.resume.experiences[0].company == "字节跳动"
    assert s.diagnosis and len(s.diagnosis.gap_questions) >= 3
    assert s.machine.stage == "DIAGNOSED"
    assert s.machine.history[0] == "NEW"
    assert s.qa_pairs == []


def test_unknown_id_returns_none(monkeypatch) -> None:
    store = SessionStore(str(settings.db_path))
    assert store.get("does-not-exist") is None


@pytest.mark.parametrize("field", ["resume_json", "messages_json"])
def test_json_columns_are_valid_json(client, pdf_bytes, jd_text, field) -> None:
    import json

    sid = upload(client, pdf_bytes, jd_text)
    conn = sqlite3.connect(settings.db_path)
    raw = conn.execute(f"SELECT {field} FROM sessions WHERE id = ?", (sid,)).fetchone()[0]
    conn.close()
    assert json.loads(raw) is not None
