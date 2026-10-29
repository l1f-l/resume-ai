"""端到端测试：上传 → 诊断 → 追问 → STAR 重写 → 模拟面试 → 导出。

全程走真实 HTTP（FastAPI TestClient）+ 真实 SSE 解析，验证事件顺序与状态机。
LLM 走内置演示引擎，因此断言是确定的、可重复的。
"""
from __future__ import annotations

import json

import pytest

from tests.conftest import parse_sse, upload


# --------------------------------------------------------------------------- #
# 基础
# --------------------------------------------------------------------------- #
def test_health(client) -> None:
    data = client.get("/api/health").json()
    assert data["status"] == "ok"
    assert data["llm_mode"] == "mock"
    assert data["rag"]["templates"] >= 5


def test_upload_validations(client, pdf_bytes, jd_text) -> None:
    r = client.post(
        "/api/sessions",
        files={"file": ("a.txt", b"hello", "text/plain")},
        data={"jd": jd_text},
    )
    assert r.status_code == 400
    assert "PDF" in r.json()["detail"]

    r = client.post(
        "/api/sessions",
        files={"file": ("a.pdf", pdf_bytes, "application/pdf")},
        data={"jd": "   "},
    )
    assert r.status_code == 400
    assert "JD" in r.json()["detail"]

    r = client.post(
        "/api/sessions",
        files={"file": ("fake.pdf", b"%PDF-1.4 not really", "application/pdf")},
        data={"jd": jd_text},
    )
    assert r.status_code == 422


