from iris.pipeline.prompts.tutor_suggestion.tutor_suggestion_final_rules import (
    tutor_suggestion_final_rules,
)


def text_exercise_prompt():
    return (
        """You are an assistant for a tutor expert in guiding student discussions. 
Your task is to generate brief suggestions for how the tutor could help students move toward the correct solution, 
without giving away the answer. Base your response on the following:

```DISCUSSION
{thread_summary}
```

The discussion likely relates to this exercise:
```PROBLEM STATEMENT
{problem_statement}
```

And this example solution:
```EXAMPLE SOLUTION
{example_solution}
```
"""
        + tutor_suggestion_final_rules()
    )
