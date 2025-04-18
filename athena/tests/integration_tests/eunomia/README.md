# Eunomia TestBench

## Overview

Eunomia TestBench is a specialized testing framework designed to evaluate how well artificial intelligence (AI) systems can provide feedback on student diagrams in software engineering courses. It as a quality control system for AI-powered teaching assistants that help grade and provide feedback on student work.

### What Problem Does It Solve?

In large university courses, reviewing and providing feedback on student diagrams (like UML diagrams that describe software systems) can be extremely time-consuming for instructors and teaching assistants. While AI systems can help by automatically providing feedback, we need to make sure this automated feedback is accurate and helpful. This is where Eunomia TestBench comes in - it systematically tests these AI systems to ensure they're giving good feedback.

### Key Features

- **Comprehensive Testing**: Tests AI feedback across many different diagram scenarios
- **Detailed Analysis**: Measures accuracy and consistency of AI feedback
- **Cost Tracking**: Monitors the computational costs of running AI feedback systems
- **Performance Metrics**: Measures response time
- **Clear Reporting**: Generates easy-to-understand reports about AI system performance
- **Flexible Configuration**: Supports testing different types of diagrams and feedback scenarios
- **Rapid Development Feedback**: Helps developers quickly assess changes to the AI feedback system
- **Diagnostic Insights**: Identifies specific areas where the AI system struggles

### Key Benefits

1. Rapid Iteration Testing: Quickly assess the impact of changes to your AI feedback system:
    - Test new LLM models
    - Evaluate different processing pipelines
    - Compare different prompt engineering approaches
    - Measure performance improvements

2. Detailed Diagnostics: Understand exactly where your system needs improvement:
    - Per-test-case performance metrics
    - Specific failure patterns
    - Response time measurements
    - Cost analysis per model and request

3. Development Insights: The system generates comprehensive reports showing:
    - Which types of diagram elements the AI struggles with
    - Where feedback is inconsistent
    - Response time bottlenecks
    - Cost implications of different approaches

## Testing Methodology

Testing Large Language Models (LLMs) in educational settings presents unique challenges. Their outputs can vary between runs, they're sensitive to subtle input changes, and they can express the same feedback in countless valid ways. Traditional evaluation methods struggle with this variability - comparing AI-generated feedback against reference solutions becomes problematic when multiple phrasings are equally valid, and it's challenging to define objective success criteria. While human evaluators could assess the quality of LLM feedback, this approach is time-consuming, expensive, and introduces its own inconsistencies as different evaluators may interpret the same feedback differently.
Eunomia TestBench overcomes these challenges through its innovative use of Structured Grading Instructions (SGIs). Rather than asking the LLM to generate freeform feedback, the system provides a carefully curated set of predefined instructions that cover different aspects of correctness and common errors. The LLM's task is to select the most appropriate instructions from this fixed set when analyzing student work. This transforms the evaluation from interpreting natural language into a clear-cut comparison of instruction IDs - did the LLM identify the correct issues or not? This automated approach allows for rapid, consistent testing at scale, enabling thousands of test cases to be evaluated in the time it would take a human to assess just a few.
This structured approach brings remarkable clarity to LLM evaluation. Each test case has specific expected instructions, and we can precisely measure how well the LLM's selections match these expectations. The system tracks accuracy rates, identifies patterns in missed issues, and enables direct comparisons between different LLM versions or configurations. While the underlying LLM remains non-deterministic, the structured nature of the inputs and outputs creates a reliable framework for assessment. This allows developers to systematically improve the system's feedback capabilities while giving educators confidence in the consistency and accuracy of the AI's evaluations, all without requiring constant human oversight or intervention.

### Example

To demonstrate how we evaluate LLM model performance, let's use an example focused on UML class diagram feedback. We'll create a test scenario called "project_management" that assesses the LLM's ability to provide accurate feedback on class diagrams.

Consider this problem statement for the project_management exercise:

"You are designing a simple project management tool. In this tool, a Project consists of multiple Task objects that detail individual units of work. Each Task is uniquely defined within the scope of its containing Project. If the Project is cancelled or deleted, all its Tasks should also be removed. Draw a UML class diagram that accurately reflects this relationship."

We start by creating a new scenario called project_management in the scenarios folder

```plaintext
scenario/
   ├── project_management/
   │   ├── manifest.yml
   │   ├── example_solution.json
   │   └── test_cases/
   │       └── association_instead_of_composition.json
   └── llm_cost.yml
```

- `manifest.yml:` Defines all configuration details for the project_management scenario
- `example_solution.json:` Contains a perfect reference solution as an Apollon UML diagram. This file is used only as a parameter for the feedback AI and not directly by the test bench.
- `test_cases Folder:` Contains all test case files representing student submissions that differ in specific ways from the perfect solution. Each test case introduces common mistakes for the AI to identify.
  - For instance, association_instead_of_composition.json includes a test case where the Project-Task relationship is modeled as a simple association rather than a composition. We want to test if the AI’s feedback will correctly flag this error.
