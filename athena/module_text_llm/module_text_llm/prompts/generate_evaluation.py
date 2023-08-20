system_message = """\
Student\'s submission (with sentence numbers <number>: <sentence>):
{submission}

Actual feedback given by human graders for the submission (as reference):
{true_feedbacks}

Your job is to evaluate the following predicted feedback extremely well. Note that the title is optional.
"""

human_message = """\
Predicted feedback for the submission:
{predicted_feedbacks}

Please evaluate only predicted feedback taking into account the actual feedback given by human graders for the submission (as reference).
"""