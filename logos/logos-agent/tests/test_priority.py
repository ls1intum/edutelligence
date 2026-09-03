"""Tests for what the platform works on first while it is busy.

Sessions are admitted one per capacity reading, so ordering is not a
nicety: whatever sorts first is what gets the idle GPU, and everything else
waits for the next one.
"""

from __future__ import annotations

from app import priority


def labels(*names: str) -> list[dict]:
    return [{"name": name} for name in names]


class TestKinds:
    def test_a_review_outranks_new_work(self):
        # A review holds a pull request shut; an issue has nobody waiting.
        assert priority.of("review").value > priority.of("issue").value

    def test_a_question_outranks_new_work(self):
        # Somebody is on the other end of it, and answering is short.
        assert priority.of("comment").value > priority.of("issue").value

    def test_a_handover_outranks_a_fresh_issue(self):
        assert priority.of("takeover").value > priority.of("issue").value

    def test_an_unknown_kind_lands_in_the_middle(self):
        assert 0 < priority.of("something-new").value < 100


class TestLabels:
    def test_a_security_fix_outranks_everything_of_its_kind(self):
        assert priority.of("issue", labels("security fix")).value > priority.of("issue", labels("bug")).value

    def test_a_bug_outranks_an_enhancement(self):
        assert priority.of("issue", labels("bug")).value > priority.of("issue", labels("enhancement")).value

    def test_documentation_sinks_below_plain_work(self):
        assert priority.of("issue", labels("documentation")).value < priority.of("issue").value

    def test_the_strongest_label_decides(self):
        both = priority.of("issue", labels("documentation", "security fix"))
        assert both.value == priority.of("issue", labels("security fix")).value

    def test_a_security_issue_outranks_an_ordinary_review(self):
        # Across kinds too: the ordering is one scale, not one per kind.
        assert priority.of("issue", labels("security fix")).value > priority.of("review").value

    def test_labels_may_be_plain_strings(self):
        assert priority.of("issue", ["bug"]).value == priority.of("issue", labels("bug")).value

    def test_the_reason_says_why(self):
        assert "security" in priority.of("issue", labels("security fix")).reason
        assert "review" in priority.of("review").reason


class TestRefusal:
    def test_blocked_work_is_not_picked_up(self):
        urgency = priority.of("issue", labels("blocked"))
        assert urgency.refused and urgency.refused_by == "blocked"

    def test_the_other_closing_labels_refuse_too(self):
        for label in ("wontfix", "invalid", "duplicate", "stale"):
            assert priority.of("issue", labels(label)).refused, label

    def test_a_refusal_beats_urgency(self):
        # "Blocked and critical" is blocked: the label is an answer, not a
        # measure of how much somebody wants it.
        assert priority.of("issue", labels("critical", "blocked")).refused

    def test_ordinary_work_is_not_refused(self):
        assert not priority.of("issue", labels("bug")).refused


class TestBounds:
    def test_nothing_leaves_the_column_range(self):
        for kind in ("issue", "review", "comment", "takeover"):
            for label in ("security fix", "documentation", "good first issue", "critical"):
                value = priority.of(kind, labels(label)).value
                assert priority.MIN <= value <= priority.MAX
