"""真实 API 的错误分类、重试与降级（不联网，全部用假的 _stream_once 模拟）。"""
from __future__ import annotations

import pytest

from app.config import settings
from app.services.agents import ResumeAgent
from app.services.llm import LLM, LLMError
from app.services.pdf_parser import parse_pdf, structure_heuristic


@pytest.fixture
def live(monkeypatch):
    """把运行模式切成「真实模型」，但不会真的发请求。"""
    monkeypatch.setattr(settings, "mock_mode_raw", "0")
    monkeypatch.setattr(settings, "llm_retries", 2)
    monkeypatch.setattr(settings, "llm_backoff", 0)
    monkeypatch.setattr(settings, "degrade_after_failures", 3)
    llm = LLM()
    llm.reset()
    yield llm
    llm.reset()


def _raise(status: int, kind: str, retryable: bool = False, text: str = "boom"):
    async def _gen(*args, **kwargs):
        raise LLMError(text, status=status, kind=kind, retryable=retryable)
        yield  # pragma: no cover

    return _gen


@pytest.mark.asyncio
async def test_402_degrades_immediately_and_message_is_actionable(live, monkeypatch) -> None:
    monkeypatch.setattr(live, "_stream_once", _raise(402, "balance"))

    with pytest.raises(LLMError) as exc:
        await live.complete([{"role": "user", "content": "hi"}])

    assert "余额不足" in str(exc.value)
    assert live.degraded is True
    assert live.is_mock is True
    assert live.mode == "degraded"

    msg = live.friendly(exc.value)
    assert "余额不足" in msg
    assert "演练引擎" in msg


@pytest.mark.asyncio
async def test_401_is_fatal_without_retry(live, monkeypatch) -> None:
    calls = {"n": 0}

    async def _gen(*args, **kwargs):
        calls["n"] += 1
        raise LLMError("bad key", status=401, kind="auth")
        yield  # pragma: no cover

    monkeypatch.setattr(live, "_stream_once", _gen)
    with pytest.raises(LLMError):
        await live.complete([{"role": "user", "content": "hi"}])

    assert calls["n"] == 1, "401 不应重试"
    assert live.degraded is True
    assert "API Key" in live.friendly(LLMError("", status=401, kind="auth"))


