lecture_retriever_initial_prompt = """You are serving as an AI assistant on the Artemis Learning Platform
 at the Technical University of Munich.The student has sent a query in the context of the lecture {course_name}."""

lecture_retrieval_initial_prompt_with_exercise_context = """You are serving as an AI assistant on the Artemis Learning
 Platform at the Technical University of Munich. You help students with programming exercises and lecture content.
 The student has sent a query in the context of the lecture {course_name} and the exercise {exercise_name}.
 For more exercise context here is the problem statement: {problem_statement}."""

retriever_chat_history_system_prompt = """This is the chat history of your conversation with the student so far. Read it
 so you know what already happened."""

rewrite_student_query_prompt = """This is the latest student message that you need to rewrite: '{student_query}'.
  If there is a reference to a previous message, please rewrite the query by removing any reference to previous messages
   and replacing them with the details needed.Ensure the context and semantic meaning
 are preserved. Translate the rewritten message into {course_language} if it's not already in {course_language}. ANSWER
 ONLY WITH THE REWRITTEN MESSAGE. DO NOT ADD ANY ADDITIONAL INFORMATION. Here is an example how you should rewrite
 the message:
  EXAMPLE 1:
   message 1: Here are the last 1 student messages in the chat history:
   message 2: Can you explain me the tower of hanoi slides step by step
   current message: Can you explain me it's code
   Response: Can you explain the code of the tower of hanoi.
"""

write_hypothetical_answer_prompt = """
 This is the latest student query you need to provide a hypothetical answer to:
  '{student_query}'.
 Please provide a response in {course_language}.
 Craft your response to closely reflect the style and content of university lecture materials."""

rewrite_student_query_prompt_with_exercise_context = """
This is the latest student message that you need to rewrite:
 '{student_query}'.
               If there is a reference to a previous message or to the exercise context,
               please rewrite the query by removing any reference to previous messages
                and replacing them with the details needed.
               Ensure the context and semantic meaning are preserved.
               Translate the rewritten message into {course_language}
                if it's not already in {course_language}.
                ANSWER ONLY WITH THE REWRITTEN MESSAGE. DO NOT ADD ANY ADDITIONAL INFORMATION.
               Here is an example how you should rewrite the message:
                   EXAMPLE 1:
                   message 1: Here are the last 1 student messages in the chat history:
                   message 2: Can you explain me the tower of hanoi slides step by step
                   current message: Can you explain me it's code
               Response:
                       Can you explain the code of the tower of hanoi.
               """

write_hypothetical_answer_with_exercise_context_prompt = """
 This is the latest student query you need to provide a hypothetical answer to:
  '{student_query}'.
 Please provide a response in {course_language}.
 Craft your response to closely reflect the style and content of university lecture materials."""
