import pytest

from ai_judge.phase2.context import ConversationContext
from ai_judge.phase2.contracts import TargetError


def context(enabled, turns=2, characters=1000):
    return ConversationContext(
        sliding_window=enabled, window_turns=turns, max_characters=characters, system="format"
    )


def test_window_removes_complete_oldest_pairs_only():
    window = context(True, turns=2)
    for i in range(4):
        window.complete(f"q{i}", f"a{i}")
    result = window.prepare("current")
    assert result.dropped_turns == 2
    assert [item["content"] for item in result.messages] == [
        "format",
        "q2",
        "a2",
        "q3",
        "a3",
        "current",
    ]


def test_disabled_preserves_all_and_rejects_overflow():
    full = context(False, turns=1)
    for i in range(3):
        full.complete(f"q{i}", f"a{i}")
    assert len(full.prepare("next").messages) == 8
    full.max_characters = 30
    with pytest.raises(TargetError, match="context_limit_exceeded"):
        full.prepare("next")
    assert len(full.history) == 3


def test_window_budget_drops_pairs_without_truncating_current_query():
    window = context(True, characters=30)
    window.complete("old question", "old answer")
    result = window.prepare("new")
    assert result.dropped_turns == 1
    assert result.messages[-1]["content"] == "new"
    with pytest.raises(TargetError, match="context_limit_exceeded"):
        window.prepare("x" * 31)


def test_context_isolation_and_repeated_prepare():
    one, two = context(True), context(True)
    one.complete("case one", "answer")
    assert one.prepare("next").messages == one.prepare("next").messages
    assert len(two.prepare("case two").messages) == 2
