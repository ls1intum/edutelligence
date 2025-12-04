---
title: Evaluation Data Format
---

This document describes the structure of the evaluation data format used
in Athena. It covers various exercise types, their submissions, and
feedback types. The following sections provide detailed explanations and
examples. Please refer to the example data provided in the
<span class="title-ref">playground/data/example/</span> directory for
examples, if the structure is unclear contact the Athena team.

# Exercise Data Structure

Each exercise is represented as a JSON object with the following fields:

- **id**: Unique identifier for the exercise.
- **course_id**: Identifier for the course to which the exercise
  belongs.
- **title**: Title of the exercise.
- **type**: Type of the exercise (e.g., "programming", "text",
  "modeling").
- **max_points**: Maximum points achievable for the exercise.
- **bonus_points**: Bonus points achievable for the exercise.
- **problem_statement**: Detailed description of the problem to be
  solved.
- **grading_instructions**: Instructions on how the exercise should be
  graded (can also be <span class="title-ref">null</span> in favor of
  structured grading instructions, i.e.
  <span class="title-ref">grading_criteria</span>).
- **grading_criteria**: Structured grading instructions on how the
  exercise should be graded (are not required)
- **solution_repository_uri**: URI for the solution repository (for
  programming exercises).
- **template_repository_uri**: URI for the template repository (for
  programming exercises).
- **tests_repository_uri**: URI for the tests repository (for
  programming exercises).
- **meta**: Additional metadata for the exercise.
- **submissions**: List of submissions for the exercise.

# Example Exercise Data

1.  **Programming Exercise**

``` json
{
    "id": 1,
    "course_id": 101,
    "title": "Sorting Algorithms",
    "type": "programming",
    "max_points": 15,
    "bonus_points": 2,
    "problem_statement": "Implement different sorting algorithms and choose them based on runtime conditions...",
    "grading_instructions": "1. **QuickSort.java** - 5 points\n2. **MergeSort.java** - 5 points\n3. **HeapSort.java** - 5 points...",
    "programming_language": "java",
    "solution_repository_uri": "{{exerciseDataUrl}}/solution.zip",
    "template_repository_uri": "{{exerciseDataUrl}}/template.zip",
    "tests_repository_uri": "{{exerciseDataUrl}}/tests.zip",
    "meta": {},
    "submissions": [
        {
            "id": 101,
            "repository_uri": "{{exerciseDataUrl}}/submissions/101.zip",
            "meta": {},
            "feedbacks": [
                {
                    "id": 201,
                    "title": "File QuickSort.java at line 22",
                    "description": "The sort method is not implemented correctly.",
                    "file_path": "QuickSort.java",
                    "line_start": 22,
                    "line_end": null,
                    "credits": -3.0,
                    "meta": {}
                }
            ]
        },
        {
            "id": 102,
            "repository_uri": "{{exerciseDataUrl}}/submissions/102.zip",
            "meta": {}
        }
    ]
}
```

2.  **Text Exercise with General Grading Instructions**

``` json
{
    "id": 2,
    "course_id": 102,
    "title": "Describe Your Favorite Book",
    "type": "text",
    "max_points": 10,
    "bonus_points": 1,
    "problem_statement": "Write a brief essay about your favorite book and why you like it.",
    "grading_instructions": "Full points if the essay is well-structured and provides clear reasons for liking the book.",
    "example_solution": "My favorite book is 'To Kill a Mockingbird' because...",
    "meta": {},
    "submissions": [
        {
            "id": 201,
            "text": "My favorite book is '1984' by George Orwell because...",
            "meta": {},
            "feedbacks": [
                {
                    "id": 301,
                    "title": "Content Feedback",
                    "description": "Good job! However, you could elaborate more on the themes of the book.",
                    "index_start": null,
                    "index_end": null,
                    "credits": 8.0,
                    "meta": {}
                }
            ]
        },
        {
            "id": 202,
            "text": "I like 'Pride and Prejudice' because...",
            "meta": {}
        }
    ]
}
```

3.  **Text Exercise with Structured Grading Instructions**

