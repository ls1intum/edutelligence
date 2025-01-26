human_prompt = """Before grading the submission, consider how a human tutor would think using the following examples:
After completing your initial analysis, think step by step to assess the submission.

Example 1
Submission:
"Scrum is a project management framework within which teams can address complex adaptive problems, while delivering products of the highest possible value within time-boxed iterations, called sprints. ... (submission truncated for brevity)."

Feedback and Reasoning:

Core Essence of SCRUM:

I observe that the first paragraph introduces the core essence of SCRUM.
The explanation is concise and effectively communicates the fundamental concept of SCRUM.
Out of the grading instructions awarding 0, 1, or 2 credits, I will award 2 credits.
My feedback to the student is: "Correct explanation, well done!"
Comparison to Spiral Model:

In sentences describing the spiral model, the student explains its iterative nature and contrasts it with SCRUM.
The comparison is accurate and aligns with the criteria.
I will award 1 credit for this criterion.
My feedback to the student is: "Correct comparison to the spiral model, well done!"
Advantages and Disadvantages of SCRUM:

I observe multiple examples in the text discussing the advantages and disadvantages of SCRUM.
The examples are relevant and supported by real-world scenarios. However, the submission lacks direct comparisons for each advantage/disadvantage to the spiral model, which is part of the task.
I will award 1.5 credits for each advantage/disadvantage example and include feedback for improvement.
My feedback to the student is: "You correctly identified advantages and disadvantages of SCRUM, but remember to compare each with the spiral model for completeness."
General Observations:

Overall, the submission demonstrates a good understanding of SCRUM and its application.
However, the student should ensure that all required comparisons are made explicitly to align with the problem statement.

{{
  "assessment": [
    {{
      "criteria": "Core Essence of SCRUM",
      "description": "Correct explanation, well done!",
      "line_start": 0,
      "line_end": 3,
      "credits": 2.0,
      "grading_instruction_id": 15663
    }},
    {{
      "criteria": "Comparison to Spiral Model",
      "description": "Correct comparison to the spiral model, well done!",
      "line_start": 3,
      "line_end": 6,
      "credits": 1.0,
      "grading_instruction_id": 15670
    }},
    {{
      "criteria": "Advantages/Disadvantages of SCRUM",
      "description": "You correctly identified advantages of SCRUM, but remember to compare each with the spiral model for completeness.",
      "line_start": 6,
      "line_end": 10,
      "credits": 1.5,
      "grading_instruction_id": 15666
    }},
    {{
      "criteria": "Advantages/Disadvantages of SCRUM",
      "description": "You correctly identified disadvantages of SCRUM, but remember to compare each with the spiral model for completeness.",
      "line_start": 10,
      "line_end": 15,
      "credits": 1.5,
      "grading_instruction_id": 15666
    }}
        {{
      "criteria": "Advantages/Disadvantages of SCRUM",
      "description": "You correctly identified advantages of SCRUM, but remember to compare each with the spiral model for completeness.",
      "line_start": 6,
      "line_end": 10,
      "credits": 1.5,
      "grading_instruction_id": 15666
    }},
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