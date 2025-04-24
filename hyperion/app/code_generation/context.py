from typing import Dict, Any, Optional

class Context:
    def __init__(
        self,
        problem_statement: str,
        programming_language: str,
        workspace_dir: str,
    ):
        self.problem_statement: str = problem_statement
        self.programming_language: str = programming_language
        self.workspace_dir: str = workspace_dir
        self.solution_plan: str = ""
        self.terminal_output: str = ""
        self.execution_successful: bool = False
        
    def __str__(self) -> str:
        return (
            f"Context(problem_statement={self.problem_statement[:30]}..., "
            f"programming_language={self.programming_language}, "
            f"execution_successful={self.execution_successful})"
        ) 
