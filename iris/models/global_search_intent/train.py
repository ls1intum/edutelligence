#!/usr/bin/env python3
"""
Train SetFit intent classifier → export INT8-quantized ONNX model.
Pipeline:
  1. Load artemis_intent_dataset.csv
  2. Fine-tune paraphrase-multilingual-MiniLM-L12-v2 with SetFit
  3. Export backbone to ONNX
  4. Apply O3 graph optimisation (saved separately; not used for quantisation)
  5. Apply dynamic INT8 quantisation on base graph (O3 ops break the quantiser)
  6. Save everything to intent_model_onnx_quantized/
"""

import json
import subprocess  # nosec B404
import sys
from pathlib import Path

# ── 0. Install dependencies ───────────────────────────────────────────────────
print("=== Installing dependencies ===")
pkgs = [
    "setfit",
    "onnxruntime",
    "optimum[onnxruntime]",
    "pandas",
    "scikit-learn",
    "datasets",
    "joblib",
]
for pkg in pkgs:
    subprocess.check_call(  # nosec B603
        [sys.executable, "-m", "pip", "install", pkg, "-q", "--upgrade"],
        stdout=subprocess.DEVNULL,
    )
print("Dependencies installed.\n")

import joblib  # noqa: E402
import pandas as pd  # noqa: E402
from datasets import Dataset  # noqa: E402
from setfit import SetFitModel, Trainer, TrainingArguments  # noqa: E402
from sklearn.model_selection import train_test_split  # noqa: E402

# ── 2. Load dataset ───────────────────────────────────────────────────────────
print("=== Loading dataset ===")
df = pd.read_csv("models/global_search_intent/training_data.csv")
df["label"] = (df["Intent"] == "trigger_ai").astype(int)
print(f"  Total rows   : {len(df)}")
print(f"  trigger_ai   : {df["label"].sum()}")
print(f"  skip_ai      : {(df["label"] == 0).sum()}")

# Stratified split first so the eval set is representative of the full distribution.
# Then balance only the training portion by capping to the minority class size.
df_train_raw, df_eval = train_test_split(
    df, test_size=0.15, stratify=df["label"], random_state=42
)
minority_size = df_train_raw["label"].value_counts().min()
df_train = pd.concat(
    [
        df_train_raw[df_train_raw["label"] == cls].sample(
            n=minority_size, random_state=42
        )
        for cls in df_train_raw["label"].unique()
    ]
).reset_index(drop=True)
print(f"  Training on  : {len(df_train)} rows ({minority_size} per class)")
print(f"  Evaluating on: {len(df_eval)} rows")
print(f"    trigger_ai : {df_eval["label"].sum()}")
print(f"    skip_ai    : {(df_eval["label"] == 0).sum()}\n")

train_dataset = Dataset.from_pandas(
    df_train[["Query", "label"]].rename(columns={"Query": "text"})
)
eval_dataset = Dataset.from_pandas(
    df_eval[["Query", "label"]].rename(columns={"Query": "text"})
)

# ── 3. Train SetFit ───────────────────────────────────────────────────────────
print("=== Training SetFit model ===")
BASE_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

model = SetFitModel.from_pretrained(BASE_MODEL)  # pylint: disable=not-callable

training_args = TrainingArguments(
    batch_size=32,
    num_epochs=1,
    num_iterations=20,
    eval_strategy="no",
    save_strategy="no",
)

trainer = Trainer(
    model=model,
    args=training_args,
    train_dataset=train_dataset,
    eval_dataset=eval_dataset,
    metric="accuracy",
    column_mapping={"text": "text", "label": "label"},
)

trainer.train()
metrics = trainer.evaluate()
print(f"\n  Eval metrics: {metrics}\n")

# ── 4. Extract and save the HF transformer backbone ──────────────────────────
print("=== Saving transformer backbone ===")
BACKBONE_DIR = Path("models/global_search_intent/backbone")
BACKBONE_DIR.mkdir(exist_ok=True)

# model.model_body is a SentenceTransformer; module[0] is the Transformer layer
st = model.model_body
transformer_module = st[0]  # sentence_transformers.models.Transformer
hf_model = transformer_module.auto_model
tokenizer = transformer_module.tokenizer

hf_model.save_pretrained(str(BACKBONE_DIR))
tokenizer.save_pretrained(str(BACKBONE_DIR))

# Persist pooling config so the inference wrapper knows how to aggregate.
# Read dimension from the HF model config (API-stable across ST versions).
pooling_config = {
    "word_embedding_dimension": hf_model.config.hidden_size,
    "pooling_mode_mean_tokens": True,  # MiniLM always uses mean pooling
    "pooling_mode_cls_token": False,  # nosec B105
}
(BACKBONE_DIR / "pooling_config.json").write_text(json.dumps(pooling_config, indent=2))
print(f"  Backbone saved to {BACKBONE_DIR}\n")

