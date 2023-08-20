system_message = """\
Student\'s submission (with sentence numbers <number>: <sentence>):
{submission}

Actual feedback given by human graders (as reference):
{true_feedbacks}

Your job is to evaluate the following predicted feedback extremely well.
"""

human_message = """\
Predicted feedback:
{predicted_feedbacks}
"""