- `llm_cost.yml:` Contains configuration details related to cost calculation for running the AI feedback system on each test case.

Next, we define grading criteria based on the problem description in the manifest.yml file:

```yml
server_url: ""
exercise:
    ...
criteria:
    - id: "classes"
      ...
    - id: "relationship_type"
      title: "Project-Task Relationship Correctness"
      instructions:
        - id: "relationship_correct"
          instruction_description: "A composition relationship from Project to Task is correctly modeled (solid diamond)."
          feedback: "Excellent! The Project-Task relationship is shown as a composition, indicating that Tasks depend entirely on the Project."
          credits: 1.0
  
        - id: "relationship_incorrect"
          instruction_description: "The Project-Task relationship is not shown as a composition (e.g., it's just an association or aggregation)."
          feedback: "This should be represented as a composition. Use a solid diamond on the Project side to show that Tasks cannot exist without the Project."
          credits: 0.0
    - id: "attributes"
      ...
    - id: "naming_format"
      ...

default_expected:
    - "classes_correct"
    - "relationship_correct"
    - "attributes_correct"
    - "naming_format_correct"

test_case_diffs:
    relationship_correct:
        "association_instead_of_composition": "relationship_incorrect"
```

In the `manifest.yml` file, we also define **default_expected** instructions. These represent the feedback we expect the AI feedback system to produce when given a perfect solution.

We then specify how each test case in `scenario/project_management/test_cases/` deviates from this perfect solution. For example, in the `association_instead_of_composition` test case, we still anticipate all of the default instructions, but instead of receiving `relationship_correct`, we expect the AI to return `relationship_incorrect`.

## Interpreting Results

When evaluating how well the AI system performs, Eunomia TestBench provides several key metrics. The most important metric is the test case score percentage, which indicates how closely the AI's feedback matched the expected instructions.

The test case score is calculated by giving double weight to instructions that are specifically being tested for in this test case (defined in test_case_diffs) and single weight to all other instructions, which helps focus the evaluation on whether the LLM correctly identified the main issue being tested. This weighted scoring approach is particularly important because LLMs tend to be "over-zealous" in finding additional errors (e.g., if testing for an extra diagram element, the LLM might correctly flag this but also deduct points for naming conventions on that extra element) - while this eagerness to find errors is actually preferable from a teaching perspective since it's better for the LLM to be too strict (allowing instructors to override) than to miss actual errors that would then go unflagged.

## Technical Details

The runtime logic is orchestrated by eval/main.py, which collects user input for scenario filtering and run naming, sets up directories, and configures LLM cost models from the llm_cost.yml file. The EvaluationRunner class (eval/models/entities/evaluation_runner.py) then loads scenario configurations, performs ID mapping for criteria and instructions (converting textual identifiers into numeric ones), and instantiates Scenario objects. Each Scenario includes its Exercise definition, criteria, expected instructions, and a list of ScenarioTestCase objects. The evaluate_scenario function (eval/core/scenario_evaluation.py) executes test cases in parallel, leveraging a ThreadPoolExecutor to handle concurrent requests. For each test case, run_test_case (eval/core/test_case_runner.py) attempts multiple retries if server requests fail, ensuring robustness against transient network issues.

After receiving feedback, Eunomia TestBench constructs TestCaseResult objects that reconcile expected and returned instructions, compute final scores, and determine if the test case was detected correctly. The scoring involves weighted calculations, especially emphasizing correctness on instructions that differ from the default scenario (i.e., the primary errors introduced for that particular test case). By integrating the LLMCostCalculator (eval/utils/llm_cost_calculator.py), the system also determines token consumption costs. Results are then aggregated into ScenarioResult objects, enabling retrieval of summary statistics such as total cases, fully correct outcomes, score matches, and cost overviews.

## Viewing Results

After executing the evaluation, results are generated in the `results/` directory, following this structure:

```plaintext
results/
├── run_name/
│   ├── scenario_name/
│   │   ├── tables/
│   │   │   ├── scenario_summary.csv
│   │   │   └── test_case_results.csv
│   │   ├── test_cases/
│   │   │   └── [individual test case results].json
│   │   └── scenario_results.json
```

Where:

- **run_name**: A user-defined label for the current batch of evaluations.
- **scenario_name**: The name of the scenario being tested (e.g., `project_management`).

Within each scenario directory, multiple output files are generated, providing insights at various levels of detail.

---

### Output Files

#### scenario_summary.csv

**Location:** `results/run_name/scenario_name/tables/scenario_summary.csv`  
**Purpose:** Provides a high-level summary of scenario evaluation metrics.

