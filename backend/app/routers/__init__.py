"""路由包：Pro 版新增的领域路由从这里挂载，api.py 只负责 include。

按阶段增量挂载，保证任一阶段都能独立启动与测试。
"""
from __future__ import annotations

from . import auth

__all__ = ["auth"]
