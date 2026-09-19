"""Regression test for the intent classifier's ONNX input handling.

The ONNX graph was exported while the tokenizer still produced
``token_type_ids``; a transformers library upgrade changed the tokenizer's
default output to no longer include it, even though the pinned tokenizer
*revision* never changed. ``_get_classifier()`` used to swallow that mismatch
as a load failure and silently fall back to always returning TRIGGER_AI,
disabling the feature without ever raising past module import.
"""

# pylint: disable=protected-access

import pytest

import iris.pipeline.shared.global_search_intent_classifier as intent_classifier
from iris.domain.search.search_intent_dto import SearchIntent

# The compiled .onnx weights are gitignored (fetched/built locally, not
# checked into the repo — see models/global_search_intent/.gitignore), so this
# test only has a real model to exercise wherever that artifact is present.
_HAS_ONNX_MODEL = any(intent_classifier._model_dir().glob("*.onnx"))


@pytest.mark.skipif(
    not _HAS_ONNX_MODEL,
    reason="compiled ONNX model not present (gitignored, dev-machine-local artifact)",
)
def test_classifier_loads_and_classifies_a_real_query():
    intent_classifier._classifier_instance = None
    intent_classifier._model_dir_missing = False

    classifier = intent_classifier._get_classifier()

    assert classifier is not None, (
        "classifier failed to load against the real tokenizer and ONNX model "
        "(this is exactly the token_type_ids regression this test guards)"
    )
    result = classifier.classify("What is the deadline for the next assignment?")
    assert isinstance(result, SearchIntent)
