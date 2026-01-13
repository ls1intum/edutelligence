assess_user_answer_prompt = """
# Iris Student Prompting Mode Answer Assessment Instruction Prompt

**Purpose:** Assess whether a student’s answer is sufficient to determine if the submission was self-written or suspicious, and decide if follow-up questions are needed.

## Inputs

* **`question`**: The verification question that was asked: {question}
* **`student_answer`**: The answer provided by the student: {answer}
* **`task_template`**: The original exercise template: {template}
* **`task_description`**: Full exercise text, including optional tasks: {task}
* **`student_submission`**: The student’s submitted code: {files}
* **`conversation_history`**: All previously asked questions and answers: {chat_history}
* **`min_questions`**: Minimum number of questions to be asked per submission: {min_questions}
* **`max_questions`**: Maximum number of questions to be asked per submission: {max_questions}

## Rules

### 1. Evaluate sufficiency

* Determine whether the student’s answer is sufficient to decide if the submission is self-written.
* If the answer is clear and demonstrates understanding of the student-written code, it may be marked as sufficient.
* If the answer is obviously demonstrates a lack of understanding, it may be marked as insufficient.
* If the answer is ambiguous or incomplete, a follow-up question may be needed.

### 2. Decide if follow-up questions are needed

* Consider the number of questions already asked (`conversation_history`).
* Ensure that the total number of questions remains between `min_questions` and `max_questions`.
* If insufficient and questions are still allowed, return `follow_up_question`
* If amount of questions asked is still below `min_questions`, return `follow_up_question`
* If the amount of questions is already at `max_questions`, decide between `sufficient` and `insufficient` in your verdict.

### 3. Provide clear assessment

* For each answer, return a structured assessment including:

  * **`verdict`**: one of `suspicious`, `unsuspicious` or `follow_up_question`
  * **`reasoning`**: optional brief explanation of why the answer is sufficient or why follow-up is needed (max 1–2 sentences)

### 4. Constraints

* Only assess based on student-written code and given answers.
* Ignore optional tasks.

## Output Format

Return a JSON object with the following structure:

```json
{
  "verdict": "suspicious" | "unsuspicious" | "follow_up_question",
  "reasoning": "<optional string, max 1-2 sentences>"
}
```
"""