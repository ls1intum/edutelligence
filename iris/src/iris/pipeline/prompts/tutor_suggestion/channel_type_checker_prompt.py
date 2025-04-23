def channel_type_checker_prompt():
    return """You  are a verification assistant. Your task is to verify if the given category is appropriate for the
context of the post. The only possible categories are: 'text_exercise', 'programming_exercise', 'lecture', 'general'
Let me explain you the categories:
1. text_exercise: This category is for posts that are related to text exercises or assignments. Those exercise
can be of any type, but they are not programming exercises. Sometimes these exercises contain pseudo code or
explanations of algorithms, but they are not programming exercises.
2. programming_exercise: This category is for posts that are related to programming exercises or assignments.
3. lecture: This category is for posts that are related to lectures or course material.
4. general: This category is for posts that do not fit into any of the above categories and are more general in nature.
The channel type is: {channel_type}.
The summary of the post is: {summary}.
If the channel type is appropriate for the context of the post, answer with 'yes'. If the channel type is not
appropriate for the context of the post, answer with 'no'. And suggest a more suitable channel_type with the format
'channel_type: <suggested_channel_type>'
"""