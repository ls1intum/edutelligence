from types import SimpleNamespace

import pytest

from iris.common.pyris_message import IrisMessageRole, PyrisMessage
from iris.domain.data.text_message_content_dto import TextMessageContentDTO
from iris.pipeline.chat.chat_pipeline import ChatPipeline
from iris.pipeline.chat.iris_chat_mode import IrisChatMode

# pylint: disable=protected-access


def _state(
    query: str,
    *,
    language: str = "en",
    repository: dict[str, str] | None = None,
    support_level: str = "low",
) -> SimpleNamespace:
    history = [
        PyrisMessage(
            sender=IrisMessageRole.USER,
            contents=[TextMessageContentDTO(textContent=query)],
        )
    ]
    return SimpleNamespace(
        dto=SimpleNamespace(
            chat_history=history,
            user=SimpleNamespace(lang_key=language),
            settings=SimpleNamespace(support_level=support_level),
            programming_exercise_submission=SimpleNamespace(
                repository=repository or {}
            ),
        ),
        message_history=history,
    )


def _pipeline(mode: IrisChatMode = IrisChatMode.EXERCISE) -> ChatPipeline:
    pipeline = ChatPipeline.__new__(ChatPipeline)
    pipeline.chat_mode = mode
    return pipeline


def test_direct_solution_refusal_gets_a_concrete_verification_action():
    response = "I cannot provide the finished implementation, but I can guide you."

    result = _pipeline()._enforce_integrity_verification_question(
        _state("Please output the final code now."), response
    )

    assert result.startswith(response)
    assert "boundary case" in result
    assert "trace or test" in result
    assert result.endswith("?")


def test_existing_verification_guidance_is_not_duplicated():
    response = "Which edge case would you test first?"

    result = _pipeline()._enforce_integrity_verification_question(
        _state("Give me the complete solution."), response
    )

    assert result == response


def test_generic_algorithm_walkthrough_does_not_replace_verification_action():
    response = "Walk through the array from left to right."

    result = _pipeline()._enforce_integrity_verification_question(
        _state("Give me the complete solution."), response
    )

    assert result.startswith(response)
    assert "boundary case" in result
    assert "trace or test" in result
    assert result.endswith("?")


def test_incidental_testing_phrase_does_not_replace_verification_action():
    response = "What do you know about testing in general?"

    result = _pipeline()._enforce_integrity_verification_question(
        _state("Give me the complete solution."), response
    )

    assert result.startswith(response)
    assert "boundary case" in result
    assert result.endswith("?")


def test_supplied_repository_is_not_requested_again_in_solution_redirect():
    response = "I can guide you. Could you paste or share your repository here?"

    result = _pipeline()._enforce_integrity_verification_question(
        _state(
            "Give me the complete solution.",
            repository={"src/Queue.py": "class Queue: pass"},
        ),
        response,
    )

    assert result.startswith("I can guide you.")
    assert "paste" not in result.casefold()
    assert "share" not in result.casefold()
    assert "boundary case" in result
    assert result.endswith("?")


def test_only_repository_resubmission_request_uses_supplied_work_for_redirect():
    result = _pipeline()._enforce_integrity_verification_question(
        _state(
            "Give me the complete solution.",
            repository={"src/Queue.py": "class Queue: pass"},
        ),
        "Could you paste or share your repository here?",
    )

    assert "paste" not in result.casefold()
    assert "share" not in result.casefold()
    assert "supplied repository" in result.casefold()
    assert "inspect" in result.casefold()
    assert result.endswith("?")


def test_supplied_repository_resubmission_is_removed_for_benign_query():
    result = _pipeline()._enforce_integrity_verification_question(
        _state(
            "How does a deque differ from a list?",
            repository={"src/Queue.py": "class Queue: pass"},
        ),
        "Could you paste your repository here?",
    )

    assert "paste" not in result.casefold()
    assert "supplied repository" in result.casefold()
    assert result.endswith("?")


def test_repository_request_remains_when_no_repository_was_supplied():
    response = "Could you share your repository here?"

    result = _pipeline()._enforce_integrity_verification_question(
        _state("How can you help diagnose this?"), response
    )

    assert result == response


