"""SSE 协议工具。api.py 与各领域路由共用同一套帧格式与收尾逻辑。"""
from __future__ import annotations

import json
import logging
from typing import AsyncIterator

from fastapi.responses import StreamingResponse

from .services.state import IllegalTransition
from .session import Session, store

log = logging.getLogger("sse")


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def sse_stream(
    gen: AsyncIterator[tuple[str, dict]],
    session: Session | None = None,
) -> StreamingResponse:
    """统一收尾：无论成功、报错还是客户端断开，都把会话快照写回 SQLite。"""

    async def body() -> AsyncIterator[str]:
        try:
            async for event, data in gen:
                yield sse(event, data)
        except IllegalTransition as exc:
            yield sse("error", {"message": f"当前阶段不允许该操作（{exc}）"})
        except Exception as exc:  # noqa: BLE001
            log.exception("stream failed")
            yield sse("error", {"message": f"处理失败：{exc}"})
        finally:
            if session is not None:
                try:
                    store.save(session)
                except Exception:  # noqa: BLE001
                    log.exception("persist session failed")
        yield sse("done", {"ok": True})

    return StreamingResponse(
        body(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
