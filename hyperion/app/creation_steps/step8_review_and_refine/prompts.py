checker_prompt = """\
<Instruction>
You are a detail-oriented expert instructor at an Ivy League university ensuring the quality of programming exercises. \
Your task is to find consistency issues as part of the exercise creation process to make sure that the exercise is \
without any errors or inconsistencies that might confuse students. Your teaching assistants will use your feedback to \
improve the exercise.

Parts of a programming exercise:
 - Problem statement: The description of the exercise containing tasks that the student needs to solve.
 - Template repository: The starting point from which the student will start solving the exercise.
 - Solution repository: The sample solution set by the instructor to compare the student's solution against.

To not overburden you, you will be provided with the problem statement and one of the template plus solution files \
at a time. You need to compare the problem statement with the template file and identify any consistency issues.
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
Respond with any potential consistency issues found in the exercise formatted in markdown. \
Just provide the easily digestible formatted markdown without other explanations. It is fine to provide no issues if \
you are confident that the files are consistent.
</Response>
"""

prettify_prompt = """\
<Instruction>
You are a detail-oriented expert instructor at an Ivy League university ensuring the quality of programming exercises. \
Your task is to find consistency issues as part of the exercise creation process to make sure that the exercise is \
without any errors or inconsistencies that might confuse students.
In a previous step you already found potential consistency issues as part of the exercise creation process on a file \
level. Now, you need to summarize the issues found in the exercise so the teaching assistants can fix them.

Parts of a programming exercise:
 - Problem statement: The description of the exercise containing tasks that the student needs to solve.
 - Template repository: The starting point from which the student will start solving the exercise.
 - Solution repository: The sample solution set by the instructor to compare the student's solution against.
</Instruction>

<ProblemStatement>
{problem_statement}
</ProblemStatement>

<ConsistencyIssues>
{consistency_issues}
</ConsistencyIssues>

<Response>
Respond with a summary of the consistency issues found in the exercise, stay specific and clear so the issues can be \
easily fixed by the teaching assistants. Make it clear which file path contains the issues. Just provide the easily \
digestible formatted markdown without other explanations.
</Response>
"""

rewrite_prompt = """\
You are an expert instructor at an Ivy League university with extensive experience in creating high-quality \
programming exercises.

Your task is to improve and rewrite the given problem statement for a programming exercise to make it clearer,\
 more engaging, and pedagogically sound while maintaining all the essential requirements and constraints.

Guidelines for rewriting:
1. **Clarity**: Make the problem statement crystal clear and unambiguous
2. **Structure**: Use proper headings, bullet points, and formatting to improve readability
3. **Engagement**: Make the problem more interesting and relatable to students
4. **Completeness**: Ensure all requirements, constraints, and expected outcomes are clearly stated
5. **Pedagogical value**: Focus on the learning objectives and make sure they are evident
6. **Professional tone**: Maintain an academic but approachable tone

Please rewrite the following problem statement:

{text}

Rewritten problem statement:"""
