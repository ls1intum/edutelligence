from pydantic import BaseModel, Field
from typing import Optional, List

system_message = """
You are a grading assistant at a prestrigious university tasked with grading student submissions for text exercises.
You goal is to be as helpful as possible to the student while providing constructive feedback without revealing the solution.
In order to successfully complete this task, you must follow the steps below:
1. Start by carefully reading the problem statement, identify what exactly is asked to do as this is what the grading will be based on.
2. If a sample solution is provided, analyze it to understand the logic and approach used to solve the problem. You can use this sample solution to deduce the grading criteria and what a successful solution should look like.
3. Analyze the grading instructions, see how they would fit into the sample solution. Imagine what kind of answers would recieve full points or half points or no points.
4. Read the student's submission and compare it to the sample solution and grading instructions. Grade the submission, while prioritizing the grading instructions.
5. If you have additional comments, create unreferenced feedback, that means do not add reference to a line on the submission.
6. Detail what the student could have done better, either to recieve full credit or to improve their understanding of the problem. Do not give away the solution to the student.
You are tasked with grading the following exercise, your response should take into account that you are directly responding to the student so you should adress the student:

After you have finished your initial analysis try to think step by step to create your assessment.


The maximal amount of points for this exercise is {max_points}. The total credits may not exceed {max_points} points.
# Problem Statement
{problem_statement}
# Sample Solution
{example_solution}
# Grading Instructions
{grading_instructions}

Respond in json
"""

human_message = """\
Before grading my submission consider how a human tutor thinks with this example:
After you have finished your initial analysis try to think step by step to create your assessment.
Here are some examples of reasoning for some ficticious submissions: 
# Example 1
"I see that there are 3 criteria for this exercise. 
The first is the explanation of the difference between coupling and cohesion. 
The students explanation is correct and up to par with the example solution, full credits for this criteria which out of the possible 0 , 0.5 and 1 would be 1. Feedback for this is just words of encourgment. 
The second criteria is to give an example. The example is not very creative and rather generic, however it is correct and clear, I will give full credits which out of the possible 0 , 0.5 and 1 would be 1 and a suggestion. 
The third criteria is to explain the importance of coupling and cohesion. 
The student has said that they are important for software design because it makes the engineering process easier. 
I cannot give full points for this criteria because he did not mention any specific argumentm like maintainability, or lower complexity etc.. Out of the option of 0, 0.5 and 1 credits i will give it 0.5. My feedback to the student would be to consider why coupling and cohesion are important in software design and to submit again."
These are the only criteria, I do not change or seperate them or create other criteria. Furthermore I do not give a feedback about plagarism since this is not the case.

Following the output schema, the result is therefore:

{{
  "feedbacks": [
    {{
      "title": "Difference between Coupling and Cohesion",
      "description": "Great work! Your explanation of the difference between coupling and cohesion is correct.",
      "line_start": 1,
      "line_end": 1,
      "credits": 1.0,
      "grading_instruction_id": 6053
    }},
    {{
      "title": "Example of Coupling and Cohesion",
      "description": "Your example is correct and clear. To improve further, consider providing a more creative or unique example.",
      "line_start": 2,
      "line_end": 2,
      "credits": 1.0,
      "grading_instruction_id": 6058
    }},
    {{
      "title": "Importance of Coupling and Cohesion",
      "description": "You have provided a partial explanation of why coupling and cohesion are important. Consider discussing specific aspects like maintainability or lower complexity.",
      "line_start": 3,
      "line_end": 3,
      "credits": 1,
      "grading_instruction_id": 6056
    }}
  ]
}}
# Example 2
"I see that there are 3 criteria for this exercise.
The first is the explanation of the difference between coupling and cohesion.
The student's explanation is correct and up to par with the example solution, full credits for this criteria which out of the possible 0, 0.5, and 1 would be 1. Feedback for this is just words of encouragement.
The second criteria is to give an example.
The student did not provide an example, so I cannot give any credits for this. Out of the possible 0, 0.5, and 1, this will be 0. My feedback to the student would be to include an example that demonstrates coupling and cohesion.
The third criteria is to explain the importance of coupling and cohesion.
The student has said that they are important for reducing complexity in software design. This is a specific and valid point, and I will give full credits for this criteria, which out of the possible 0, 0.5, and 1 would be 1."

Following the output schema, the result is therefore:
{{
  "feedbacks": [
    {{
      "title": "Difference between Coupling and Cohesion",
      "description": "Great work! Your explanation of the difference between coupling and cohesion is correct.",
      "line_start": 1,
      "line_end": 1,
      "credits": 1.0,
      "grading_instruction_id": 6053
    }},
    {{
      "title": "Example of Coupling and Cohesion",
      "description": "No example provided. Please include an example to demonstrate coupling and cohesion.",
      "line_start": 2,
      "line_end": 2,
      "credits": 0.0,
      "grading_instruction_id": 6055
    }},
    {{
      "title": "Importance of Coupling and Cohesion",
      "description": "Excellent point on reducing complexity. Great work!",
      "line_start": 3,
      "line_end": 3,
      "credits": 1.0,
      "grading_instruction_id": 6056
    }}
  ]
}}
# Example 3
"I see that there are 3 criteria for this exercise.
The first is the explanation of the difference between coupling and cohesion.
The student has mixed up the definitions of coupling and cohesion, which is a critical mistake. Out of the possible 0, 0.5, and 1, I must give 0. My feedback to the student would be to review the definitions and ensure they understand the difference clearly.
The second criteria is to give an example.
The example provided is clear and correct, so I will give full credits for this, which out of the possible 0, 0.5, and 1 would be 1.
The third criteria is to explain the importance of coupling and cohesion.
The student has mentioned maintainability and reducing complexity as reasons why they are important. This is valid, and I will give full credits for this, which out of the possible 0, 0.5, and 1 would be 1."

Following the output schema, the result is therefore:
{{
  "feedbacks": [
    {{
      "title": "Difference between Coupling and Cohesion",
      "description": "You have mixed up the definitions of coupling and cohesion. Please review their correct meanings.",
      "line_start": 1,
      "line_end": 1,
      "credits": 0.0,
      "grading_instruction_id": 6053
    }},
    {{
      "title": "Example of Coupling and Cohesion",
      "description": "Your example is correct and clear. Great job!",
      "line_start": 2,
      "line_end": 2,
      "credits": 1.0,
      "grading_instruction_id": 6053
    }},
    {{
      "title": "Importance of Coupling and Cohesion",
      "description": "You have correctly highlighted maintainability and reduced complexity. Great work!",
      "line_start": 3,
      "line_end": 3,
      "credits": 1.0,
      "grading_instruction_id": 6056
    }}
  ]
}}
# End of Examples
Remember to be extra caution and careful not to reveal the solution. Your feedback should be constructive and helpful to guide and encourage the student to improve, but without telling them what to write.
You are allowed to use the examples above as inspiration, but make sure to adapt them to the student's submission. Furthermore, you may deviate on the feedback content in order to be more assisting to the student.
You may also explain things which the student seem to have misconceptions about. However you should not give away the solution.
# Your Assessment
Now its your turn. Here is student the submission (with sentence numbers <number>: <sentence>):
\"\"\"
{submission}
\"\"\"\
    

"""

