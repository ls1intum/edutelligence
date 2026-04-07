---
title: Similarity Analysis
---

Similarity analysis is a critical component of Athena's testing
framework that enables the detection of performance degradation in LLM
models over time. This analysis uses BERTScore metric for semantic
similarity comparison and provides possibility for quality monitoring.

# Overview

Quality drift analysis addresses the challenge of maintaining consistent
LLM performance. LLM models evolve or as input data changes, the quality
of generated feedback may drift from established baselines. This
analysis system provides:

- **Quality Monitoring**: Continuous assessment of model performance
- **Semantic Similarity Analysis**: BERTScore-based comparison of
  feedback quality
- **Baseline Management**: Creation and maintenance of performance
  baselines
- **Drift Detection**: Identification of performance degradation
  patterns
- **Historical Tracking**: Long-term performance trend analysis

# System Architecture

The quality drift analysis system consists of several key components:

``` text
Quality Drift Analysis System
├── Baseline Generation
│   ├── Exercise Sampling
│   ├── Submission Selection
│   └── Feedback Generation
├── Analysis Execution
│   ├── Model Comparison
│   ├── BERTScore Calculation
│   └── Credit Difference Analysis
└── Reporting
    ├── Quality Metrics
    ├── History
```

# Baseline Creation Process

The baseline creation process establishes reference performance metrics
for comparison:

## Step 1: Exercise Sampling

**Script**: `sample_exercises.py`

**Purpose**: Select 10-12 submissions per exercise covering different
score ranges

**Example Usage**:

``` bash
# From athena/tests/modules/text/module_text_llm/real/
python sample_exercises.py
```

**Output**: Sampled exercise data with submissions ready for baseline
generation.

## Step 2: Baseline Feedback Generation

**Process**:

1.  **Model Configuration**: Use a reference LLM model (typically a
    stable, well-performing version)
2.  **Feedback Generation**: Generate feedback for all sampled
    submissions
3.  **Quality Validation**: Ensure baseline feedback meets quality
    standards
4.  **Storage**: Store baseline feedback with timestamps in the sampled
    data

## Step 3: Baseline Storage

**Format**: Baseline data is stored within the sampled exercise JSON
files:

``` json
{
"id": 6715,
"title": "Software Design Patterns",
"submissions": 
    {
        "id": 201,
        "text": "Student submission text...",
        "baseline_feedback": {
            "timestamp": "2024-09-15T10:30:00Z",
            "model_version": "gpt-4o-2025-09-01",
            "feedback": [
                {
                    "title": "Pattern Identification",
                    "description": "Good identification of Singleton pattern",
                    "credits": 2.0
                }
            ],
        }
    }
}
```

# Quality Drift Analysis Execution

The analysis process compares current model performance against
established baselines:

## Step 1: Model Comparison Setup

**Script**: `run_quality_drift_analysis.py`

**Purpose**: Execute comprehensive quality drift analysis

**Example Usage**:

``` python
# From athena/modules/text/module_text_llm with module's venv:
python ../../../tests/modules/text/module_text_llm/real/run_quality_drift_analysis.py
```

## Step 2: BERTScore Calculation

**BERTScore Integration**: BERTScore provides semantic similarity
analysis between generated and baseline feedback:

``` python
from bert_score import score

def calculate_bertscore_similarity(self, baseline_texts: List[str], test_texts: List[str]) -> Dict[str, float]:

        precision, recall, f1 = bert_score(
            test_texts_trimmed, 
            baseline_texts_trimmed, 
            lang='en', 
            verbose=False
        )

        # Convert to numpy arrays and handle the mean calculation properly
        precision_np = precision.cpu().numpy() if hasattr(precision, 'cpu') else np.array(precision)
        recall_np = recall.cpu().numpy() if hasattr(recall, 'cpu') else np.array(recall)
        f1_np = f1.cpu().numpy() if hasattr(f1, 'cpu') else np.array(f1)

        return {
            "precision": float(np.mean(precision_np)),
            "recall": float(np.mean(recall_np)),
            "f1": float(np.mean(f1_np))
        }
```

**Metrics Calculated**:

