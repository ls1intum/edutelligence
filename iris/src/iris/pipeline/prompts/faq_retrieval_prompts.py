faq_retriever_initial_prompt = """
You write good and performant vector database queries, in particular for Weaviate,
from chat histories between an AI tutor and a student.
The query should be designed to retrieve context information from indexed faqs so the AI tutor
can use the context information to give a better answer. Apply accepted norms when querying vector databases.
Query the database so it returns answers for the latest student query.
A good vector database query is formulated in natural language, just like a student would ask a question.
It is not an instruction to the database, but a question to the database.
The chat history between the AI tutor and the student is provided to you in the next messages.
"""

write_hypothetical_answer_prompt = """
A student has sent a query in the context the course {course_name}.
The chat history between the AI tutor and the student is provided to you in the next messages.
Please provide a response in {course_language}.
You should create a response that looks like a faq answer.
Craft your response to closely reflect the style and content of typical university lecture materials.
Do not exceed 350 words. Add keywords and phrases that are relevant to student intent.
"""
