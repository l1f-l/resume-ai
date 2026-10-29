"""状态机与追问进度测试：流程正确性不依赖 LLM。"""
from __future__ import annotations

import pytest

from app.schemas import Diagnosis, GapQuestion
from app.services.state import (
    IllegalTransition,
    Stage,
    StateMachine,
    next_stage_for_gaps,
    pipeline_progress,
)


def test_happy_path_transitions() -> None:
    m = StateMachine()
    for stage in (
        Stage.PARSED,
        Stage.DIAGNOSED,
        Stage.CLARIFYING,
        Stage.READY_TO_REWRITE,
        Stage.OPTIMIZED,
        Stage.INTERVIEWING,
        Stage.REVIEWED,
    ):
        assert m.can(stage)
        m.to(stage)
    assert m.stage == Stage.REVIEWED
    assert m.history[0] == Stage.NEW and m.history[-1] == Stage.REVIEWED


def test_idempotent_transition_is_allowed() -> None:
    m = StateMachine(Stage.CLARIFYING)
    assert m.to(Stage.CLARIFYING) == Stage.CLARIFYING
    assert m.history.count(Stage.CLARIFYING) == 1


@pytest.mark.parametrize(
    ("start", "target"),
    [
        (Stage.NEW, Stage.OPTIMIZED),
        (Stage.PARSED, Stage.INTERVIEWING),
        (Stage.DIAGNOSED, Stage.OPTIMIZED),      # 必须先追问或多轮确认
        (Stage.OPTIMIZED, Stage.DIAGNOSED),      # 不允许倒退
        (Stage.REVIEWED, Stage.OPTIMIZED),
    ],
)
def test_illegal_transitions_raise(start: str, target: str) -> None:
    m = StateMachine(start)
    assert not m.can(target)
    with pytest.raises(IllegalTransition):
        m.to(target)


def test_expect_guards() -> None:
    m = StateMachine(Stage.PARSED)
    m.expect(Stage.PARSED)
    with pytest.raises(IllegalTransition):
        m.expect(Stage.OPTIMIZED)


def test_gap_progress_drives_next_stage() -> None:
    assert next_stage_for_gaps(total=3, answered=0) == Stage.CLARIFYING
    assert next_stage_for_gaps(total=3, answered=2) == Stage.CLARIFYING
    assert next_stage_for_gaps(total=3, answered=3) == Stage.READY_TO_REWRITE
    assert next_stage_for_gaps(total=0, answered=0) == Stage.READY_TO_REWRITE


def test_pipeline_progress_marks_current() -> None:
    steps = list(pipeline_progress(Stage.OPTIMIZED))
    assert len(steps) == 5
    current = [s for s, done, active in steps if active]
    assert current == [Stage.OPTIMIZED]
    assert all(done for _, done, _ in steps[:3])


def test_session_gap_bookkeeping() -> None:
    from app.session import Session

    s = Session(id="t1")
    s.diagnosis = Diagnosis(
        gap_questions=[
            GapQuestion(id="g1", topic="规模", question="q1", bullet_id="b1"),
            GapQuestion(id="g2", topic="幅度", question="q2", bullet_id="b2"),
        ]
    )
    assert s.gap_progress() == (0, 2)
    assert s.current_gap().id == "g1"

    s.mark_answered("覆盖 320 万用户")
    assert s.answers == {"b1": "覆盖 320 万用户"}
    assert s.gap_progress() == (1, 2)
    assert s.current_gap().id == "g2"

    s.mark_answered("")  # 用户选择跳过
    assert s.gap_progress() == (2, 2)
    assert s.current_gap() is None
    assert "b2" not in s.answers
