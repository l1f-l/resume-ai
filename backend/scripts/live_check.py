"""用真实 DeepSeek 跑一遍全链路（会消耗 token，默认不随 CI 执行）。

用法：python -m scripts.live_check
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ["MOCK_LLM"] = "0"          # 强制真实模型
os.environ["MOCK_STREAM_DELAY"] = "0"
os.environ["DB_PATH"] = "data/live_check.db"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

BASE = Path(__file__).resolve().parent.parent


def parse_sse(text: str):
    events = []
    for block in text.strip().split("\n\n"):
        ev, data = "message", {}
        for line in block.splitlines():
            if line.startswith("event:"):
                ev = line[6:].strip()
            elif line.startswith("data:"):
                data = json.loads(line[5:].strip() or "{}")
        events.append((ev, data))
    return events


def main() -> None:
    c = TestClient(app)
    print("health:", json.dumps(c.get("/api/health").json()["llm"], ensure_ascii=False))

    with open(BASE / "samples/sample_resume.pdf", "rb") as f:
        r = c.post(
            "/api/sessions",
            files={"file": ("sample_resume.pdf", f, "application/pdf")},
            data={"jd": (BASE / "samples/sample_jd.txt").read_text(encoding="utf-8")},
        )
    assert r.status_code == 200, r.text
    sid = r.json()["session_id"]
    print("结构化的方式:", r.json()["parse"]["structure"], "| 经历:", len(r.json()["resume"]["experiences"]))

    t0 = time.time()
    evs = parse_sse(c.post(f"/api/sessions/{sid}/analyze").text)
    dx = next(d for e, d in evs if e == "diagnosis")
    warn = [d["message"] for e, d in evs if e == "warning"]
    narrative = "".join(d["text"] for e, d in evs if e == "token")
    print(f"\n[诊断] {time.time()-t0:.1f}s score={dx['match_score']} 维度={len(dx['dimensions'])} 要求={len(dx['requirement_matches'])}")
    print("旁白:", narrative[:120])
    print("warning:", warn)
    print("q1:", dx["gap_questions"][0]["question"])
    assert not warn, "真实调用不应触发降级"

    answers = [
        "覆盖 320 万用户，带动 GMV 提升 28%，ROI 3.2",
        "触达转化率从 2.1% 提升到 3.4%，推送成本下降 18%",
        "提前 2 周上线，节省约 40 人天",
        "看板服务 60 多名运营，日均查看 300 次",
    ]
    answers = answers * 3  # 模型可能生成 3-5 条追问，答到进入重写为止
    for i, ans in enumerate(answers, 1):
        t0 = time.time()
        evs = parse_sse(c.post(f"/api/sessions/{sid}/chat", json={"message": ans}).text)
        kinds = [e for e, _ in evs]
        print(f"\n[追问 {i}] {time.time()-t0:.1f}s events={sorted(set(kinds))}")
        if "gap" in kinds:
            print("  下一问:", next(d for e, d in evs if e == "gap")["question"])
        if "rewrite" in kinds:
            rw = next(d for e, d in evs if e == "rewrite")
            print("  改写条数:", len(rw["bullets"]), "| 摘要:", rw["summary"]["optimized"][:80])
            for b in rw["bullets"][:3]:
                print("   -", b["optimized"][:80])
            break

    sess = c.get(f"/api/sessions/{sid}").json()
    print("\nstage:", sess["stage"], "| score:", sess["match_score"])
    bad = [b["optimized"] for e in sess["resume"]["experiences"] for b in e["bullets"]
           if b["optimized"].startswith(("负责", "参与", "协助"))]
    print("弱动词开头的条目:", len(bad))
    assert sess["stage"] == "OPTIMIZED", "未进入 OPTIMIZED"
    assert not bad, f"真实模型输出仍有弱动词: {bad}"

    t0 = time.time()
    evs = parse_sse(c.post(f"/api/sessions/{sid}/interview/start").text)
    qs = next(d for e, d in evs if e == "questions")["questions"]
    print(f"\n[出题] {time.time()-t0:.1f}s")
    for q in qs:
        print("  Q:", q["question"][:90])

    evs = parse_sse(
        c.post(
            f"/api/sessions/{sid}/interview/answer",
            json={"answer": "当时日活 200 万，我主导引导链路改版，先做分层调研再设计 3 档任务，"
                            "推动 A/B 实验，最终 7 日留存从 31% 提升到 39%，复盘后沉淀成 SOP。"},
        ).text
    )
    fb = next(d for e, d in evs if e == "feedback")
    print("\n[评分]", fb["score"], fb["verdict"][:60])
    print("  维度:", [(s["name"], s["score"]) for s in fb["scores"]])
    print("  改进:", fb["improvements"][:2])

    html = c.get(f"/api/sessions/{sid}/export?format=html")
    print("\nexport html:", html.status_code, len(html.content))
    print("health after:", json.dumps(c.get("/api/health").json()["llm"], ensure_ascii=False))


if __name__ == "__main__":
    main()
