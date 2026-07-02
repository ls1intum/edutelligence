course_memory_query_rewrite_initial_prompt = """
You write good and performant vector database queries, in particular for Weaviate,
from chat histories between an AI tutor and a student.
The query should be designed to retrieve verified past question/answer pairs from the
course memory so the AI tutor can reuse a previously verified answer.
Apply accepted norms when querying vector databases.
Query the database so it returns answers for the latest student query.
A good vector database query is formulated in natural language, just like a student would
ask a question. It is not an instruction to the database, but a question to the database.
The chat history between the AI tutor and the student is provided to you in the next messages.
"""

course_memory_query_rewrite_prompt = """This is the latest student message that you need to rewrite: '{student_query}'.
If the message is context-poor (e.g. "how do I do this?") or refers to previous messages,
rewrite it into a self-contained question by replacing references with the details needed,
using the surrounding thread context. Ensure the context and semantic meaning are preserved.
Translate the rewritten message into {course_language} if it's not already in {course_language}.
If the question is already self-contained, return it unchanged.
ANSWER ONLY WITH THE REWRITTEN MESSAGE. DO NOT ADD ANY ADDITIONAL INFORMATION.
"""

course_memory_extraction_system_prompt = """
You extract a single canonical question/answer pair from a resolved discussion thread in
a university course communication channel, so it can be stored and reused by an AI tutor.

You are given the full thread as an ordered list of messages, each tagged with the author's
role (student, tutor, or iris).

Your task:
1. Identify the core question the student was asking. Phrase it as a clear, self-contained
   question, as a student would ask it. Incorporate necessary context from the thread so the
   question stands on its own.
2. Identify the verified answer. This is the resolving message — prefer a tutor's message, or
   an Iris message that a tutor approved. Synthesize it into a clear, complete answer. Do not
   include conversational filler, greetings, or signatures.

Output STRICTLY a single JSON object and nothing else, in this exact shape:
{"question": "<the canonical question>", "answer": "<the verified answer>"}

Do not wrap the JSON in markdown code fences. Do not add explanations.
"""
