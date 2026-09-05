from iris.domain.data.verdict_dto import VerdictDTO


def test_defaults_are_none_when_omitted():
    verdict = VerdictDTO()

    assert verdict.verdict is None
    assert verdict.reasoning is None


def test_constructs_from_keyword_arguments():
    verdict = VerdictDTO(
        verdict="SUSPICIOUS", reasoning="Answer contradicted the code."
    )

    assert verdict.verdict == "SUSPICIOUS"
    assert verdict.reasoning == "Answer contradicted the code."


def test_round_trips_through_model_dump():
    verdict = VerdictDTO(verdict="NEXT_QUESTION", reasoning="Too vague.")

    dumped = verdict.model_dump(by_alias=True)

    assert dumped == {"verdict": "NEXT_QUESTION", "reasoning": "Too vague."}
    assert VerdictDTO(**dumped) == verdict
