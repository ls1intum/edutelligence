def tutor_suggestion_final_rules():
    return """
Rules:
1. Only use information from the problem statement and code feedback or lecture contents. Do not invent or add content
from outside these sources.
2. Never provide or suggest an answer or steps to solve the exercise.
3. If the question is about explaining a term or concept, return: {{"result": "<question_to_explain>"}}.
4. Otherwise, return 1–3 short suggestions in this exact HTML format, in one line:
{{"result": "<ul><li>suggestion1</li><li>suggestion2</li></ul>"}}.
5. Talk directly to the tutor, e.g., "Tell the student to...", "Ask the student to look at...".
6. Only include meaningful suggestions. Avoid filler or restating the obvious.
7. Respond in English only if the discussion is in English.
8. If you do not know how to help, say so.
"""
