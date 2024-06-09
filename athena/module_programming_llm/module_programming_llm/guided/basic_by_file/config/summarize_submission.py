from pydantic import BaseModel, Field


system_message = """\
You are a very experienced software engineer.

# Task
Analyze the following source code file.
Create a structural diagram of the file in the format of a single string called 'Explanation'.
Name public relevant functions/methods/procedures/data structures/interfaces or alike that are used/declared in the file.
Name relevant details for the chosen paradigm.
You can skip purely file-internal code.
Omit default imports for the language. 

# Style
1. Global view preserving 2. Structural
Include full path for files where necessary.
"""


human_message = """\
File path: {file_path}
File:
\"\"\"
{submission_file}
\"\"\"
"""


class FileSummaryPrompt(BaseModel):
    """Generates concise summaries of submission files, facilitating a quicker review and understanding of the content for AI processing."""

    system_message: str = Field(default=system_message,
                                description="Message for priming AI behavior and instructing it what to do.")
    human_message: str = Field(default=human_message,
                               description="Message from a human. The input on which the AI is supposed to act.")

