class ProgrammingExerciseSolutionEntry:
    def __init__(
        self,
        file_path: str,
        previous_line: int,
        line: int,
        previous_code: str,
        code: str,
    ):
        self.file_path = file_path
        self.previous_line = previous_line
        self.line = line
        self.previous_code = previous_code
        self.code = code


class CodeHint:
    def __init__(
        self,
        title: str,
        description: str,
        content: str,
        solution_entries: [ProgrammingExerciseSolutionEntry],
    ):
        self.title = title
        self.description = description
        self.content = content
        self.solution_entries = solution_entries
