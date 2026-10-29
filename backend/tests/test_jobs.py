"""岗位池测试：数量、结构、筛选、检索相关性、不编造。"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.jobs import job_store
from app.jobs_seed import build_jobs


def test_seed_generates_fifty_unique_jobs() -> None:
    jobs = build_jobs()
    assert len(jobs) == 50
    assert len({j["id"] for j in jobs}) == 50
    assert all(j["title"] and j["company"] and j["jd_text"] for j in jobs)
    assert all(j["salary_min"] > 0 and j["salary_max"] > j["salary_min"] for j in jobs)
    assert all(len(j["skills"]) >= 5 for j in jobs)
    # 高级版薪资应高于同级中级版
    for i in range(25):
        assert jobs[i + 25]["salary_max"] > jobs[i]["salary_max"]


def test_seed_is_persisted() -> None:
    assert job_store.count() == 50
    one = job_store.get("job_001")
    assert one is not None
    assert one["salary"].endswith("K")
    assert isinstance(one["skills"], list) and one["skills"]


def test_list_and_filters(client: TestClient) -> None:
    resp = client.get("/api/jobs?limit=10")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 50
    assert len(body["items"]) == 10

    filters = client.get("/api/jobs/filters").json()
    assert filters["total"] == 50
    assert filters["cities"] and filters["seniorities"]

    city = filters["cities"][0]
    scoped = client.get(f"/api/jobs?city={city}").json()
    assert scoped["total"] > 0
    assert all(item["city"] == city for item in scoped["items"])


def test_search_matches_title_or_skill(client: TestClient) -> None:
    resp = client.get("/api/jobs?q=React")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert items
    assert any("前端" in item["title"] for item in items)


def test_detail_and_404(client: TestClient) -> None:
    ok = client.get("/api/jobs/job_003")
    assert ok.status_code == 200
    assert ok.json()["id"] == "job_003"
    assert "【岗位职责】" in ok.json()["jd_text"]

    assert client.get("/api/jobs/job_999").status_code == 404


def test_vector_search_is_relevant() -> None:
    hits = job_store.search_vector("React TypeScript 前端 组件 性能优化 5 年", k=5)
    assert hits
    ids = [h[0] for h in hits]
    titles = [job_store.get(i)["title"] for i in ids]
    assert any("前端" in t for t in titles), titles


def test_all_results_come_from_pool() -> None:
    """检索结果 id 必须全部存在于岗位池（不编造）。"""
    pool = {j["id"] for j in job_store.all()}
    for _, (job_id, _score) in enumerate(job_store.search_vector("算法 推荐 深度学习", k=12)):
        assert job_id in pool
