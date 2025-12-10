generate_user_question_prompt = """
**Purpose:** Generate verification questions to determine whether a student truly understands and wrote their submitted code.

## Inputs

* **`task_template`**: The original exercise template
* **`task_description`**: Full exercise text, including optional tasks and optional diagrams in PlantUML sections recognizable by "@startuml" and "@enduml"
* **`student_submission`**: The student’s submitted code
* **`conversation_history`**: All previously asked questions and received answers

## Rules

### 1. The question must be about the student’s own code

* Identify which parts of the code were written by the student.
* Base your question only on student-written elements.
* Do not ask about boilerplate, template code, or framework code.

### 2. Do NOT ask about optional tasks

* Detect parts labeled as optional, bonus, extra, advanced, etc.
* Avoid any question whose topic intersects these optional sections.

### 3. The question must be short

* Keep the question concise, clear, and max. 1–2 sentences.

### 4. The question must not be too easy

* Avoid trivial questions such as:

* “What does your function do?”
* “What is the name of this variable?”
* “Did you sort the list?”
* Prefer questions that require understanding of the implementation, e.g.:

* “Why do you update this variable inside the loop instead of before it?”
* “Explain the logic behind the condition in your second loop.”
* “How does your swapping mechanism ensure the array stays sorted?”

### 5. Ask about only one concept

* Focus on exactly one part of the implementation.
* Do not combine multiple topics.
* Avoid broad or open-ended questions.

### 6. Avoid repeating topics

* Use the `conversation_history`.
* Do not ask about code concepts that were covered in earlier questions.
* Move to a different line, block, or technique.

### 7. No hints, no explanations

* Generate only the question, without hints or commentary.

## Output Format

* Return a **single string** containing the question only.
"""


assess_user_answer_prompt = """
# Iris Student Prompting Mode Answer Assessment Instruction Prompt

**Purpose:** Assess whether a student’s answer is sufficient to determine if the submission was self-written or suspicious, and decide if follow-up questions are needed.

## Inputs

* **`question`**: The verification question that was asked
* **`student_answer`**: The answer provided by the student
* **`task_template`**: The original exercise template
* **`task_description`**: Full exercise text, including optional tasks
* **`student_submission`**: The student’s submitted code
* **`conversation_history`**: All previously asked questions and answers
* **`min_questions`**: Minimum number of questions to be asked per submission
* **`max_questions`**: Maximum number of questions to be asked per submission

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

  * **`verdict`**: one of `suspicious`, `insuspicious` or `follow_up_question`
  * **`reasoning`**: optional brief explanation of why the answer is sufficient or why follow-up is needed (max 1–2 sentences)

### 4. Constraints

* Only assess based on student-written code and given answers.
* Ignore optional tasks.

## Output Format

Return a JSON object with the following structure:

```json
{
  "verdict": "suspicious" | "insuspicious" | "follow_up_question",
  "reasoning": "<optional string, max 1-2 sentences>"
}
```
"""