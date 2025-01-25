examples = """Before grading my submission consider how a human tutor thinks with this example:
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
""" 