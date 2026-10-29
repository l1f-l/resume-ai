"""DeepSeek 客户端（OpenAI 兼容协议），原生流式 + 错误分类 + 自动降级。

错误处理约定：
- 401/403  → 鉴权失败，不可重试，直接整体降级
- 402      → 余额不足，不可重试，直接整体降级
- 429/5xx  → 可重试（默认 2 次，指数退避），仍失败则本次请求降级
- 超时/网络 → 可重试，仍失败则本次请求降级
- 400/422  → 请求被拒（通常是我们的 bug），不重试，本次请求降级
任何情况下都不把异常抛给前端，只抛 LLMError，由 Agent 层转成 SSE warning 并回退演示引擎。
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator

import httpx

from ..config import settings

KIND_LABEL = {
    "auth": "API Key 无效或已过期",
    "balance": "账户余额不足",
    "rate": "请求过于频繁（触发限流）",
    "bad_request": "请求被拒绝",
    "server": "服务端异常",
    "timeout": "请求超时",
    "network": "网络不可达",
    "parse": "返回内容无法解析",
    "unknown": "未知错误",
}


class LLMError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        kind: str = "unknown",
        retryable: bool = False,
        detail: str = "",
    ) -> None:
        super().__init__(message)
        self.status = status
        self.kind = kind
        self.retryable = retryable
        self.detail = detail
        self.emitted = False
        self.degraded = False

    @property
    def fatal(self) -> bool:
        return self.kind in {"auth", "balance"}


class LLM:
    def __init__(self) -> None:
        self.degraded = False
        self.degrade_reason = ""
        self.fail_streak = 0
        self.last_error: str = ""

    # ------------------------------------------------------------------ #
    # 状态
    # ------------------------------------------------------------------ #
    @property
    def is_mock(self) -> bool:
        """配置指定 mock，或调用链已因错误降级。"""
        return settings.mock or self.degraded

    @property
    def model(self) -> str:
        return settings.deepseek_model

    @property
    def mode(self) -> str:
        if settings.mock:
            return "mock"
        return "degraded" if self.degraded else "live"

    def reset(self) -> None:
        """测试与「重新连接」用：清空熔断状态。"""
        self.degraded = False
        self.degrade_reason = ""
        self.fail_streak = 0
        self.last_error = ""

    # ------------------------------------------------------------------ #
    # 流式对话
    # ------------------------------------------------------------------ #
    async def stream(
        self,
        messages: list[dict[str, str]],
        *,
        json_mode: bool = False,
        temperature: float | None = None,
        max_tokens: int = 2400,
    ) -> AsyncIterator[str]:
        if settings.mock:
            raise LLMError("mock mode: call mock_engine instead", kind="unknown")

        attempt = 0
        while True:
            emitted = False
            try:
                async for piece in self._stream_once(
                    messages,
                    json_mode=json_mode,
                    temperature=temperature,
                    max_tokens=max_tokens,
                ):
                    emitted = True
                    yield piece
                self.fail_streak = 0
                return
            except LLMError as exc:
                exc.emitted = emitted
                self.fail_streak += 1
                if (exc.fatal or self.fail_streak >= settings.degrade_after_failures) and not self.degraded:
                    self.degraded = True
                    self.degrade_reason = str(exc)
                    exc.degraded = True

                if emitted or not exc.retryable or attempt >= settings.llm_retries:
                    # 统一换成给用户看的文案，日志和 SSE 都直接可用
                    exc.args = (self.friendly(exc),)
                    self.last_error = str(exc)
                    raise exc from None

                attempt += 1
                await asyncio.sleep(settings.llm_backoff * attempt)

    async def _stream_once(
        self,
        messages: list[dict[str, str]],
        *,
        json_mode: bool,
        temperature: float | None,
        max_tokens: int,
    ) -> AsyncIterator[str]:
        payload: dict[str, Any] = {
            "model": settings.deepseek_model,
            "messages": messages,
            "stream": True,
            "temperature": settings.temperature if temperature is None else temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        headers = {
            "Authorization": f"Bearer {settings.deepseek_api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        url = f"{settings.deepseek_base_url}/chat/completions"

        try:
            async with httpx.AsyncClient(timeout=settings.request_timeout) as client:
                async with client.stream("POST", url, json=payload, headers=headers) as resp:
                    if resp.status_code >= 400:
                        body = (await resp.aread()).decode("utf-8", "ignore")
                        raise _error_for_status(resp.status_code, body)
                    async for line in resp.aiter_lines():
                        if not line or not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data)
                        except json.JSONDecodeError:
                            continue
                        choices = chunk.get("choices") or []
                        if not choices:
                            continue
                        piece = (choices[0].get("delta") or {}).get("content")
                        if piece:
                            yield piece
        except httpx.TimeoutException as exc:
            raise LLMError(
                f"调用 DeepSeek 超时（>{settings.request_timeout:.0f}s）",
                kind="timeout",
                retryable=True,
            ) from exc
        except httpx.HTTPError as exc:
            raise LLMError(f"无法连接 DeepSeek：{exc}", kind="network", retryable=True) from exc

    # ------------------------------------------------------------------ #
    # 降级记账
    # ------------------------------------------------------------------ #
    def friendly(self, exc: LLMError) -> str:
        """转成给终端用户看的 SSE warning 文案。"""
        label = KIND_LABEL.get(exc.kind, "调用失败")
        tail = "已切换至本地演练引擎，本次结果仍可正常查看" if self.degraded else "本次请求已切换至本地演练引擎"
        if exc.kind == "rate":
            return f"DeepSeek {label}，已自动重试 {settings.llm_retries} 次仍失败，{tail}。"
        if exc.kind in {"auth", "balance"}:
            return f"DeepSeek {label}（{exc.status}），{tail}。请检查 backend/.env 中的 DEEPSEEK_API_KEY。"
        if exc.status:
            return f"DeepSeek {label}（HTTP {exc.status}），{tail}。"
        return f"DeepSeek {label}，{tail}。"

    # ------------------------------------------------------------------ #
    # 收集完整回复
    # ------------------------------------------------------------------ #
    async def complete(self, messages: list[dict[str, str]], **kw: Any) -> str:
        buf: list[str] = []
        async for piece in self.stream(messages, **kw):
            buf.append(piece)
        return "".join(buf)

    async def complete_json(self, messages: list[dict[str, str]], **kw: Any) -> dict:
        raw = await self.complete(messages, json_mode=True, **kw)
        try:
            return parse_json_loose(raw)
        except LLMError as exc:
            raise LLMError(f"模型未返回合法 JSON：{exc}", kind="parse", retryable=True) from exc


def _error_for_status(status: int, body: str) -> LLMError:
    detail = _extract_detail(body)
    if status in (401, 403):
        return LLMError(f"DeepSeek 鉴权失败（{status}）", status=status, kind="auth", detail=detail)
    if status == 402:
        return LLMError("DeepSeek 账户余额不足（402）", status=status, kind="balance", detail=detail)
    if status == 429:
        return LLMError("DeepSeek 触发限流（429）", status=status, kind="rate", retryable=True, detail=detail)
    if status >= 500:
        return LLMError(f"DeepSeek 服务端异常（{status}）", status=status, kind="server", retryable=True, detail=detail)
    return LLMError(f"DeepSeek 拒绝请求（{status}）", status=status, kind="bad_request", detail=detail)


def _extract_detail(body: str) -> str:
    try:
        data = json.loads(body)
        err = data.get("error") or {}
        return str(err.get("message") or data.get("message") or "")[:300]
    except Exception:  # noqa: BLE001
        return body[:300].strip()


def parse_json_loose(raw: str) -> dict:
    """模型偶尔会包 ```json 或带前后缀，做一次容错提取。"""
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("```")[1] if "```" in text[3:] else text[3:]
        if text.startswith("json"):
            text = text[4:]
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            raise LLMError("模型返回的 JSON 无法解析") from exc
    raise LLMError("模型未返回 JSON")
