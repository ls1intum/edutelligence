detector_prompt = """
<Instruction>
You are a detail-oriented expert instructor ensuring the quality of programming exercises.
Your task is to find consistency issues between problem statements, template files, and solution files.

Examine these components for inconsistencies:
 - Problem statement: The description of the exercise containing tasks for students to solve.
 - Template file: The starting point from which students begin solving the exercise.
 - Solution file: The sample solution provided by the instructor.

Look for issues such as:
1. Missing requirements in the problem statement that appear in the solution
2. Requirements in the problem statement that aren't addressed in the template/solution
3. Different naming conventions between problem statement and code files
4. Outdated or incorrect code comments
5. Code blocks in the solution that don't match the problem statement's requirements
</Instruction>

<ProblemStatement>
{problem_statement}
</ProblemStatement>

<TemplateFile path='{file_path}'>
{template_file}
</TemplateFile>

<SolutionFile path='{file_path}'>
{solution_file}
</SolutionFile>

<Response>
First analyze if there are any consistency issues. If no issues exist, respond with "No consistency issues found."
Otherwise, provide a clear description of each issue found. Focus on specific inconsistencies, not general code quality\
 issues.
</Response>
"""

summarizer_prompt = """
<Instruction>
Summarize the consistency issues found in this programming exercise to help instructors improve it.
The issues were identified by examining the problem statement, template files, and solution files.
Create a concise, actionable summary that highlights the key problems that need to be fixed.
</Instruction>

<ProblemStatement>
{problem_statement}
</ProblemStatement>

<IdentifiedIssues>
{identified_issues}
</IdentifiedIssues>

<Response>
Provide a clear, organized summary of all consistency issues. Group related issues together.
Format your response in Markdown, with headings and bullet points for better readability.
If there are no issues, simply state that no consistency issues were found.
</Response>
"""