# ── 5. Export backbone to base ONNX ──────────────────────────────────────────
print("=== Exporting to base ONNX ===")
from optimum.onnxruntime import (  # noqa: E402
    ORTModelForFeatureExtraction,
    ORTOptimizer,
    ORTQuantizer,
)
from optimum.onnxruntime.configuration import (  # noqa: E402
    AutoQuantizationConfig,
    OptimizationConfig,
    QuantizationConfig,
)

ONNX_BASE_DIR = Path("models/global_search_intent/onnx_base")
ort_model = ORTModelForFeatureExtraction.from_pretrained(str(BACKBONE_DIR), export=True)
ort_model.save_pretrained(str(ONNX_BASE_DIR))
tokenizer.save_pretrained(str(ONNX_BASE_DIR))
print(f"  Base ONNX saved to {ONNX_BASE_DIR}\n")

# ── 6. O3 graph optimisation ──────────────────────────────────────────────────
print("=== Applying O3 graph optimisation ===")
ONNX_OPT_DIR = Path("models/global_search_intent/onnx_optimized")
optimizer = ORTOptimizer.from_pretrained(str(ONNX_BASE_DIR))
opt_config = OptimizationConfig(
    optimization_level=99,  # ORT_ENABLE_ALL (O3 equivalent)
    enable_transformers_specific_optimizations=True,
    enable_gelu_approximation=True,
)
optimizer.optimize(
    save_dir=str(ONNX_OPT_DIR),
    optimization_config=opt_config,
)
tokenizer.save_pretrained(str(ONNX_OPT_DIR))
print(f"  Optimised ONNX saved to {ONNX_OPT_DIR}\n")

# ── 7. Dynamic INT8 quantisation ──────────────────────────────────────────────
print("=== Applying dynamic INT8 quantisation ===")
FINAL_DIR = Path("models/global_search_intent/onnx")
FINAL_DIR.mkdir(exist_ok=True)

quantizer = ORTQuantizer.from_pretrained(str(ONNX_BASE_DIR))

# Try platform-specific configs, fall back to a generic dynamic INT8 config
try:
    import platform

    if platform.machine() == "arm64":
        qconfig = AutoQuantizationConfig.arm64(is_static=False, per_channel=False)
        print("  Using ARM64 quantisation config")
    else:
        qconfig = AutoQuantizationConfig.avx2(is_static=False, per_channel=False)
        print("  Using AVX2 quantisation config")
except Exception as e:
    print(f"  Platform-specific config unavailable ({e}), using generic INT8 config")
    from onnxruntime.quantization import QuantType

    qconfig = QuantizationConfig(  # pylint: disable=no-value-for-parameter
        is_static=False,
        per_channel=False,
        weights_dtype=QuantType.QInt8,
        activations_dtype=QuantType.QUInt8,
        operators_to_quantize=["MatMul", "Add", "Gather"],
    )

quantizer.quantize(
    save_dir=str(FINAL_DIR),
    quantization_config=qconfig,
)
# Tokenizer is loaded from HuggingFace Hub at runtime — do not commit it.
print(f"  Quantised ONNX saved to {FINAL_DIR}\n")

# ── 8. Save classifier head alongside ONNX files ─────────────────────────────
print("=== Saving classifier head ===")
joblib.dump(model.model_head, str(FINAL_DIR / "model_head.joblib"))
(BACKBONE_DIR / "pooling_config.json").read_text()  # sanity check readable

# Copy pooling config so the inference dir is self-contained
(FINAL_DIR / "pooling_config.json").write_text(json.dumps(pooling_config, indent=2))

# Write a small metadata file for the inference wrapper
meta = {
    "base_model": BASE_MODEL,
    "task": "binary_classification",
    "labels": {"0": "skip_ai", "1": "trigger_ai"},
    "quantization": "dynamic INT8",
    "optimization_level": "O3",
    "onnx_file": next((f.name for f in FINAL_DIR.glob("*.onnx")), "unknown"),
    "eval_metrics": {k: float(v) for k, v in metrics.items()},
}
(FINAL_DIR / "meta.json").write_text(json.dumps(meta, indent=2))

# ── 9. Summary ────────────────────────────────────────────────────────────────
files = sorted(FINAL_DIR.iterdir())
print("=== Done! ===")
print(f"Output directory : {FINAL_DIR.resolve()}")
print("Files:")
for f in files:
    size_kb = f.stat().st_size / 1024
    print(f"  {f.name:<45}  {size_kb:>8.1f} KB")