| Metric                                   | Value     |
|-------------------------------------------|-----------|
| Total Cases                               | *Number of test cases executed for the scenario.* |
| Fully Correct Cases                       | *Number of test cases where the returned instructions matched perfectly.* |
| Score Matched Count                       | *Number of test cases where the final score matched the expected score.* |
| Average Test Case Score                   | *Average percentage score across all test cases.* |
| Correctly Detected Test Cases / Total Cases | *A ratio of how many test cases were correctly detected versus total cases.* |
| Total Cost                                | *Sum of all costs from all test cases.* |
| Average Cost                              | *Average cost per test case.* |
| Average Request Time (s)                  | *Average processing time per test case request.* |

---

#### scenario_results.json

**Location:** `results/run_name/scenario_name/scenario_results.json`  
**Purpose:** A JSON representation of the scenario-level summary, similar to `scenario_summary.csv` but structured for programmatic consumption.

**Sample Fields:** Same as scenario_summary.csv but in json form

---

#### test_case_results.csv

**Location:** `results/run_name/scenario_name/tables/test_case_results.csv`  
**Purpose:** Lists key performance indicators for each test case in a scenario, allowing quick scanning for patterns or problematic areas.

| Test Case                 | Test Case Detected Correctly | Test Case Score (%) | Expected Points | Total Returned Points | Cost     | Request Time (s) | Wrong < Points | Wrong > Points |
|---------------------------|------------------------------|---------------------|----------------|-----------------------|----------|------------------|----------------|----------------|
| *Name of the test case*   | *Yes/No if the test was correctly identified* | *Percentage of expected score achieved* | *Points expected from correct instructions* | *Points awarded by the AI* | *Monetary cost for this test case* | *Time taken for feedback request* | *Count of instructions where fewer points than expected were awarded* | *Count of instructions where more points than expected were awarded* |

---

#### Individual Test Case Results ([individual test case results].json)

**Location:** `results/run_name/scenario_name/test_cases/[test_case_name].json`  
**Purpose:** Provides a detailed breakdown per test case, including expected vs. returned instructions, scoring, cost details, and raw feedback.

**Example:**

```json
{
    "test_case": "unlabelled_activity",
    "expected_score": 8.0,
    "returned_score": 9.0,
    "test_case_detected_correctly": false,
    "test_case_score_percent": 83.33333333333334,
    "cost": {
        "total_cost": 0.501525,
        "total_input_cost": 0.07276500000000001,
        "total_output_cost": 0.42876,
        "details": [
            {
                "llm": "o1-preview-2024-09-12",
                "input_cost": 0.07276500000000001,
                "output_cost": 0.42876,
                "total": 0.501525
            }
        ]
    },
    "criteria_results": [
        {
            "criterion_id": 7,
            "criterion_textual_id": "naming_format",
            "mismatch_pairs": [
                {
                    "expected": {
                        "id": 14,
                        "textual_id": "naming_format_incorrect",
                        "credits": 0.0,
                        "instructionDescription": "One or more tasks do not follow the Verb-Object format."
                    },
                    "received": {
                        "id": 13,
                        "textual_id": "naming_format_correct",
                        "credits": 1.0,
                        "instructionDescription": "All tasks use 'Verb Object' naming.",
                        "feedbackDescription": "Task names follow the correct naming scheme."
                    }
                }
            ],
            "missing_instructions": [],
            "extra_instructions": []
        }
    ],
    "feedback": [
        {
            "id": 6169,
            "title": "Representation of Participants",
            "description": "Great! Both participants are correctly modeled.",
            "credits": 1.0,
            "structured_grading_instruction_id": 1,
            "is_graded": false,
            "meta": {},
            "exercise_id": 1330572582,
            "submission_id": 17,
            "element_ids": [],
            "reference": null
        }
        ...
    ]
}
```

---

### Legend: What Each Means

- **Test Case:** The name of the test case file that was evaluated.  
- **Test Case Detected Correctly:** Indicates if the AI correctly recognized the introduced error or deviation in the test case.  
- **Test Case Score (%):** How close the returned instructions matched the expected instructions, expressed as a percentage. See the "Interpreting Results" section for more details.
- **Expected Points:** The total points that would be awarded if the test case was perfectly solved.  
- **Total Returned Points:** The actual points the AI assigned, based on its returned instructions.  
- **Cost:** The computed monetary cost to evaluate this single test case, derived from token usage.  
- **Request Time (s):** How long it took for the AI system to return feedback for this test case.  
- **Wrong < Points:** The count of instructions where the AI awarded fewer points than expected, indicating missed opportunities or stricter-than-expected grading.  
- **Wrong > Points:** The count of instructions where the AI awarded more points than expected, indicating overly lenient grading or misunderstanding.  
- **criterion_id:** Internal numeric ID of the criterion.  
- **criterion_textual_id:** Human-readable ID of the criterion.  
- **mismatch_pairs:** Pairs of instructions showing where the expected instruction was replaced by a different (incorrect) instruction.  
- **missing_instructions:** Instructions that should have been present but were not returned by the AI.  
- **extra_instructions:** Instructions that the AI returned but were not expected.  
- **feedback:** The actual feedback items generated by the AI, including title, description, credits, and any metadata. This shows exactly what the student would see.