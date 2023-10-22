system_template = """\
Your task is to restructure the problem statement by student changed file to show the student \
relevant information for each file. This should make it easier for the student to solve the assignment.\
"""

human_template = """\
Problem statement:
{problem_statement}

Changed files from template to sample solution:
{changed_files_from_template_to_solution}

Changed files from template to student submission (Pick from this list, very important!):
{changed_files_from_template_to_submission}

Problem statement by file:
"""