def test_upload_returns_structure(client, pdf_bytes, jd_text) -> None:
    r = client.post(
        "/api/sessions",
        files={"file": ("sample_resume.pdf", pdf_bytes, "application/pdf")},
        data={"jd": jd_text},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["stage"] == "PARSED"
    assert body["chars"] > 200
    assert body["parse"]["structure"] in {"heuristic", "llm"}
    resume = body["resume"]
    assert resume["basics"]["name"] == "张明"
    assert len(resume["experiences"]) == 2
    assert len(resume["experiences"][0]["bullets"]) == 4
    assert body["message"]


def test_unknown_session_404(client) -> None:
    assert client.get("/api/sessions/nope").status_code == 404
    assert client.post("/api/sessions/nope/analyze").status_code == 404


# --------------------------------------------------------------------------- #
# 诊断（SSE）
# --------------------------------------------------------------------------- #
def test_analyze_streams_diagnosis(client, pdf_bytes, jd_text) -> None:
    sid = upload(client, pdf_bytes, jd_text)
    resp = client.post(f"/api/sessions/{sid}/analyze")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")

    events = parse_sse(resp.text)
    kinds = [e for e, _ in events]

    # 协议：必须有 token 增量（打字机效果）、结构化诊断、状态推进、done
    assert kinds.count("token") >= 5, "流式输出没有分片，前端无法做打字机"
    assert "phase" in kinds and "diagnosis" in kinds and "done" in kinds
    assert kinds.index("diagnosis") < kinds.index("done")
    assert events[-1][0] == "done"

    # token 拼起来是一段完整中文点评
    narrative = "".join(d["text"] for e, d in events if e == "token")
    assert len(narrative) > 20

    dx = next(d for e, d in events if e == "diagnosis")
    assert 0 <= dx["match_score"] <= 100
    assert len(dx["dimensions"]) == 5
    assert 3 <= len(dx["requirement_matches"]) <= 8
    assert len(dx["gap_questions"]) >= 3
    gap = dx["gap_questions"][0]
    assert gap["id"] and gap["question"] and gap["bullet_id"]
    assert any(k in gap["question"] for k in ("多少", "几", "？"))
    # 追问必须瞄准「缺量化数据」的工作条目，不能问技能行
    assert "Axure" not in gap["question"]

    # RAG 命中
    assert dx["retrieved_templates"], "没有检索到优秀模板"
    assert dx["retrieved_templates"][0]["score"] > 0

    state = [d["stage"] for e, d in events if e == "state"]
    assert state == ["DIAGNOSED"]
    assert client.get(f"/api/sessions/{sid}").json()["stage"] == "DIAGNOSED"


def test_analyze_twice_conflicts(client, pdf_bytes, jd_text) -> None:
    sid = upload(client, pdf_bytes, jd_text)
    assert client.post(f"/api/sessions/{sid}/analyze").status_code == 200
    r = client.post(f"/api/sessions/{sid}/analyze")
    assert r.status_code == 409


def test_chat_before_diagnosis_conflicts(client, pdf_bytes, jd_text) -> None:
    sid = upload(client, pdf_bytes, jd_text)
    r = client.post(f"/api/sessions/{sid}/chat", json={"message": "你好"})
    assert r.status_code == 409


# --------------------------------------------------------------------------- #
# 追问 + STAR 重写
# --------------------------------------------------------------------------- #
def test_gap_clarify_then_rewrite(client, pdf_bytes, jd_text) -> None:
    sid = upload(client, pdf_bytes, jd_text)
    analyze = parse_sse(client.post(f"/api/sessions/{sid}/analyze").text)
    gaps = next(d for e, d in analyze if e == "diagnosis")["gap_questions"]
    total = len(gaps)

    seen_questions: list[str] = []
    answers = [
        "活动覆盖 320 万用户，带动 GMV 提升 28%",
        "触达转化率从 2.1% 提升到 3.4%",
        "提前 2 周上线，节省约 40 人天",
        "看板服务 60 多名运营，日均查看 300 次",
        "被 3 个团队复用",
    ]

    answers = answers[:total]
    for i, answer in enumerate(answers):
        resp = client.post(f"/api/sessions/{sid}/chat", json={"message": answer})
        assert resp.status_code == 200
        events = parse_sse(resp.text)
        kinds = [e for e, _ in events]

        if i < total - 1:
            assert "gap" in kinds, f"第 {i + 1} 轮应继续追问：{kinds}"
            assert "state" not in kinds
            q = next(d for e, d in events if e == "gap")
            assert q["question"] not in seen_questions, "追问重复了"
            seen_questions.append(q["question"])
            progress = next(d for e, d in events if e == "gaps")
            assert progress["answered"] == i + 1 and progress["total"] == total
            assert client.get(f"/api/sessions/{sid}").json()["stage"] == "CLARIFYING"
        else:
            # 最后一轮：先 READY_TO_REWRITE 再 OPTIMIZED
            states = [d["stage"] for e, d in events if e == "state"]
            assert states == ["READY_TO_REWRITE", "OPTIMIZED"]
            assert "rewrite" in kinds and "resume" in kinds

            payload = next(d for e, d in events if e == "rewrite")
            bullets = payload["bullets"]
            assert len(bullets) >= 8
            assert all(b["optimized"].strip() for b in bullets)
            assert all(b["id"] for b in bullets)

            # STAR 四要素齐全
            for b in bullets:
                star = b["star"]
                assert set(star) == {"situation", "task", "action", "result"}
                assert star["result"]

            # 关键词替换：不再以「负责/参与/协助」开头
            texts = [b["optimized"] for b in bullets]
            assert not any(t.startswith(("负责", "参与", "协助")) for t in texts)
            # 用户补充的数据被写进简历
            assert any("320 万" in t for t in texts)
            assert any("2.1%" in t and "3.4%" in t for t in texts)

            # 摘要与技能也重写了
            assert payload["summary"]["optimized"]
            assert any(k in payload["summary"]["optimized"] for k in ("年", "经验"))

    session = client.get(f"/api/sessions/{sid}").json()
    assert session["stage"] == "OPTIMIZED"
    assert session["answered_gaps"] == session["total_gaps"]
    assert session["resume"]["summary"]["optimized"]
    changed = [b for e in session["resume"]["experiences"] for b in e["bullets"] if b["changed"]]
    assert len(changed) >= 4


def test_skip_gap_still_reaches_rewrite(client, pdf_bytes, jd_text) -> None:
    sid = upload(client, pdf_bytes, jd_text)
    parse_sse(client.post(f"/api/sessions/{sid}/analyze").text)
    total = client.get(f"/api/sessions/{sid}").json()["total_gaps"]
    for _ in range(total):
        events = parse_sse(client.post(f"/api/sessions/{sid}/chat", json={"message": "跳过"}).text)
    assert "rewrite" in [e for e, _ in events]
    assert client.get(f"/api/sessions/{sid}").json()["stage"] == "OPTIMIZED"


def test_revision_after_optimize(client, pdf_bytes, jd_text) -> None:
    sid = upload(client, pdf_bytes, jd_text)
    from tests.conftest import optimize

    optimize(client, sid)
    before = client.get(f"/api/sessions/{sid}").json()["resume"]
    events = parse_sse(client.post(f"/api/sessions/{sid}/chat", json={"message": "帮我把每条再精简一点"}).text)
    assert "rewrite" in [e for e, _ in events]
    after = client.get(f"/api/sessions/{sid}").json()["resume"]
    assert after["summary"]["optimized"] == before["summary"]["optimized"]
    # 至少有部分条目变短
    lens_before = [len(b["optimized"]) for e in before["experiences"] for b in e["bullets"]]
    lens_after = [len(b["optimized"]) for e in after["experiences"] for b in e["bullets"]]
    assert sum(lens_after) < sum(lens_before)


# --------------------------------------------------------------------------- #
# 模拟面试
# --------------------------------------------------------------------------- #
def test_interview_requires_optimized_resume(client, pdf_bytes, jd_text) -> None:
    sid = upload(client, pdf_bytes, jd_text)
    client.post(f"/api/sessions/{sid}/analyze")
    assert client.post(f"/api/sessions/{sid}/interview/start").status_code == 409


def test_interview_full_round(client, pdf_bytes, jd_text) -> None:
    sid = upload(client, pdf_bytes, jd_text)
    from tests.conftest import optimize

    optimize(client, sid)

    start = parse_sse(client.post(f"/api/sessions/{sid}/interview/start").text)
    kinds = [e for e, _ in start]
    assert "questions" in kinds and "question" in kinds and "done" in kinds

    questions = next(d for e, d in start if e == "questions")["questions"]
    assert len(questions) == 5
    assert [q["index"] for q in questions] == [1, 2, 3, 4, 5]
    kinds_set = {q["kind"] for q in questions}
    assert {"behavioral", "technical", "situational", "pressure"} <= kinds_set
    assert all(q["key_points"] for q in questions)
    # 第一题必须引用简历内容
    assert "字节跳动" in questions[0]["question"] or len(questions[0]["question"]) > 15
    assert client.get(f"/api/sessions/{sid}").json()["stage"] == "INTERVIEWING"

    good_answer = (
        "当时业务日活 200 万，我负责引导链路改版，目标是提升 7 日留存。"
        "我先做了分层调研，再设计 3 档任务体系并推动 A/B 实验，"
        "最终 7 日留存从 31% 提升到 39%，复盘后把这套方法沉淀成了 SOP。"
    )
    scores: list[int] = []
    for i in range(5):
        resp = client.post(f"/api/sessions/{sid}/interview/answer", json={"answer": good_answer})
        assert resp.status_code == 200
        events = parse_sse(resp.text)
        fb = next(d for e, d in events if e == "feedback")
        assert 0 <= fb["score"] <= 100
        assert len(fb["scores"]) == 4
        assert fb["reference_answer"] and fb["improvements"]
        scores.append(fb["score"])

        if i < 4:
            assert "question" in [e for e, _ in events], "答完后应抛出下一题"
            assert "report" not in [e for e, _ in events]

    final = parse_sse(resp.text)
    report = next(d for e, d in final if e == "report")
    assert 0 <= report["overall"] <= 100
    assert report["level"] in {"优秀", "良好", "合格", "待提升"}
    assert len(report["advice"]) >= 3
    assert abs(report["overall"] - sum(scores) / 5) <= 3

    session = client.get(f"/api/sessions/{sid}").json()
    assert session["stage"] == "REVIEWED"
    assert session["interview_answered"] == 5
    assert session["report"]["overall"] == report["overall"]

    # 答完再提交 -> 409
    assert client.post(f"/api/sessions/{sid}/interview/answer", json={"answer": "再来一题"}).status_code == 409


def test_chat_during_interview_is_an_answer(client, pdf_bytes, jd_text) -> None:
    """面试阶段聊天框的输入必须被当作「作答」，而不是去改简历。"""
    sid = upload(client, pdf_bytes, jd_text)
    from tests.conftest import optimize

    optimize(client, sid)
    parse_sse(client.post(f"/api/sessions/{sid}/interview/start").text)

    events = parse_sse(
        client.post(
            f"/api/sessions/{sid}/chat",
            json={"answer": "", "message": "当时日活 200 万，我主导引导链路改版，7 日留存从 31% 提升到 39%。"},
        ).text
    )
    kinds = [e for e, _ in events]
    assert "feedback" in kinds, f"聊天入口没有触发评分：{kinds}"
    assert "error" not in kinds
    assert "rewrite" not in kinds  # 不能被当作改简历指令
    fb = next(d for e, d in events if e == "feedback")
    assert fb["score"] > 40
    assert next(d["stage"] for e, d in events if e == "session") == "INTERVIEWING"


def test_answer_quality_changes_score(client, pdf_bytes, jd_text) -> None:
    """弱回答必须显著低于强回答，避免「人人 80 分」。"""
    from app.schemas import InterviewQuestion
    from app.services.mock_engine import feedback

    q = InterviewQuestion(
        id="q1", index=1, question="讲讲这个项目",
        key_points=["项目背景与目标", "你个人的具体动作", "可验证的量化结果", "过程中的取舍"],
    )
    weak = feedback(q, "我做过用户增长活动，效果不错。")
    strong = feedback(
        q,
        "当时业务日活 200 万，我主导引导链路改版，先做分层调研再设计 3 档任务，"
        "推动 A/B 实验，最终 7 日留存从 31% 提升到 39%，复盘后沉淀成 SOP。",
    )
    assert weak.score < 55 < 70 <= strong.score
    assert weak.score < strong.score - 15


# --------------------------------------------------------------------------- #
# 导出
# --------------------------------------------------------------------------- #
def test_export_html_and_pdf(client, pdf_bytes, jd_text) -> None:
    sid = upload(client, pdf_bytes, jd_text)
    from tests.conftest import optimize

    optimize(client, sid)

    html = client.get(f"/api/sessions/{sid}/export?format=html")
    assert html.status_code == 200
    assert html.headers["content-type"].startswith("text/html")
    assert "attachment" in html.headers["content-disposition"]
    doc = html.text
    assert doc.startswith("<!DOCTYPE html>")
    assert "<style>" in doc and "@media print" in doc
    # 单文件：不能引用任何外部资源
    assert "http://" not in doc and "https://" not in doc
    assert "<link" not in doc and "<script" not in doc
    assert "张明" in doc

    pdf = client.get(f"/api/sessions/{sid}/export?format=pdf")
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF")
    assert len(pdf.content) > 3000

    from PyPDF2 import PdfReader
    import io

    reader = PdfReader(io.BytesIO(pdf.content))
    text = "\n".join(p.extract_text() or "" for p in reader.pages)
    assert "张明" in text

    bad = client.get(f"/api/sessions/{sid}/export?format=docx")
    assert bad.status_code == 400
    diff_pdf = client.get(f"/api/sessions/{sid}/export?format=pdf&variant=diff")
    assert diff_pdf.status_code == 400


def test_export_diff_variant(client, pdf_bytes, jd_text) -> None:
    sid = upload(client, pdf_bytes, jd_text)
    from tests.conftest import optimize

    optimize(client, sid)
    doc = client.get(f"/api/sessions/{sid}/export?format=html&variant=diff").text
    assert 'class="del"' in doc and 'class="ins"' in doc
    # 改前原文与改后文案都要出现
    assert "负责抖音电商的用户增长活动策划与落地" in doc
    assert "主导抖音电商" in doc


def test_preview_is_inline(client, pdf_bytes, jd_text) -> None:
    sid = upload(client, pdf_bytes, jd_text)
    r = client.get(f"/api/sessions/{sid}/preview")
    assert r.status_code == 200
    assert "attachment" not in (r.headers.get("content-disposition") or "")
    assert "<style>" in r.text
