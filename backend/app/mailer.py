"""邮件发送：真实 SMTP + 无凭据时的本地 .eml 模拟。

安全与体验取舍：
- 邮件只发往**注册邮箱**，收件人由后端从 JWT 用户里取，前端不能指定，
  避免这套演示接口被用来给任意第三方发信。
- 未配置 SMTP 时降级为 `simulated`：把 .eml 与 PDF 落到 data/outbox/，
  前端可下载查看，整条投递闭环依然可演示。
- 发送失败不阻塞投递记录（mail_status=failed + 原因），用户可以重发。
"""
from __future__ import annotations

import asyncio
import logging
import smtplib
import time
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr, formatdate
from pathlib import Path

from .config import settings

log = logging.getLogger("mailer")


@dataclass
class MailResult:
    status: str            # sent | simulated | failed
    to: str = ""
    subject: str = ""
    body_html: str = ""
    attachment: str = ""   # 附件落盘路径（相对 backend/）
    error: str = ""


def outbox_dir() -> Path:
    path = settings.data_dir / "outbox"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _build(to: str, subject: str, html: str, pdf: bytes, pdf_name: str) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((settings.smtp_from_name, settings.smtp_user or "no-reply@resumepilot.local"))
    msg["To"] = to
    msg["Date"] = formatdate(localtime=True)
    msg.set_content("这是一封 HTML 邮件，请使用支持 HTML 的客户端查看。")
    msg.add_alternative(html, subtype="html")
    msg.add_attachment(pdf, maintype="application", subtype="pdf", filename=pdf_name)
    return msg


def save_attachment(pdf: bytes, filename: str, tag: str) -> str:
    """投递用的简历 PDF 落盘留档（真实发送与模拟发送都需要，便于回看当时投的版本）。"""
    path = outbox_dir() / f"{tag}.pdf"
    try:
        path.write_bytes(pdf)
    except OSError as exc:
        log.warning("save attachment failed: %s", exc)
        return ""
    return str(path.relative_to(settings.data_dir.parent)).replace("\\", "/")


def send_now(
    *,
    to: str,
    subject: str,
    html: str,
    pdf: bytes,
    pdf_name: str,
    tag: str,
    attachment: str = "",
) -> MailResult:
    """同步发送（在线程池里调用）。任何失败都返回 failed，不抛异常。"""
    msg = _build(to, subject, html, pdf, pdf_name)

    if not settings.smtp_ready:
        eml_path = outbox_dir() / f"{tag}.eml"
        try:
            eml_path.write_bytes(bytes(msg))
        except OSError as exc:
            return MailResult(status="failed", to=to, subject=subject, body_html=html,
                              attachment=attachment, error=f"本地归档失败：{exc}")
        return MailResult(status="simulated", to=to, subject=subject, body_html=html,
                          attachment=attachment, error="未配置 SMTP，已生成本地 .eml 存档")

    try:
        if settings.smtp_ssl:
            server = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=20)
        else:
            server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20)
            server.starttls()
        with server:
            server.login(settings.smtp_user, settings.smtp_password)
            server.send_message(msg)
        return MailResult(status="sent", to=to, subject=subject, body_html=html,
                          attachment=attachment)
    except Exception as exc:  # noqa: BLE001 - smtplib 异常种类多，统一转失败
        log.warning("smtp send failed: %s", exc)
        return MailResult(status="failed", to=to, subject=subject, body_html=html,
                          attachment=attachment, error=str(exc)[:300])


async def send_mail(**kwargs) -> MailResult:
    """异步包装：smtplib 是阻塞 IO，必须丢到线程池，否则会卡住整个事件循环。"""
    return await asyncio.to_thread(send_now, **kwargs)
