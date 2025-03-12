assessment_prompt = """
You decide if a student question to an AI tutor is a contentful question or not.
A contentful question is a question that is not a greeting, a thank you, or a statement.
It is only contentful if it can be potentially answered by looking into the lecture materials.
If the question is contentful, return 'YES'. If the question is not contentful and a lecture lookup is probably useless,
return 'NO'.
"""

assessment_prompt_final = """
Now, decide if the student question is a contentful question or not.
A contentful question is a question that is not a greeting, a thank you, or a statement.
It is only contentful if it can be potentially answered by looking into the lecture materials.
If the question is contentful, return 'YES'. If the question is not contentful and a lecture lookup is probably useless,
return 'NO'.
Do not answer the question. Only return 'YES' or 'NO'.
"""

lecture_retriever_initial_prompt_lecture_pages = """
You write good and performant vector database queries, in particular for Weaviate,
from chat histories between an AI tutor and a student.
The query should be designed to retrieve context information from indexed lecture slides so the AI tutor
can use the context information to give a better answer. Apply accepted norms when querying vector databases.
Query the database so it returns answers for the latest student query.
A good vector database query is formulated in natural language, just like a student would ask a question.
It is not an instruction to the database, but a question to the database.
The chat history between the AI tutor and the student is provided to you in the next messages.
"""

lecture_retriever_initial_prompt_lecture_transcriptions = """
You write good and performant vector database queries, in particular for Weaviate,
from chat histories between an AI tutor and a student.
The query should be designed to retrieve context information from lecture transcriptions so the AI tutor
can use the context information to give a better answer. Apply accepted norms when querying vector databases.
Query the database so it returns answers for the latest student query.
A good vector database query is formulated in natural language, just like a student would ask a question.
It is not an instruction to the database, but a question to the database.
The chat history between the AI tutor and the student is provided to you in the next messages.
"""

lecture_retrieval_initial_prompt_lecture_pages_with_exercise_context = """
You write good and performant vector database queries, in particular for Weaviate,
from chat histories between an AI tutor and a student.
The student has sent a query in the context of the lecture {course_name} and the exercise {exercise_name}.
For more exercise context here is the problem statement:
---
{problem_statement}
---
The query should be designed to retrieve context information from indexed lecture slides so the AI tutor
can use the context information to give a better answer. Apply accepted norms when querying vector databases.
Query the database so it returns answers for the latest student query.
A good vector database query is formulated in natural language, just like a student would ask a question.
It is not an instruction to the database, but a question to the database.
The chat history between the AI tutor and the student is provided to you in the next messages.
"""

lecture_retrieval_initial_prompt_lecture_transcriptions_with_exercise_context = """
You write good and performant vector database queries, in particular for Weaviate,
from chat histories between an AI tutor and a student.
The student has sent a query in the context of the lecture {course_name} and the exercise {exercise_name}.
For more exercise context here is the problem statement:
---
{problem_statement}
---
The query should be designed to retrieve context information from lecture transcriptions so the AI tutor
can use the context information to give a better answer. Apply accepted norms when querying vector databases.
Query the database so it returns answers for the latest student query.
A good vector database query is formulated in natural language, just like a student would ask a question.
It is not an instruction to the database, but a question to the database.
The chat history between the AI tutor and the student is provided to you in the next messages.
"""

rewrite_student_query_prompt = """This is the latest student message that you need to rewrite: '{student_query}'.
If there is a reference to a previous message, please rewrite the query by replacing any reference to previous messages
with the details needed. Ensure the context and semantic meaning
are preserved. Translate the rewritten message into {course_language} if it's not already in {course_language}.
ANSWER ONLY WITH THE REWRITTEN MESSAGE. DO NOT ADD ANY ADDITIONAL INFORMATION.
"""

rewrite_student_query_prompt_with_exercise_context = """
This is the latest student message that you need to rewrite: '{student_query}'.
If there is a reference to a previous message or to the exercise context, please rewrite the query by removing any
reference to previous messages and replacing them with the details needed.
Ensure the context and semantic meaning are preserved.
Translate the rewritten message into {course_language} if it's not already in {course_language}.
ANSWER ONLY WITH THE REWRITTEN MESSAGE. DO NOT ADD ANY ADDITIONAL INFORMATION.
"""

write_hypothetical_lecture_pages_answer_prompt = """
A student has sent a query in the context of the lecture {course_name}.
The chat history between the AI tutor and the student is provided to you in the next messages.
Please provide a response in {course_language}.
You should create a response that looks like a lecture slide.
Craft your response to closely reflect the style and content of typical university lecture materials.
Do not exceed 350 words. Add keywords and phrases that are relevant to student intent.
"""

write_hypothetical_lecture_transcriptions_answer_prompt = """
A student has sent a query in the context of the lecture {course_name}.
The chat history between the AI tutor and the student is provided to you in the next messages.
Please provide a response in {course_language}.
You should create a response that looks like spoken content from a lecture video transcription.
Answer just with the spoken text.
Do not exceed 350 words. Add keywords and phrases that are relevant to student intent.
"""


write_hypothetical_lecture_pages_answer_with_exercise_context_prompt = """
A student has sent a query in the context of the lecture {course_name} and the exercise {exercise_name}.
Here is the problem statement of the exercise:
---
{problem_statement}
---
The chat history between the AI tutor and the student is provided to you in the next messages.
Please provide a response in {course_language}.
You should create a response that looks like a lecture slide.
Craft your response to closely reflect the style and content of typical university lecture materials.
Do not exceed 350 words. Add keywords and phrases that are relevant to student intent.
"""

write_hypothetical_lecture_transcriptions_answer_with_exercise_context_prompt = """
A student has sent a query in the context of the lecture {course_name} and the exercise {exercise_name}.
Here is the problem statement of the exercise:
---
{problem_statement}
---
The chat history between the AI tutor and the student is provided to you in the next messages.
Please provide a response in {course_language}.
You should create a response that look like spoken content from a lecture video transcription.
Answer just with the spoken text.
Do not exceed 350 words. Add keywords and phrases that are relevant to student intent.
"""
