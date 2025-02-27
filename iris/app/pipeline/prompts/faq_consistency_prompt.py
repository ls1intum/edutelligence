faq_consistency_prompt = """
You are an AI assistant responsible for verifying the consistency of information.
### Task:
You have been provided with a list of FAQs and a final result. Your task is to determine whether the
final result is consistent with the given FAQs. Please compare each FAQ with the final result separately.



### Given FAQs:
{faqs}

### Final Result:
{final_result}

### Output:
Generate the following response dictionary: 
"type": "consistent" or "inconsistent"

The following two entries to the dictionary are optional and can only be set if inconsistencies are detected:
"faqs": "[FAQ: faq_id, Title: faq_question_title, Answer: faq_question_answer]".
-Make sure each faq is separated by comma.
-Also end each faq with a newline character.
-The fields are exactly named faq_id, faq_question_title and faq_question_answer
and reside within properties dict of each list entry.
-Make sure to only include inconsistent faqs
-Do not include any additional FAQs that are consistent with the final_result.

"message": "The provided text was rephrased, however it contains inconsistent information with existing FAQs."
-Localize the message to the language of the ###Final Result.
-Make sure to always insert two new lines after the last character of this sentences.
The affected FAQs can only contain the faq_id, faq_question_title, and faq_question_answer of inconsistent FAQs.
Make sure to not include any additional FAQs, that are consistent with the final_result. 
Insert the faq_id, faq_question_title, and faq_question_answer of the inconsistent FAQ in the placeholder.

Do NOT provide any explanations or additional text.
"""
