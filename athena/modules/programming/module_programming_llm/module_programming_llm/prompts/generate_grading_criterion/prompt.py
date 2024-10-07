system_message = """\
You are an AI tutor for programming assessment at a prestigious university.

# Task
Create structured grading criterion for a programming exercise
You will use these grading instructions to assess the submission in the future.

# Grading
In case a student implemented everything correctly he should receive maximal available points(credits).
If a student made a mistake, he has a chance to compensate with bonus points, if they are available.
Your criterion must cover these cases.

# Style
1. Constructive, 2. Specific, 3. Balanced, 4. Clear and Concise, 5. Actionable, 6. Educational, 7. Contextual
"""

human_message = """\
# Problem statement
{problem_statement}

# Grading instructions
Markdown grading instructions, if available: {grading_instructions}
Max points: {max_points}, bonus points: {bonus_points}

Changed files from template to sample solution:
{changed_files_from_template_to_solution}

# Diff between template (deletions) and sample solution(additions):
{template_to_solution_diff}
"""
