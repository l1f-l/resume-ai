"""会话状态机。

设计目标：把「流程是否正确」从 LLM 的不确定性里剥离出来，做成可单测的纯逻辑。

NEW ──upload──> PARSED ──analyze──> DIAGNOSED ──chat──> CLARIFYING
                                                   │   (答完所有追问)
                                                   ▼
OPTIMIZED <──rewrite── READY_TO_REWRITE <───────────┘
   │
   └──interview.start──> INTERVIEWING ──全部作答──> REVIEWED
任意阶段 ──reset──> NEW
"""
from __future__ import annotations

from typing import Iterable


class IllegalTransition(RuntimeError):
    def __init__(self, src: str, dst: str) -> None:
        self.src, self.dst = src, dst
        super().__init__(f"illegal stage transition: {src} -> {dst}")


class Stage:
    NEW = "NEW"
    PARSED = "PARSED"
    DIAGNOSED = "DIAGNOSED"
    CLARIFYING = "CLARIFYING"
    READY_TO_REWRITE = "READY_TO_REWRITE"
    OPTIMIZED = "OPTIMIZED"
    INTERVIEWING = "INTERVIEWING"
    REVIEWED = "REVIEWED"

    ALL = (NEW, PARSED, DIAGNOSED, CLARIFYING, READY_TO_REWRITE, OPTIMIZED, INTERVIEWING, REVIEWED)

    LABELS = {
        NEW: "待上传",
        PARSED: "已解析",
        DIAGNOSED: "已诊断",
        CLARIFYING: "追问中",
        READY_TO_REWRITE: "待重写",
        OPTIMIZED: "已优化",
        INTERVIEWING: "模拟面试",
        REVIEWED: "面试复盘",
    }


#: 显式声明的合法迁移
TRANSITIONS: dict[str, set[str]] = {
    Stage.NEW: {Stage.PARSED},
    Stage.PARSED: {Stage.DIAGNOSED},
    Stage.DIAGNOSED: {Stage.CLARIFYING, Stage.READY_TO_REWRITE},
    Stage.CLARIFYING: {Stage.CLARIFYING, Stage.READY_TO_REWRITE},
    Stage.READY_TO_REWRITE: {Stage.OPTIMIZED},
    Stage.OPTIMIZED: {Stage.OPTIMIZED, Stage.INTERVIEWING},
    Stage.INTERVIEWING: {Stage.INTERVIEWING, Stage.REVIEWED},
    Stage.REVIEWED: {Stage.REVIEWED, Stage.INTERVIEWING},
}


class StateMachine:
    """轻量状态机：任何非法迁移都会抛 IllegalTransition（由路由层转 409）。"""

    def __init__(self, stage: str = Stage.NEW) -> None:
        if stage not in Stage.ALL:
            raise ValueError(f"unknown stage: {stage}")
        self._stage = stage
        self.history: list[str] = [stage]

    @property
    def stage(self) -> str:
        return self._stage

    @property
    def label(self) -> str:
        return Stage.LABELS.get(self._stage, self._stage)

    def can(self, dst: str) -> bool:
        return dst in TRANSITIONS.get(self._stage, set())

    def to(self, dst: str) -> str:
        if dst == self._stage:
            return self._stage
        if not self.can(dst):
            raise IllegalTransition(self._stage, dst)
        self._stage = dst
        self.history.append(dst)
        return self._stage

    def expect(self, *allowed: str) -> None:
        """断言当前阶段属于 allowed，否则抛 IllegalTransition。"""
        if self._stage not in allowed:
            raise IllegalTransition(self._stage, "|".join(allowed))

    def __repr__(self) -> str:  # pragma: no cover
        return f"<StateMachine {self._stage}>"


def next_stage_for_gaps(total: int, answered: int) -> str:
    """追问进度 -> 下一阶段。全部答完即进入待重写。"""
    return Stage.READY_TO_REWRITE if answered >= total else Stage.CLARIFYING


def pipeline_progress(stage: str) -> Iterable[tuple[str, bool, bool]]:
    """给前端画步骤条：(名称, 已完成, 进行中)"""
    order = [
        Stage.PARSED,
        Stage.DIAGNOSED,
        Stage.CLARIFYING,
        Stage.OPTIMIZED,
        Stage.INTERVIEWING,
    ]
    idx = {
        Stage.NEW: -1,
        Stage.PARSED: 0,
        Stage.DIAGNOSED: 1,
        Stage.CLARIFYING: 2,
        Stage.READY_TO_REWRITE: 2,
        Stage.OPTIMIZED: 3,
        Stage.INTERVIEWING: 4,
        Stage.REVIEWED: 5,
    }.get(stage, -1)
    for i, s in enumerate(order):
        yield s, i < idx, i == idx
