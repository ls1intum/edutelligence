basic_prompt = """\
<Instruction>
As detail-oriented expert, find inconsistencies between the provided problem statement and the template repository of \
a programming exercise.
The student will use the the template repository as a framework to write code that solves the problem statement, it might be missing implementations which the students have to do. You are also provided with the solution repository, which should contain the full and correct implementation of the exercise. You are only provided one template file at a time and the corresponding solution file.

Checks:
- Given the problem statement, identify any missing or incorrect information in the template repository.
- Given the template repository, identify any missing or incorrect information in the problem statement.
- Ensure that the theme of the problem statement is consistent with the template repository.
- Ensure that the problem statement is clear and concise and it covers everything that the student needs to know in \
order to solve the exercise.

It is not an inconsistency, if the problem statement clearly states that the student is responsible for writing a \
specific part of the code.
</Instruction>

<Problem Statement>
{problem_statement}
</Problem Statement>

<TemplateRepository>
{template_repository}
</TemplateRepository>

<SolutionRepository>
{solution_repository}
</SolutionRepository>

<Response>
Be smart about it, give a structured and actionable response that an instructor can use to significantly improve the \
exercise. Clearly state where the inconsistency lies. Do not make up inconsistencies just to have something to say.
It needs to be very comprehensive and detailed, imagine some inconsistencies slipped through, students in the exam \
will be confused and frustrated. This is a high stakes exam, so we need to be very thorough.
You will be legally responsible for the quality of the exercise, so make sure you do the absolute best job possible, \
otherwise you will be held accountable in the court of law. Do not quote whole files! 🔫
Do not mention that the template repository is missing requirements mentioned in the problem statement, that is not an inconsistency. The students are supposed to implement those parts, without any guidance such as comments or partial code.
Do only list the inconsistencies (unnumbered), no need to mention something before or after the list of inconsistencies.
</Response>
"""
