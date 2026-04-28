"""
Lightweight intent classifier for Artemis search queries.

Loads the INT8-quantized ONNX SetFit model once at module level and exposes
a single ``classify(query)`` function that returns "trigger_ai" or "skip_ai"
in ~2 ms per call.

Set the INTENT_MODEL_DIR environment variable to override the default model
path (relative to the repo root).
"""

import json
import os
import threading
from pathlib import Path

import joblib
import numpy as np
import onnxruntime as ort
from transformers import AutoTokenizer

from iris.common.logging_config import get_logger
from iris.domain.search.search_intent_dto import SearchIntent

logger = get_logger(__name__)

_LABELS = {0: SearchIntent.SKIP_AI, 1: SearchIntent.TRIGGER_AI}

_DEFAULT_MODEL_DIR = (
    Path(__file__).resolve().parents[4] / "models" / "global_search_intent" / "onnx"
)


def _model_dir() -> Path:
    override = os.environ.get("INTENT_MODEL_DIR")
    return Path(override) if override else _DEFAULT_MODEL_DIR


def _find_onnx_file(directory: Path) -> Path:
    candidates = sorted(directory.glob("*.onnx"))
    if not candidates:
        raise FileNotFoundError(f"No .onnx file found in {directory}")
    quantized = [p for p in candidates if "quantized" in p.name]
    return quantized[0] if quantized else candidates[0]


def _mean_pool(token_embeddings: np.ndarray, attention_mask: np.ndarray) -> np.ndarray:
    mask = attention_mask[:, :, np.newaxis].astype(np.float32)
    summed = (token_embeddings * mask).sum(axis=1)
    counts = mask.sum(axis=1).clip(min=1e-9)
    return summed / counts


class _IntentClassifier:
    """Holds all loaded artifacts and runs inference."""

    def __init__(self, model_dir: Path) -> None:
        logger.info("Loading intent classifier from %s", model_dir)

        onnx_path = _find_onnx_file(model_dir)
        meta = json.loads((model_dir / "meta.json").read_text())
        self._tokenizer = AutoTokenizer.from_pretrained(
            meta["base_model"]
        )  # nosec B615
        self._head = joblib.load(model_dir / "model_head.joblib")

        pooling_cfg = json.loads((model_dir / "pooling_config.json").read_text())
        self._use_mean_pooling = pooling_cfg.get("pooling_mode_mean_tokens", True)

        sess_opts = ort.SessionOptions()
        sess_opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        sess_opts.intra_op_num_threads = 4
        self._session = ort.InferenceSession(
            str(onnx_path), sess_opts, providers=["CPUExecutionProvider"]
        )
        self._input_names = {inp.name for inp in self._session.get_inputs()}
        self._output_names = [out.name for out in self._session.get_outputs()]

        # Warm up the ORT session so the first real request isn't slow
        self._infer("warmup")
        logger.info("Intent classifier ready (model: %s)", onnx_path.name)

    def _infer(self, query: str) -> SearchIntent:
        enc = self._tokenizer(
            query,
            return_tensors="np",
            padding=True,
            truncation=True,
            max_length=128,
        )
        ort_inputs = {k: v for k, v in enc.items() if k in self._input_names}
        outputs = self._session.run(self._output_names, ort_inputs)
        token_embeddings = outputs[0]

        if self._use_mean_pooling:
            embedding = _mean_pool(token_embeddings, enc["attention_mask"])
        else:
            embedding = token_embeddings[:, 0, :]

        pred_class = int(self._head.predict(embedding)[0])
        return _LABELS[pred_class]

    def classify(self, query: str) -> SearchIntent:
        return self._infer(query)


_classifier_instance: "_IntentClassifier | None" = None
_classifier_lock = threading.Lock()
_model_dir_missing: bool = False  # latched once to suppress repeated warnings


def _get_classifier() -> "_IntentClassifier | None":
    """Load lazily; only memoize on success so transient errors are retried.

    The missing-model-directory case is treated as permanent and latched so
    that the warning is only emitted once per process lifetime.
    """
    global _classifier_instance, _model_dir_missing
    if _classifier_instance is not None:
        return _classifier_instance
    if _model_dir_missing:
        return None
    model_dir = _model_dir()
    if not model_dir.exists():
        _model_dir_missing = True
        logger.warning(
            "Intent model directory not found at %s — intent filtering disabled",
            model_dir,
        )
        return None
    with _classifier_lock:
        if _classifier_instance is not None:
            return _classifier_instance
        try:
            _classifier_instance = _IntentClassifier(model_dir)
        except Exception:
            logger.exception(
                "Failed to load intent classifier — will retry on next call"
            )
            return None
    return _classifier_instance


def classify(query: str) -> SearchIntent:
    """
    Classify a query intent for global search.

    Returns TRIGGER_AI as a safe default if the model is unavailable,
    so the pipeline never silently drops a valid student question.
    """
    classifier = _get_classifier()
    if classifier is None:
        return SearchIntent.TRIGGER_AI
    return classifier.classify(query)
