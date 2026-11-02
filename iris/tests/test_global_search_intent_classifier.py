"""Regression test for the intent classifier's ONNX input handling.

The ONNX graph was exported while the tokenizer still produced
``token_type_ids``; a transformers library upgrade changed the tokenizer's
default output to no longer include it, even though the pinned tokenizer
*revision* never changed. ``_get_classifier()`` used to swallow that mismatch
as a load failure and silently fall back to always returning TRIGGER_AI,
disabling the feature without ever raising past module import.
"""

# pylint: disable=protected-access

from unittest.mock import MagicMock

import numpy as np
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


class TestInferTokenTypeIdsCompatibility:
    """`_infer`'s zero-filled token_type_ids branch, exercised directly against a mocked
    tokenizer/session/head so it runs without the real (gitignored, CI-unavailable) ONNX
    model file described in the module docstring above."""

    def _classifier(self, model_input_names):
        # Bypasses __init__ (no real tokenizer/ONNX/joblib files needed): only the
        # attributes _infer actually reads are set, as plain mocks.
        classifier = intent_classifier._IntentClassifier.__new__(
            intent_classifier._IntentClassifier
        )
        classifier._use_mean_pooling = True
        classifier._input_names = model_input_names
        classifier._output_names = ["token_embeddings"]
        classifier._tokenizer = MagicMock(
            return_value={
                "input_ids": np.array([[1, 2, 3]]),
                "attention_mask": np.array([[1, 1, 1]]),
            }
        )
        classifier._session = MagicMock()
        classifier._session.run.return_value = [np.ones((1, 3, 4))]
        classifier._head = MagicMock()
        classifier._head.predict.return_value = np.array([1])
        return classifier

    def test_zero_fills_token_type_ids_when_the_model_needs_them_but_the_tokenizer_omitted_them(
        self,
    ):
        classifier = self._classifier({"input_ids", "attention_mask", "token_type_ids"})

        result = classifier._infer("some query")

        assert result == SearchIntent.TRIGGER_AI
        fed_inputs = classifier._session.run.call_args[0][1]
        assert "token_type_ids" in fed_inputs
        assert np.array_equal(fed_inputs["token_type_ids"], np.zeros((1, 3)))

    def test_leaves_token_type_ids_out_when_the_model_does_not_declare_that_input(self):
        classifier = self._classifier({"input_ids", "attention_mask"})

        classifier._infer("some query")

        fed_inputs = classifier._session.run.call_args[0][1]
        assert "token_type_ids" not in fed_inputs
