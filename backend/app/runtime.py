"""进程级单例：LLM 客户端必须全局唯一，否则熔断状态（degraded / fail_streak）不共享。"""
from __future__ import annotations

from .services.llm import LLM

llm = LLM()
