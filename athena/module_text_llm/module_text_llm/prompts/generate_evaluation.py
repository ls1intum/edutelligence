system_message = """\
Student\'s submission (with sentence numbers <number>: <sentence>):
{submission}

Actual feedback given by tutors for the submission (gold standard):
{true_feedbacks}

Your job is to evaluate the following predicted feedback extremely well. Note that the title is optional.
"""

human_message = """\
Predicted feedback for the submission:
{predicted_feedbacks}

Please evaluate only predicted feedback taking into account the gold standard. \
Be as critical and correct as possible, even the gold standard might be wrong or of low quality!
"""