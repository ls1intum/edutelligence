examples = """
"Before grading the submission consider how a human tutor thinks with this examples:
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
""" 


