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
"I see that there are 2 criteria for this exercise. I am considering the first criteria 'Plagarism', I do not have any access to the lecture slides so I cannot comment on this, it is also a 0 credit negative instruction so i will not include it. Next criteria is 'Definition of LLM', the student has stated that an LLM is a model that generates text, this is partially true however LLMs have other characteristics that are important without which i can not give full credit, especially since the example solution and grading instructions are clear on this. I will give half points for this criteria. I do not want to reveal the solution to the student so i will only guide them to the right direction. My feedback to them would be to consider what other characteristics makes an LLM different from other models and to submit again."
# Example 2 
"I see that there are 3 criteria for this exercise. The first is the explanation of the difference between coupling and cohesion. The students explanation is correct and up to par with the example solution, full credits for this criteria. Feedback for this is just words of encourgment. The second criteria is to give an example. The example is not very creative and rather generic, however it is correct and clear, I will give full credits and a suggestion. The third criteria is to explain the importance of coupling and cohesion. The student has said that they are important for software design because it makes the engineering process easier. I will give half points for this criteria because he did not mention any specific argumentm like maintainability, or lower complexity etc. . My feedback to the student would be to consider why coupling and cohesion are important in software design and to submit again."
# End of Examples

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
    grading_instruction_id: Optional[int] = Field(
        description="ID of the grading instruction that was used to generate this feedback, or empty if no grading instruction was used"
    )

class InitialAssessmentModel(BaseModel):
    """Collection of feedbacks making up an assessment"""
    
    feedbacks: List[InitialAssessment] = Field(description="Assessment feedbacks")
    