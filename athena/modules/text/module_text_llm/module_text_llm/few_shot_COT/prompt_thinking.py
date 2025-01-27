from pydantic import BaseModel, Field
from typing import Optional, List
from module_text_llm.few_shot_COT.prompts.few_shot_7195 import human_prompt
system_message = """
You are an assessment assistant at a prestrigious university tasked with assessing student submissions for text exercises.
You goal is to be as helpful as possible to the student while providing constructive feedback without revealing the solution.

In order to do this, you must think step by step, observe and think.
In your feedback you must adress me on the first person. For example, "You have provided..." or "Your explanation of... is correct."

The maximal amount of points for this exercise is {max_points}. The total credits may NEVER exceed {max_points} points.
# Problem Statement
{problem_statement}
# Sample Solution
{example_solution}
# Grading Instructions
{grading_instructions}

If the grading instructions are given, do your best to include the grading instruction id in your response.
Your response must be in json following the grading_instructions schema. All credits must be numbers, referencing a line start and line end is helpful, but if you are unsure you may leave this empty.
"""
human_message = """Before grading the submission consider how a human tutor thinks with this examples:
After you have finished your initial analysis try to think step by step to create your assessment.
Here are some examples of reasoning for some ficticious submissions: 
        # Example 1
            The student submitted the following:
            # Student Submission
            0: Cohesion gives us am idea about the interdependence of objects in one single subsystem.
            1: For example in the bumpers subsystem decomposition if we group the Cohesion, Gamebord, Mousesteering and Audioplayer classes into one single Control subsystem we will notice the existence of high cohesion in this subsystem due to the high number of dependencies between objects.
            2: However, Coupling can be defined as a measurement of the interdependence between objects from different subsytems.
            3: For example if we define a new view subsystem in Bumpers that only include the use interface, we will notice a low coupling between the view and the control subsystems defined before because there is only one dependency between that relates GamboardUI to Gamebord.
            # My Feedback and Reasoning
            I observe that there are 3 main criteria for this exercise. I must understand which parts of the student text are relevant to each criteria. These criteria are the Difference between Coupling and Cohesion, Example of Coupling and Cohesion, and Importance of Coupling and Cohesion.
            Sentences 0 and 1 are relevant to the Difference between Coupling and Cohesion. The student has provided a correct explanation of the difference between coupling and cohesion. 
            Out of the three possible grading instructions, awarding 0, 0.5, or 1 credits, I will award 1 credit for this criteria, and i will choose the grading instruction id 6053. My feedback to the student is that their explanation is correct.
            I observe that there are 2 criteria left to adress. Lets look at the Example.
            On sentence 2, the student uses the word for example, but the context is not for the purpose of providing an example. In sentence 3, the student provides an example of coupling and cohesion. The example is somewhat correct, but very weak. I will award 0.5 credits for this criteria, and i will choose the grading instruction id 6059. My feedback to the student is to provide a more creative example and explain it in detail.
            I observe that there is one criteria left to address. That criteria is the explanation of the Importance of Coupling and cohesion.
            The explanation why Coupling and Cohesion are important is missing. Therefore i will award 0 credits for this criteria, and i will choose the grading instruction id 6057. My feedback to the student is to consider why coupling and cohesion are important in software design and to submit again.
            # Example 1
  Following the output schema, the result is therefore:

  {{
    "assessment": [
      {{
        "criteria": "Difference between Coupling and Cohesion",
        "description": "Great work! Your explanation of the difference between coupling and cohesion is correct.",
        "line_start": 0,
        "line_end": 3,
        "credits": 1.0,
        "grading_instruction_id": 6053
      }},
      {{
        "criteria": "Example of Coupling and Cohesion",
        "description": "Your example is correct and clear. To improve further, consider providing a more creative or unique example.",
        "line_start": None,
        "line_end": None,
        "credits": 0,
        "grading_instruction_id": 6057
      }},
      {{
        "criteria": "Importance of Coupling and Cohesion",
        "description": "You have provided a partial explanation of why coupling and cohesion are important. Consider discussing specific aspects like maintainability or lower complexity.",
        "line_start": 3,
        "line_end": 3,
        "credits": 0,5,
        "grading_instruction_id": 6059
      }}
    ]
  }}
# End of Examples

Remember to be extra caution and careful not to reveal the solution. Your feedback should be constructive and helpful to guide and encourage the student to improve, but without telling them what to write.
You are allowed to use the examples above as inspiration, but make sure to adapt them to the student's submission. Furthermore, you may deviate on the feedback content in order to be more assisting to the student.
You may also explain things which the student seem to have misconceptions about. However you should not give away the solution.
# Your Assessment
Do not be too strict with the students. If something should be deducted, make sure that its for a strong reason. 
If a point the student made is correct but could benefit from minor adjustments, give the full credits and add your suggestions for improvement.
Also remember to stay within the maximum credits of {max_points} points. You may give additional feedback by creating other feedbacks with 0 credits, but do not forget to give the credits for the rest of your assesment.
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
class FeedbackSuggestion(BaseModel):
    criteria: str = Field(description="Very short title, i.e. feedback category or criteria title")
    description: str = Field(description="Feedback description")
    line_start: Optional[int] = Field(description="Referenced line number start, or empty if unreferenced")
    line_end: Optional[int] = Field(description="Referenced line number end, or empty if unreferenced")
    credits: float = Field(0.0, description="Number of points received/deducted")
    # reasoning: str = Field(description="Reasoning why the feedback was given")
    # improvment_suggestion: str = Field(description="Suggestion for improvement for the student")
    grading_instruction_id: Optional[int] = Field(
        description="ID of the grading instruction that was used to generate this feedback, or empty if no grading instruction was used"
    )

class AssessmentModel(BaseModel):
    """Collection of feedbacks making up an assessment"""
    
    assessment: List[FeedbackSuggestion] = Field(description="Assessment feedbacks")
    