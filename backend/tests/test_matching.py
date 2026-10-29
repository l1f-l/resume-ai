"""双向匹配测试：Top3 白名单、雷达图结构、技能缺口不编造、阶段衔接。"""
from __future__ import annotations

import json

from fastapi.testclient import TestClient

from app.jobs import job_store
from app.schemas import MatchReport
from app.services import matching

from .conftest import parse_sse


DEFAULT_JD = "用户增长产品经理，要求 3-5 年经验，熟悉 A/B 实验、数据分析与需求管理"


def _upload(client: TestClient, jd: str = DEFAULT_JD, job_id: str = "") -> str:
    pdf = open("samples/sample_resume.pdf", "rb").read()
    data = {"jd": jd}
    if job_id:
        data["job_id"] = job_id
    resp = client.post(
        "/api/sessions",
        files={"file": ("resume.pdf", pdf, "application/pdf")},
        data=data,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["session_id"]


def test_recommend_returns_three_from_pool(client: TestClient) -> None:
    sid = _upload(client)
    resp = client.post(f"/api/sessions/{sid}/match")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    items = body["items"]
    assert len(items) == 3
    assert body["pool_size"] == 50

    pool = {j["id"] for j in job_store.all()}
    for item in items:
        assert item["job"]["id"] in pool, f"推荐了池外岗位：{item['job']['id']}"
        assert 0 <= item["score"] <= 100
        assert item["reason"]
    assert [i["rank"] for i in items] == [1, 2, 3]
    # 分数应递减
    assert items[0]["score"] >= items[1]["score"] >= items[2]["score"]


def test_recommendation_matches_resume_direction(client: TestClient) -> None:
    """样例简历是用户增长产品经理，Top3 不应跑偏到纯技术岗。"""
    sid = _upload(client)
    items = client.post(f"/api/sessions/{sid}/match").json()["items"]
    titles = " ".join(i["job"]["title"] for i in items)
    assert ("产品" in titles) or ("运营" in titles), titles


def test_hallucinated_job_ids_are_dropped() -> None:
    """白名单校验：模型编造的 job_id 必须被丢弃。"""
    job = job_store.get("job_001")
    cand_map = {"job_001": (0.8, job, ["Java"], ["Kafka"])}
    raw = {
        "items": [
            {"job_id": "job_999", "score": 99, "reason": "虚构岗位"},
            {"job_id": "job_001", "score": 88, "reason": "技能命中", "matched_skills": ["Java"]},
        ]
    }
    items = matching._parse_items(raw, cand_map)
    assert len(items) == 1
    assert items[0].job.id == "job_001"


def test_report_radar_shape_and_context(client: TestClient) -> None:
    sid = _upload(client, job_id="job_001")
    resp = client.post(f"/api/sessions/{sid}/match/job_001")
    assert resp.status_code == 200
    events = parse_sse(resp.text)
    names = [e for e, _ in events]
    assert "match_report" in names and "state" in names

    report = next(d for e, d in events if e == "match_report")
    assert report["job_id"] == "job_001"
    assert [r["dimension"] for r in report["radar"]] == [
        "技能覆盖", "经验深度", "项目复杂度", "行业相关", "学历资质", "薪资匹配",
    ]
    for r in report["radar"]:
        assert 0 <= r["score"] <= 100 and 0 <= r["benchmark"] <= 100

    # 技能缺口必须来自岗位池或 JD，不允许编造
    job = job_store.get("job_001")
    allowed = {s.lower().replace(" ", "") for s in job["skills"]}
    jd_norm = job["jd_text"].lower().replace(" ", "")
    for gap in report["skill_gap"]:
        key = gap["skill"].lower().replace(" ", "")
        assert key in allowed or key in jd_norm, f"编造了岗位没要求的技能：{gap['skill']}"

    assert len(report["gap_questions"]) >= 3


def test_report_drives_stage_and_session(client: TestClient) -> None:
    """报告落库后：session.job_id 写入、阶段推进到 DIAGNOSED、诊断可用于追问。"""
    sid = _upload(client)
    assert client.get(f"/api/sessions/{sid}").json()["stage"] == "PARSED"

    client.post(f"/api/sessions/{sid}/match/job_002")
    summary = client.get(f"/api/sessions/{sid}").json()
    assert summary["stage"] == "DIAGNOSED"
    assert summary["job_id"] == "job_002"
    assert summary["diagnosis"] is not None
    assert summary["diagnosis"]["match_score"] > 0
    assert summary["jd"].startswith("【岗位职责】")  # 岗位 JD 已灌入会话


def test_matches_endpoint_restores(client: TestClient) -> None:
    sid = _upload(client)
    client.post(f"/api/sessions/{sid}/match")
    body = client.get(f"/api/sessions/{sid}/matches").json()
    assert len(body["items"]) == 3
    assert all(item["job_id"].startswith("job_") for item in body["items"])


def test_reject_match_after_clarifying(client: TestClient) -> None:
    sid = _upload(client, job_id="job_003")
    client.post(f"/api/sessions/{sid}/match/job_003")
    # 追问一轮，进入 CLARIFYING
    client.post(f"/api/sessions/{sid}/chat", json={"message": "覆盖 300 万用户，提升 25%"})
    assert client.get(f"/api/sessions/{sid}").json()["stage"] in {"CLARIFYING", "READY_TO_REWRITE"}

    resp = client.post(f"/api/sessions/{sid}/match/job_004")
    assert resp.status_code == 409


def test_match_unknown_job_404(client: TestClient) -> None:
    sid = _upload(client)
    assert client.post(f"/api/sessions/{sid}/match/job_999").status_code == 404


def test_upload_with_job_id_fills_jd(client: TestClient) -> None:
    sid = _upload(client, job_id="job_010")
    summary = client.get(f"/api/sessions/{sid}").json()
    assert summary["job_id"] == "job_010"
    job = job_store.get("job_010")
    assert summary["jd"] == job["jd_text"]


def test_report_model_accepts_snapshot(client: TestClient) -> None:
    """报告快照可反序列化（前端刷新恢复依赖这个）。"""
    sid = _upload(client)
    client.post(f"/api/sessions/{sid}/match/job_005")
    from app.matches import match_store

    report = match_store.current_report(sid)
    assert isinstance(report, MatchReport)
    assert json.loads(report.model_dump_json())["job_id"] == "job_005"


def test_resume_feature_text_extracts_skills_and_projects() -> None:
    from app.schemas import Basics, Bullet, ProjectItem, ResumeDoc

    resume = ResumeDoc(
        basics=Basics(name="张三", headline="后端工程师", location="北京"),
        skills=Bullet(id="skills", original="Java, Spring Boot, MySQL"),
        projects=[ProjectItem(id="p1", name="订单系统", bullets=[Bullet(id="b1", original="重构下单链路")])],
    )
    text = matching.resume_feature_text(resume)
    assert "Java" in text and "订单系统" in text and "北京" in text
