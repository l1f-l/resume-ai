"""用本机 Chrome 跑一遍真实 UI 流程并截图（开发自检，不参与交付构建）。

用法：
  python -m scripts.ui_shots                          # 默认文字版简历 + 当前后端的模型模式
  UI_PDF=scanned_resume.pdf python -m scripts.ui_shots  # 扫描件（验证 OCR 徽标）
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from playwright.sync_api import sync_playwright  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "samples" / "shots"
URL = os.getenv("UI_URL", "http://127.0.0.1:3000")
API = os.getenv("UI_API", "http://127.0.0.1:8000")
PDF = os.getenv("UI_PDF", "sample_resume.pdf")
TAG = os.getenv("UI_TAG", "")
JD = (ROOT / "samples" / "sample_jd.txt").read_text(encoding="utf-8")

ANSWERS = [
    "活动覆盖 320 万用户，带动 GMV 提升 28%，ROI 做到 3.2",
    "触达转化率从 2.1% 提升到 3.4%，推送成本下降 18%",
    "上线提前 2 周，节省约 40 人天",
    "看板服务 60 多名运营，日均查看 300 次",
    "方案被 3 个团队复用，月均节省 12 人天",
]


def session_state(page) -> dict:
    sid = page.evaluate("localStorage.getItem('rp_sid')")
    if not sid:
        return {}
    return page.request.get(f"{API}/api/sessions/{sid}").json()


def wait_idle(page, timeout: float = 120) -> None:
    """等 SSE 流结束、输入框可用，避免把回答丢在 streaming 期间。"""
    end = time.time() + timeout
    while time.time() < end:
        try:
            if page.locator("textarea").last.is_enabled():
                return
        except Exception:  # noqa: BLE001
            pass
        page.wait_for_timeout(300)


def wait_answered(page, expected: int, timeout: float = 180) -> dict:
    """等后台真正记下一份回答（stage 不会每题都变，不能用 stage 判断）。"""
    end = time.time() + timeout
    st: dict = {}
    while time.time() < end:
        st = session_state(page)
        if st.get("interview_answered", 0) >= expected:
            wait_idle(page, timeout=60)
            return st
        page.wait_for_timeout(600)
    return st


def wait_stage(page, wanted: set[str], timeout: float = 120) -> dict:
    end = time.time() + timeout
    st = {}
    while time.time() < end:
        st = session_state(page)
        if st.get("stage") in wanted:
            return st
        page.wait_for_timeout(700)
    raise TimeoutError(f"等待阶段 {wanted} 超时，当前 {st.get('stage')}")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=1)
        errors: list[str] = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(str(e)))

        page.goto(URL, wait_until="domcontentloaded")
        page.wait_for_timeout(600)
        page.screenshot(path=str(OUT / f"01_home{TAG}.png"), full_page=True)
        print("home ok")

        page.set_input_files('input[type="file"]', str(ROOT / "samples" / PDF))
        page.fill("textarea", JD)
        page.click("text=开始诊断")
        st = wait_stage(page, {"DIAGNOSED"}, timeout=150)
        page.wait_for_timeout(1200)
        page.screenshot(path=str(OUT / f"02_diagnosis{TAG}.png"), full_page=True)
        print("diagnosis ok:", st.get("stage"), "score", st.get("match_score"), "gaps", st.get("total_gaps"))

        for i, ans in enumerate(ANSWERS * 2):
            if st.get("stage") == "OPTIMIZED":
                break
            wait_idle(page)
            box = page.locator("textarea").last
            box.fill(ans)
            box.press("Enter")
            page.wait_for_timeout(1500)
            st = wait_stage(page, {"CLARIFYING", "OPTIMIZED"}, timeout=120)
            print(f"  answer#{i + 1}: stage={st['stage']} answered={st['answered_gaps']}/{st['total_gaps']}")

        assert st.get("stage") == "OPTIMIZED", f"没有进入 OPTIMIZED：{st.get('stage')}"
        page.click("text=改前改后")
        page.wait_for_timeout(1200)
        page.screenshot(path=str(OUT / f"03_diff{TAG}.png"), full_page=True)
        print("rewrite ok")

        # 刷新验证持久化恢复
        page.reload(wait_until="domcontentloaded")
        page.wait_for_timeout(2500)
        st2 = session_state(page)
        assert st2.get("stage") == "OPTIMIZED", "刷新后会话没有恢复"
        restored_msgs = page.locator("section").first.locator("text=重写完成").count()
        print("restore ok, messages in db:", len(st2.get("messages", [])), "| 重写气泡:", restored_msgs)
        page.screenshot(path=str(OUT / f"04_restored{TAG}.png"), full_page=True)

        page.click("text=简历预览")
        page.wait_for_timeout(1200)
        page.screenshot(path=str(OUT / f"05_preview{TAG}.png"), full_page=True)
        print("preview ok")

        page.click("text=开始模拟面试")
        st = wait_stage(page, {"INTERVIEWING"}, timeout=150)
        page.wait_for_timeout(1200)
        page.screenshot(path=str(OUT / f"06_interview{TAG}.png"), full_page=True)

        answer = (
            "当时业务日活 200 万，我负责新用户引导链路改版，目标是提升 7 日留存。"
            "我先做了用户分层调研，再设计 3 档新手任务并推动 A/B 实验，"
            "最终 7 日留存从 31% 提升到 39%，复盘后把这套方法沉淀成了 SOP。"
        )
        for i in range(5):
            if st.get("stage") == "REVIEWED":
                break
            wait_idle(page)
            box = page.locator("textarea").last
            box.fill(answer)
            box.press("Enter")
            st = wait_answered(page, i + 1, timeout=180)
            print(f"  interview#{i + 1}: stage={st['stage']} answered={st.get('interview_answered')}")
        page.wait_for_timeout(1200)
        page.screenshot(path=str(OUT / f"07_report{TAG}.png"), full_page=True)
        print("interview ok:", st.get("stage"), (st.get("report") or {}).get("overall"))

        print("console errors:", errors[:5])
        browser.close()


if __name__ == "__main__":
    main()
