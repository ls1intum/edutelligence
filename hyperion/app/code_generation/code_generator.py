import os
from app.models import get_model
from .utils import Logger
from .step_execution.steps import (
    GenerateSolutionPlan,
    GenerateComments,
    GenerateCoreLogic,
    RunScript,
    EvaluateTerminalOutput,
    FixCode
)
from langchain_core.language_models import BaseLanguageModel
from .context import Context
from .environment.env import Env
from .environment.strategies.python_env import PythonEnv

class CodeGenerator:
    
    def __init__(self, workspace_dir: str, max_iterations: int = 3):
        self.max_iterations: int = max(1, max_iterations)
        self.model: BaseLanguageModel = get_model()
        self.workspace_dir: str = workspace_dir
        self.logger: Logger = Logger(log_dir=workspace_dir)
        self.env: Env = None
        
    def generate(self, problem_statement: str, programming_language: str) -> str:
        """
        Args:
            problem_statement (str): problem statement to solve
            programming_language (str): programming language to use

        Returns:
            str: path to file containing the generated code
        """
        self.logger.info("Starting code generation process")
        self.env = self.get_env(programming_language)
        
        context = Context(
            problem_statement=problem_statement,
            programming_language=programming_language,
            workspace_dir=self.workspace_dir
        )
        
        GenerateSolutionPlan(self).execute(context)
        GenerateComments(self).execute(context)
        GenerateCoreLogic(self).execute(context)
        
        for _ in range(self.max_iterations):
            RunScript(self).execute(context)
            EvaluateTerminalOutput(self).execute(context)
            if context.execution_successful:
                break
            FixCode(self).execute(context)
        
        return self.env.env_file_path
        
    def get_env(self, programming_language: str) -> Env:
        if programming_language == "python":
            env_file_path: str = os.path.join(self.workspace_dir, "env.py")
            return PythonEnv(env_file_path)
        else:
            raise ValueError(f"Unsupported programming language: {programming_language}")
