"""生成演示用中文简历 PDF 与 JD，方便一键体验。

用法：python -m scripts.make_sample
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reportlab.lib.colors import HexColor  # noqa: E402
from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.pdfbase import pdfmetrics  # noqa: E402
from reportlab.pdfbase.cidfonts import UnicodeCIDFont  # noqa: E402
from reportlab.pdfgen import canvas  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "samples"

RESUME = """张明
求职意向：用户增长产品经理
13800138000 | zhangming@example.com | 上海 | github.com/zhangming

个人简介
5 年互联网产品经验，先后负责社区内容与电商增长方向，擅长用数据定位问题。

工作经历
字节跳动 | 高级产品经理 2021.03-至今
- 负责抖音电商的用户增长活动策划与落地
- 参与搭建用户分层体系，优化推送触达策略
- 协助推进跨部门项目，协调研发与运营资源
- 负责增长数据看板的需求梳理与迭代

小红书 | 产品经理 2019.07-2021.02
- 负责社区内容推荐的产品设计
- 参与用户调研与竞品分析，输出需求文档
- 优化新用户引导流程，调整新手任务结构

项目经历
新用户 7 日留存提升项目 2022.05-2022.11
- 主导新用户引导链路改版，设计分层任务体系
- 推动 A/B 实验落地，复盘实验结论并迭代

教育背景
复旦大学 | 本科 | 信息管理与信息系统 2015.09-2019.06

专业技能
Axure, SQL, 数据分析, 用户调研, A/B测试, Figma, 项目管理

证书 / 荣誉
PMP 项目管理专业人士
"""

JD = """用户增长产品经理（高级）

岗位职责：
1. 负责 App 用户增长策略制定与落地，对 DAU、留存率、转化率核心指标负责；
2. 搭建用户分层与生命周期运营体系，设计自动化触达策略；
3. 主导 A/B 实验设计与归因分析，持续优化漏斗转化率；
4. 协同投放团队优化 ROI 与获客成本，控制 CAC；
5. 输出增长方法论与 SOP，赋能业务团队。

任职要求：
1. 本科及以上学历，5 年以上互联网产品经验，其中 3 年以上用户增长方向；
2. 精通 SQL 与数据分析，能独立完成漏斗分析、AB 实验与指标体系建设；
3. 熟悉私域、社群运营与内容运营者优先；
4. 有从 0 到 1 搭建增长体系经验者优先；
5. 优秀的跨部门协作与项目管理能力，能推动多团队按期交付。
"""


def build_pdf(path: Path) -> None:
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    font = "STSong-Light"
    W, H = A4
    c = canvas.Canvas(str(path), pagesize=A4)
    c.setTitle("张明 - 用户增长产品经理")
    y = H - 60
    for i, raw in enumerate(RESUME.splitlines()):
        line = raw.strip()
        if not line:
            y -= 6
            continue
        if i == 0:
            c.setFont(font, 22)
            c.setFillColor(HexColor("#111827"))
            c.drawString(56, y, line)
            y -= 26
            continue
        if line.startswith("-"):
            c.setFont(font, 10)
            c.setFillColor(HexColor("#374151"))
            c.drawString(70, y, line)
            y -= 17
            continue
        if line in ("个人简介", "工作经历", "项目经历", "教育背景", "专业技能", "证书 / 荣誉"):
            c.setFont(font, 11)
            c.setFillColor(HexColor("#0f766e"))
            c.drawString(56, y, line)
            y -= 15
            continue
        c.setFont(font, 10.5 if "|" in line else 10)
        c.setFillColor(HexColor("#111827" if "|" in line else "#4b5563"))
        c.drawString(56, y, line)
        y -= 17
    c.showPage()
    c.save()


def build_scanned_pdf(src: Path, dst: Path, dpi: int = 200) -> None:
    """把文字版 PDF 渲染成图片再包成 PDF —— 模拟「扫描件」（没有文字层）。"""
    import pymupdf

    source = pymupdf.open(str(src))
    out = pymupdf.open()
    for page in source:
        # 用 JPEG 而不是无损 PNG：200dpi 的 A4 扫描件从 12MB 降到 ~1MB
        jpg = page.get_pixmap(dpi=dpi).tobytes("jpg", jpg_quality=82)
        new_page = out.new_page(width=page.rect.width, height=page.rect.height)
        new_page.insert_image(page.rect, stream=jpg)
    out.save(str(dst))
    out.close()
    source.close()


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    build_pdf(OUT / "sample_resume.pdf")
    build_scanned_pdf(OUT / "sample_resume.pdf", OUT / "scanned_resume.pdf")
    (OUT / "sample_jd.txt").write_text(JD, encoding="utf-8")
    print(f"已生成：{OUT / 'sample_resume.pdf'}")
    print(f"已生成：{OUT / 'scanned_resume.pdf'}（OCR 演示用）")
    print(f"已生成：{OUT / 'sample_jd.txt'}")


if __name__ == "__main__":
    main()