# Input Prompt
class ThinkingPrompt(BaseModel):
    """\
Features available: **{problem_statement}**, **{example_solution}**, **{grading_instructions}**, **{max_points}**, **{bonus_points}**, **{submission}**

_Note: **{problem_statement}**, **{example_solution}**, or **{grading_instructions}** might be omitted if the input is too long._\
"""
    system_message: str = Field(default=system_message,
                                description="Message for priming AI behavior and instructing it what to do.")
    human_message: str = Field(default=human_message,
                               description="Message from a human. The input on which the AI is supposed to act.")
  
# Output Object
class InitialAssessment(BaseModel):
    title: str = Field(description="Very short title, i.e. feedback category or criteria title")
    description: str = Field(description="Feedback description")
    line_start: Optional[int] = Field(description="Referenced line number start, or empty if unreferenced")
    line_end: Optional[int] = Field(description="Referenced line number end, or empty if unreferenced")
    credits: float = Field(0.0, description="Number of points received/deducted")
    # reasoning: str = Field(description="Reasoning why the feedback was given")
    # improvment_suggestion: str = Field(description="Suggestion for improvement for the student")
    grading_instruction_id: int = Field(
        description="ID of the grading instruction that was used to generate this feedback, or empty if no grading instruction was used"
    )

class InitialAssessmentModel(BaseModel):
    """Collection of feedbacks making up an assessment"""
    
    feedbacks: List[InitialAssessment] = Field(description="Assessment feedbacks")
    