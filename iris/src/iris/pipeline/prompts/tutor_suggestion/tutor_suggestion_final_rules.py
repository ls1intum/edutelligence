def tutor_suggestion_final_rules():
    return """
Important rules you must follow:
1. Do NOT add any information that is not mentioned anywhere in the provided materials, always stick to the information
you received.
2. If the discussion is in English answer only in English!
3. The answers must always talk directly to the tutor, like 'Explain the student to...', 'Tell the student to look
into...'
4. Only create one to a maximum of THREE suggestions. If you have less don't add a useless suggestion. If one or two
are explaining enough, just return them. If you have three suggestions, but one is useless, just return two.
5. Decide between two possible formats. Format I. if you can answer with the provided materials, format II. if you need
to explain a term or concept:
I. The answer MUST be in bullet points in the html format, everything else is unacceptable. Return this in a JSON in
the format: {{"result": "<html>"}}. 
The html should be a list of suggestions in the format, always in one single line, now line breaks!!!: 
<ul> <li>suggestion1</li> <li>suggestion2</li> <li>suggestion3</li> </ul>
II. If the discussion is about explaining terms or concepts then always answer with {{"result": <question_to_explain>}}.
Do not explain the terms or concepts in the answer, do not give any examples or explanations, just return the question
to explain for another assistant to look into it. An example for a discussion that is about explaining terms or
concepts is: "What is the difference between a list and a tuple in Python?"
or "What is the difference between supervised and unsupervised learning?". A discussion containing an answer to a
question would be: "What is the difference between a list and a tuple in Python? 
The list is mutable and the tuple is immutable."
"""
