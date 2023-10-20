system_template = """\
Your task is to restructure the grading instructions by student changed file to show a tutor \
relevant instructions for each file. This should make it easier for the tutor to grade the assignment.\
"""

human_template = """\
Grading instructions:
{grading_instructions}

Changed files from template to sample solution:
{changed_files_from_template_to_solution}

Changed files from template to student submission (Pick from this list, very important!):
{changed_files_from_template_to_submission}

Grading instructions by file:
"""