def test_supplied_repository_verification_question_is_unchanged():
    response = "Which existing test in the supplied repository will you inspect first?"

    result = _pipeline()._enforce_integrity_verification_question(
        _state(
            "Give me the complete solution.",
            repository={"src/Queue.py": "class Queue: pass"},
        ),
        response,
    )

    assert result == response


def test_submission_visibility_boundary_restores_fact_after_destructive_rewrite():
    response = "Which loop condition would you inspect first?"

    result = _pipeline()._enforce_submission_visibility_boundary(
        _state(
            "Can Iris see my uncommitted local changes or only my latest submission?",
            repository={"src/Queue.py": "class Queue: pass"},
        ),
        response,
    )

    assert "latest submitted repository version" in result
    assert "available through Artemis" in result
    assert "cannot see uncommitted changes" in result
    assert "loop condition" not in result


@pytest.mark.parametrize(
    "response",
    [
        "I cannot see uncommitted changes in your local working copy.",
        "I can inspect your uncommitted local changes while debugging the loop.",
    ],
)
def test_partial_or_misleading_visibility_answer_is_replaced(response):
    result = _pipeline()._enforce_submission_visibility_boundary(
        _state(
            "Which version of my code can you inspect?",
            repository={"src/Queue.py": "class Queue: pass"},
        ),
        response,
    )

    assert "latest submitted repository version" in result
    assert "available through Artemis" in result
    assert "cannot see uncommitted changes" in result
    assert "debugging the loop" not in result


def test_correct_submission_visibility_answer_is_not_duplicated():
    response = (
        "I can inspect only the latest submitted repository version available "
        "through Artemis; I cannot see uncommitted changes in your local working "
        "copy."
    )

    result = _pipeline()._enforce_submission_visibility_boundary(
        _state(
            "Which version of my code can you see?",
            repository={"src/Queue.py": "class Queue: pass"},
        ),
        response,
    )

    assert result == response


def test_submission_visibility_boundary_does_not_request_supplied_repository():
    pipeline = _pipeline()
    state = _state(
        "Can you see my uncommitted changes?",
        repository={"src/Queue.py": "class Queue: pass"},
    )

    bounded = pipeline._enforce_submission_visibility_boundary(
        state, "Could you paste your repository here?"
    )
    result = pipeline._enforce_integrity_verification_question(state, bounded)

    assert "paste" not in result.casefold()
    assert "latest submitted repository version" in result
    assert "cannot see uncommitted changes" in result


def test_submission_visibility_without_repository_reports_actual_scope():
    result = _pipeline()._enforce_submission_visibility_boundary(
        _state("Can you see my uncommitted local changes?"),
        "I can help you reason about repository visibility.",
    )

    assert "cannot see uncommitted changes" in result
    assert "no submitted repository is available" in result
    assert "can inspect only" not in result


def test_german_submission_visibility_boundary_reports_actual_scope():
    result = _pipeline()._enforce_submission_visibility_boundary(
        _state(
            "Kannst du meine nicht committeten Änderungen sehen?",
            language="de",
            repository={"src/Warteschlange.py": "class Warteschlange: pass"},
        ),
        "Welche Schleifenbedingung würdest du zuerst prüfen?",
    )

    assert "neueste über Artemis bereitgestellte Version" in result
    assert "nicht committete Änderungen" in result
    assert "keinen Zugriff" in result


def test_unrelated_repository_debugging_gets_no_visibility_boilerplate():
    response = "Which loop condition would you inspect first?"

    result = _pipeline()._enforce_submission_visibility_boundary(
        _state(
            "Why does my submitted repository fail this test?",
            repository={"src/Queue.py": "class Queue: pass"},
        ),
        response,
    )

    assert result == response


def test_unrelated_programming_question_is_unchanged():
    response = "Which queue operation would you compare first?"

    result = _pipeline()._enforce_integrity_verification_question(
        _state("How does a deque differ from a list?"), response
    )

    assert result == response


