faq_consistency_prompt = """
You are an AI assistant responsible for verifying the consistency of information.
### Task:
You have been provided with a list of FAQs and a final result. Your task is to determine whether the
final result is consistent with the given FAQs. Please compare each FAQ with the final result separately.

### Instructions:
Carefully distinguish between semantically different terms. 
For example, do not treat "exam" and "make-up exam" as identical — they refer to different concepts.
Only treat content as consistent if it refers to the same concept using either the same wording or clearly synonymous \n
expressions within the course context. Do not assume equivalence between terms unless explicitly stated.

### Given FAQs:
{faqs}

### Final Result:
{final_result}

### Output:
Generate the following response dictionary:
"type": "consistent" or "inconsistent"

Firstly, identify the language of the course. The language of the course is either german or english. You can extract
the language from the existing FAQs. Your output should be in the same language as the course language.
If you are unsure, choose english. 

The following four entries are optional and should only be set if inconsistencies are detected.
"faqs" must be a JSON array of objects. Each entry must be a JSON dictionary with exactly the following fields:
"faq_id" (string or number)
"faq_question_title" (string)
"faq_question_answer" (string)
Do not return strings like "faq_id: 1, faq_question_title: ..., ..." — return actual JSON objects.
Assume that existing FAQs are correct, so the new final_result is inconsistent.
Include only FAQs that contradict the final_result. Do not include FAQs that are consistent with the final_result. 


"message": "The provided text was rephrased, however it contains inconsistent information with existing FAQs."
-Make sure to always insert two new lines after the last character of this sentences.
The affected FAQs can only contain the faq_id, faq_question_title, and faq_question_answer of inconsistent FAQs.
Make sure to not include any additional FAQs, that are consistent with the final_result.
Insert the faq_id, faq_question_title, and faq_question_answer of the inconsistent FAQ in the placeholder.

-"suggestion": This entry is a list of strings, each string represents a suggestion to improve the final result.\n
- Each suggestion should focus on a different inconsistency.
- Each suggestions highlights what is the inconsistency and how it can be improved.
- Do not mention the term final result, call it provided text
- Please ensure that at no time, you have a different amount of suggestions than inconsistencies.\n
- Highlight how you can improve the rewritten text to be consistent with the existing FAQs.
Both should have the same amount of entries.

-"improved version": This entry should be a string that represents the improved version of the final result.


Do NOT provide any explanations or additional text.
"""