- **Precision**: How much of the generated feedback is relevant
- **Recall**: How much of the baseline feedback is captured
- **F1 Score**: Harmonic mean of precision and recall
- **Semantic Similarity**: Overall quality similarity score

## Step 3: Credit Difference Analysis

Compare credit assignments between generated and baseline feedback:

``` python
def calculate_credit_drift(self, baseline_feedbacks: List[Dict], test_feedbacks: List[Dict]) -> Dict[str, float]:
    """Calculate credit drift between baseline and test feedbacks."""
    if not baseline_feedbacks or not test_feedbacks:
        return {"mean_drift": 0.0, "std_drift": 0.0, "max_drift": 0.0}

    baseline_credits = [feedback["credits"] for feedback in baseline_feedbacks]
    test_credits = [feedback["credits"] for feedback in test_feedbacks]

    # Use the minimum length to avoid padding issues
    min_len = min(len(baseline_credits), len(test_credits))
    baseline_credits_trimmed = baseline_credits[:min_len]
    test_credits_trimmed = test_credits[:min_len]

    differences = [abs(b - t) for b, t in zip(baseline_credits_trimmed, test_credits_trimmed)]

    if not differences:
        return {"mean_drift": 0.0, "std_drift": 0.0, "max_drift": 0.0}

    return {
        "mean_drift": float(np.mean(differences)),
        "std_drift": float(np.std(differences)),
        "max_drift": float(np.max(differences))
    }
```

# Analysis Results and Reporting

The analysis generates comprehensive reports stored in
`quality_drift_report.json`:

## Report Structure

``` json
"exercises": {
"14676": {
  "timestamp": "2025-09-28 16:46:07",
  "exercise_id": 14676,
  "exercise_file": "sampled_exercise-14676.json",
  "baseline": {
    "model": "azure_openai_gpt-4o",
    "generated_at": "2025-08-28T10:54:05.805981"
  },
  "thresholds": {
    "min_bertscore_f1": 0.8,
    "max_avg_credit_drift": 3.0
  },
  "model_results": {
    "gpt-4o": {
      "avg_bertscore_f1": 0.871,
      "avg_credit_drift": 0.79,
      "passed": true
    },
    "gpt-4-turbo": {
      "avg_bertscore_f1": 0.872,
      "avg_credit_drift": 0.64,
      "passed": true
    },
    "gpt-35-turbo": {
      "avg_bertscore_f1": 0.876,
      "avg_credit_drift": 0.72,
      "passed": true
    }
  }
}
}
```

## Check against the thresholds

``` python
baseline_info = analysis_results.get("baseline_info", {})
model_comparison = analysis_results.get("model_comparison", {})
thresholds = analysis_results.get("thresholds", {"min_bertscore_f1": MIN_BERTSCORE_F1, "max_avg_credit_drift": MAX_MEAN_CREDIT_DRIFT})

total_models = len(model_comparison)
passed_models = sum(1 for _, res in model_comparison.items() if res.get("passed"))
print(f"Tests: {passed_models}/{total_models} passed
 (min F1 >= {thresholds['min_bertscore_f1']}, max credit drift <= {thresholds['max_avg_credit_drift']})")
```

# Usage Guidelines

## Running Quality Drift Analysis

**Prerequisites**:

1.  **Baseline Data**: Ensure baseline feedback has been generated
2.  **Model Configuration**: Configure target models for analysis
3.  **Environment Setup**: Activate appropriate virtual environment
4.  **Dependencies**: Install required packages (bert-score, etc.)

**Execution Steps**:

1.  **Navigate to Module Directory**:

    ``` bash
    cd athena/modules/text/module_text_llm
    ```

2.  **Activate Module Environment**:

    ``` bash
    source .venv/bin/activate
    ```

3.  **Run Analysis**:

    ``` bash
    python ../../../tests/modules/text/module_text_llm/real/run_quality_drift_analysis.py
    ```

4.  **Regenerate Baseline** (if needed):

    ``` bash
    python ../../../tests/modules/text/module_text_llm/real/run_quality_drift_analysis.py --regenerate-baseline
    ```

The same process applies to the other modules.

## Sampling New Submissions

To update the test data with new submissions:

``` bash
# From athena/tests/modules/text/module_text_llm/real/
python sample_exercises.py
```