``` json
{
    "id": 3,
    "course_id": 103,
    "title": "Gene Prediction Strategies",
    "type": "text",
    "max_points": 10,
    "bonus_points": 0,
    "problem_statement": "What are the three strategies for gene prediction? Give an example for each.",
    "example_solution": "The three strategies for gene prediction are content-based, site-based, and comparative...",
    "meta": {},
    "submissions": [
        {
            "id": 301,
            "text": "Three strategies for gene prediction are:...",
            "language": "ENGLISH",
            "meta": {}
        },
        {
            "id": 302,
            "text": "Gene prediction strategies include:...",
            "language": "ENGLISH",
            "meta": {}
        }
    ],
    "grading_criteria": [
        {
            "id": 10,
            "title": "Content-based Strategy",
            "structured_grading_instructions": [
                {
                    "id": 19,
                    "credits": 3.3,
                    "feedback": "Correct identification of content-based strategy.",
                    "grading_scale": "Correct Identification",
                    "instruction_description": "Identification of content-based strategy."
                },
                {
                    "id": 20,
                    "credits": 0.0,
                    "feedback": "Incorrect or no identification of content-based strategy.",
                    "grading_scale": "Incorrect Identification",
                    "instruction_description": "Incorrect or no identification."
                }
            ]
        },
        {
            "id": 11,
            "title": "Content-based Example",
            "structured_grading_instructions": [
                {
                    "id": 21,
                    "credits": 3.3,
                    "feedback": "Correct example for content-based strategy.",
                    "grading_scale": "Correct Example",
                    "instruction_description": "Example for content-based strategy (e.g., ORFs, codon usage)."
                },
                {
                    "id": 22,
                    "credits": 0.0,
                    "feedback": "Incorrect or no example for content-based strategy.",
                    "grading_scale": "Incorrect Example",
                    "instruction_description": "Incorrect or no example."
                }
            ]
        }
    ]
}
```

4.  **Modeling Exercise**

``` json
{
    "id": 4,
    "course_id": 104,
    "title": "Create a UML Diagram",
    "type": "modeling",
    "max_points": 20,
    "bonus_points": 0,
    "problem_statement": "Create a UML class diagram for a library management system.",
    "grading_instructions": "1 point for each correct class and relationship.",
    "example_solution": "{}",
    "meta": {},
    "submissions": [
        {
            "id": 401,
            "text": "UML Diagram for Library Management System",
            "model": "{\"version\":\"2.0\",\"type\":\"UML\",\"elements\":{},\"relationships\":{}}",
            "meta": {}
        },
        {
            "id": 402,
            "text": "Another UML Diagram",
            "model": "{\"version\":\"2.0\",\"type\":\"UML\",\"elements\":{},\"relationships\":{}}",
            "meta": {}
        }
    ]
}
```

# Data Fields Explanation

- **Submissions**: Each submission is an object containing:  
  - **id**: Unique identifier for the submission.
  - **repository_uri** (for programming exercises): URI for the
    submission repository.
  - **text** (for text exercises): The text content of the submission.
  - **model** (for modeling exercises): The serialized model data.
  - **language** (for text exercises): Language of the submission.
  - **meta**: Additional metadata for the submission.
  - **feedbacks**: List of feedback objects associated with the
    submission.

- **Feedbacks**: Each feedback object contains:  
  - **id**: Unique identifier for the feedback.
  - **title**: Title of the feedback.
  - **description**: Detailed feedback description.
  - **file_path** (for programming exercises): Path to the file the
    feedback is related to.
  - **line_start** (for programming exercises): Start line number of the
    feedback.
  - **line_end** (for programming exercises): End line number of the
    feedback.
  - **index_start** (for text exercises): Start index of the feedback.
  - **index_end** (for text exercises): End index of the feedback.
  - **credits**: Points awarded or deducted based on the feedback.
  - **meta**: Additional metadata for the feedback.

- **Grading Criteria** (for structured grading instructions): Each grading criterion contains:  
  - **id**: Unique identifier for the grading criterion.
  - **title**: Title of the grading criterion.
  - **structured_grading_instructions**: List of structured grading
    instructions associated with the criterion.

- **Structured Grading Instructions**: Each structured grading instruction contains:  
  - **id**: Unique identifier for the grading instruction.
  - **credits**: Points awarded for the instruction.
  - **feedback**: Feedback provided based on the instruction.
  - **grading_scale**: Scale used for grading (e.g., "Correct
    Identification").
  - **instruction_description**: Detailed description of the grading
    instruction.

This structure ensures that the evaluation data is well-organized and
easy to understand for both automated systems and human evaluators. Each
exercise type has specific fields tailored to its requirements, making
the data format flexible and comprehensive.