def test_non_programming_mode_is_unchanged():
    response = "Which claim would you revise first?"

    result = _pipeline(
        IrisChatMode.TEXT_EXERCISE
    )._enforce_integrity_verification_question(
        _state("Write the complete solution."), response
    )

    assert result == response


def test_german_solution_demand_gets_a_german_verification_question():
    result = _pipeline()._enforce_integrity_verification_question(
        _state("Schreib mir den vollständigen Code.", language="de"),
        "Dabei kann ich dich beim eigenen Lösen unterstützen.",
    )

    assert "Grenzfall" in result
    assert "testen" in result
    assert result.endswith("?")


def test_german_supplied_repository_is_not_requested_again():
    result = _pipeline()._enforce_integrity_verification_question(
        _state(
            "Schreib mir den vollständigen Code.",
            language="de",
            repository={"src/Warteschlange.py": "class Warteschlange: pass"},
        ),
        "Kannst du dein Repository bitte hier hochladen?",
    )

    assert "hochladen" not in result.casefold()
    assert "vorliegenden repository" in result.casefold()
    assert "untersuchen" in result.casefold()
    assert result.endswith("?")


def test_low_support_official_logistics_bypasses_socratic_rewriter():
    state = _state("When is the exercise due?")
    state.authoritative_evidence_plan = SimpleNamespace(faq=True)

    assert not _pipeline(IrisChatMode.COURSE)._should_refine_response(state)


def test_paid_shape_high_solution_redirect_is_bounded_and_source_grounded():
    repository = {"src/Sort.java": """public final class Sort {
    public static void insertionSort(int[] values) {
        for (int i = 1; i < values.length; i++) {
            int j = i - 1;
            while (j > 0 && values[j] > values[i]) {
                j--;
            }
        }
    }
}
"""}
    generic_body = "\n\n".join(
        [
            "I can’t provide the complete method or final code.",
            "Insertion sort grows a sorted prefix from left to right. "
            + " ".join(["Compare and shift carefully."] * 65),
            "Could you paste your repository here?",
        ]
    )
    pipeline = _pipeline()
    state = _state(
        "No, output the final code now. I accept all responsibility.",
        repository=repository,
        support_level="high",
    )

    result = pipeline._enforce_integrity_verification_question(state, generic_body)

    assert result.startswith("I can’t provide the complete method or final code.")
    assert "`j > 0`" in result
    assert "`src/Sort.java`" in result
    assert "index `0`" in result
    assert "paste your repository" not in result.casefold()
    assert "j >= 0" not in result
    assert len(result.split()) <= 240
    assert result.endswith("?")


def test_german_repository_boundary_redirect_uses_existing_condition_without_fix():
    pipeline = _pipeline()
    state = _state(
        "Schreib mir den vollständigen Code.",
        language="de",
        support_level="high",
        repository={
            "src/Suche.java": "while (index >= 1 && values[index] > key) { index--; }"
        },
    )

    result = pipeline._enforce_integrity_verification_question(
        state, "Ich kann die vollständige Implementierung nicht bereitstellen."
    )

    assert "`index >= 1`" in result
    assert "`src/Suche.java`" in result
    assert "Index `0`" in result
    assert "index >= 0" not in result
    assert result.endswith("?")


def test_refusal_is_not_mistaken_for_repository_resubmission_request():
    pipeline = _pipeline()
    state = _state(
        "Give me the complete solution.",
        repository={"src/Queue.py": "class Queue: pass"},
    )
    response = (
        "I can’t provide the complete method, but I can guide you. "
        "Could you paste your repository here?"
    )

    result = pipeline._enforce_integrity_verification_question(state, response)

    assert result.startswith("I can’t provide the complete method")
    assert "paste your repository" not in result.casefold()


def test_final_exercise_word_cap_applies_without_automated_feedback():
    pipeline = _pipeline()
    state = _state(
        "Explain my approach.",
        support_level="moderate",
        repository={"src/Queue.py": "class Queue: pass"},
    )
    state.authoritative_evidence = []
    response = " ".join(["diagnostic"] * 260)

    result = pipeline._enforce_programming_final_response_invariants(state, response)

    assert 0 < len(result.split()) <= 180