@pytest.mark.asyncio
async def test_429_retries_then_succeeds(live, monkeypatch) -> None:
    calls = {"n": 0}

    async def _gen(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise LLMError("rate", status=429, kind="rate", retryable=True)
        yield "可用"

    monkeypatch.setattr(live, "_stream_once", _gen)
    out = await live.complete([{"role": "user", "content": "hi"}])

    assert out == "可用"
    assert calls["n"] == 2
    assert live.degraded is False, "偶发限流恢复后不应整体降级"


@pytest.mark.asyncio
async def test_429_exhausted_then_degrades(live, monkeypatch) -> None:
    calls = {"n": 0}

    async def _gen(*args, **kwargs):
        calls["n"] += 1
        raise LLMError("rate", status=429, kind="rate", retryable=True)
        yield  # pragma: no cover

    monkeypatch.setattr(live, "_stream_once", _gen)
    with pytest.raises(LLMError) as exc:
        await live.complete([{"role": "user", "content": "hi"}])

    assert calls["n"] == 3, "1 次原始请求 + 2 次重试"
    assert "已自动重试" in live.friendly(exc.value)


@pytest.mark.asyncio
async def test_timeout_is_retryable(live, monkeypatch) -> None:
    calls = {"n": 0}

    async def _gen(*args, **kwargs):
        calls["n"] += 1
        raise LLMError("timeout", kind="timeout", retryable=True)
        yield  # pragma: no cover

    monkeypatch.setattr(live, "_stream_once", _gen)
    with pytest.raises(LLMError) as exc:
        await live.complete([{"role": "user", "content": "hi"}])
    assert calls["n"] == 3
    assert "超时" in str(exc.value)


@pytest.mark.asyncio
async def test_three_failures_trip_the_breaker(live, monkeypatch) -> None:
    monkeypatch.setattr(live, "_stream_once", _raise(500, "server", retryable=True))

    assert live.degraded is False
    with pytest.raises(LLMError):
        await live.complete([{"role": "user", "content": "hi"}])
    # 第 1 次请求内部已重试 2 次 → fail_streak 达到 3 → 熔断
    assert live.fail_streak >= 3
    assert live.degraded is True

    # 熔断后不再发请求，直接走 mock
    assert live.is_mock is True


@pytest.mark.asyncio
async def test_diagnose_falls_back_with_warning(live, monkeypatch, pdf_bytes, jd_text) -> None:
    monkeypatch.setattr(live, "_stream_once", _raise(402, "balance"))
    resume = structure_heuristic(parse_pdf(pdf_bytes).text)

    agent = ResumeAgent(live)
    events = [e async for e in agent.diagnose(resume, jd_text, pdf_text(pdf_bytes))]

    kinds = [k for k, _ in events]
    assert "warning" in kinds
    assert "diagnosis" in kinds, "降级后仍然要给出诊断"
    assert "state" in kinds

    warning = next(d["message"] for k, d in events if k == "warning")
    assert "余额不足" in warning and "演练引擎" in warning

    dx = next(d for k, d in events if k == "diagnosis")
    assert 0 <= dx["match_score"] <= 100
    assert len(dx["gap_questions"]) >= 3


@pytest.mark.asyncio
async def test_rewrite_falls_back_and_still_covers_all_bullets(live, monkeypatch, pdf_bytes, jd_text) -> None:
    monkeypatch.setattr(live, "_stream_once", _raise(401, "auth"))
    resume = structure_heuristic(parse_pdf(pdf_bytes).text)

    agent = ResumeAgent(live)
    events = [
        e
        async for e in agent.rewrite(
            resume,
            {"b1": "覆盖 320 万用户，GMV 提升 28%"},
            jd_text,
            {"问": "覆盖 320 万用户，GMV 提升 28%"},
        )
    ]

    assert "warning" in [k for k, _ in events]
    payload = next(d for k, d in events if k == "rewrite")
    ids = {b["id"] for b in payload["bullets"]}
    expected = {b.id for b in resume.all_bullets() if b.original.strip()}
    assert expected <= ids, "降级改写也不能漏条"
    assert any("320 万" in b["optimized"] for b in payload["bullets"])


@pytest.mark.asyncio
async def test_after_degrade_all_calls_use_mock(live, monkeypatch, pdf_bytes, jd_text) -> None:
    monkeypatch.setattr(live, "_stream_once", _raise(402, "balance"))
    resume = structure_heuristic(parse_pdf(pdf_bytes).text)

    agent = ResumeAgent(live)
    [e async for e in agent.diagnose(resume, jd_text, "text")]

    calls = {"n": 0}

    async def _should_not_be_called(*a, **k):
        calls["n"] += 1
        yield "x"

    monkeypatch.setattr(live, "_stream_once", _should_not_be_called)
    events = [e async for e in agent.diagnose(resume, jd_text, "text")]
    assert calls["n"] == 0
    assert "warning" not in [k for k, _ in events]


def pdf_text(data: bytes) -> str:
    return parse_pdf(data).text


@pytest.mark.asyncio
async def test_live_rewrite_happy_path(live, monkeypatch, pdf_bytes, jd_text) -> None:
    """真实模式下：先流式旁白，再返回 JSON；不能出现「重复解析」之类的低级错误。"""
    import json

    resume = structure_heuristic(parse_pdf(pdf_bytes).text)
    bullets = [b for b in resume.all_bullets() if b.original.strip()]
    body = {
        "summary": {"optimized": "5 年用户增长产品经验，主导活动覆盖 320 万用户，GMV 提升 28%。"},
        "skills": {"optimized": "用户增长 · SQL · A/B 实验 · 数据分析"},
        "bullets": [
            {
                "id": b.id,
                "optimized": "主导增长项目，覆盖 320 万用户，GMV 提升 28%。",
                "star": {"situation": "增长停滞", "task": "拉动 GMV", "action": "分层激励", "result": "GMV +28%"},
                "metrics": ["320 万", "28%"],
            }
            for b in bullets
        ],
    }
    calls = {"n": 0}

    async def _gen(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:  # 旁白
            for piece in ["改完了。", "重点补了量化。"]:
                yield piece
        else:  # 结构化 JSON
            yield json.dumps(body, ensure_ascii=False)

    monkeypatch.setattr(live, "_stream_once", _gen)

    events = [e async for e in ResumeAgent(live).rewrite(resume, {}, jd_text, {})]
    kinds = [k for k, _ in events]
    assert "warning" not in kinds
    payload = next(d for k, d in events if k == "rewrite")
    assert len(payload["bullets"]) == len(bullets)
    assert payload["bullets"][0]["metrics"] == ["320 万", "28%"]
    assert "320 万" in payload["summary"]["optimized"]


@pytest.mark.asyncio
async def test_live_diagnose_happy_path(live, monkeypatch, pdf_bytes, jd_text) -> None:
    import json

    resume = structure_heuristic(parse_pdf(pdf_bytes).text)
    body = {
        "match_score": 71,
        "verdict": "方向匹配，缺少量化。",
        "dimensions": [{"name": n, "score": 70, "comment": "证据"} for n in ("技能匹配", "经历深度", "量化成果", "表达结构", "岗位贴合")],
        "requirement_matches": [{"requirement": "5 年以上经验", "evidence": "5 年", "level": "strong", "suggestion": "-"}],
        "missing_keywords": ["CAC"],
        "strengths": ["方向对口"],
        "risks": ["缺数据"],
        "gap_questions": [{"id": "g1", "topic": "幅度", "question": "留存从多少到多少？", "why": "补结果", "bullet_id": "b1"}],
    }
    calls = {"n": 0}

    async def _gen(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            yield "方向和岗位是匹配的。"
        else:
            yield json.dumps(body, ensure_ascii=False)

    monkeypatch.setattr(live, "_stream_once", _gen)
    events = [e async for e in ResumeAgent(live).diagnose(resume, jd_text, parse_pdf(pdf_bytes).text)]
    kinds = [k for k, _ in events]
    assert "warning" not in kinds
    dx = next(d for k, d in events if k == "diagnosis")
    assert dx["match_score"] == 71
    assert len(dx["gap_questions"]) >= 3, "模型给少了要自动补齐"
    assert dx["retrieved_templates"], "RAG 模板应该被挂上"


def test_merge_skills_never_invents(pdf_bytes) -> None:
    """技能行由代码合并：不新增原简历没有的技能，不重复，不拆坏 A/B。"""
    from app.services.agents import _merge_skills

    resume = structure_heuristic(parse_pdf(pdf_bytes).text)
    merged = _merge_skills(resume, "用户增长 SQL A/B 实验 数据分析", "A/B测试 · uxure · Axure · SQL · SQL")

    assert "uxure" not in merged, "模型编造的技能不能进简历"
    assert merged.count("SQL") == 1
    assert "A/B测试" in merged, "A/B 不能被拆成 A 和 B测试"
    assert merged.count("A/B") == 1, "A/B 与 A/B测试 不应重复出现"
    origin = {x.strip().lower() for x in resume.skills.original.replace("，", ",").split(",")}
    for item in merged.split(" · "):
        assert item.lower() in origin or item in {"用户增长", "SQL", "A/B测试", "数据分析"}, item
