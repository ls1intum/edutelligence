def tutor_suggestion_final_rules():
    return """
Important rules you must follow:
1. Do NOT add any information that is not mentioned anywhere in the provided prompt.
2. If the discussion is in English answer only in english!
3. The answers should talk directly to the tutor, like 'Explain the student to...', 'Tell the student to look into...'
4. Only create a maximum of THREE suggestions. If you have less don't add a useless suggestion.
5. The answer MUST be in bullet points in the html format, everything else is unacceptable. Return this in a JSON in
the format: {{"result": "<html>"}}. The html should be a list of suggestions in the format:
<ul> <li>suggestion1</li> <li>suggestion2</li> <li>suggestion3</li> </ul>
"""
