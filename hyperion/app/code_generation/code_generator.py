"""
Main orchestrator for the code generation pipeline.
Controls the flow between different components and manages the overall process
from problem parsing to code generation and evaluation.
"""

from app.models import get_model
import os
import uuid

from .components import (
    ProblemParser,
    SolutionPlanner,
    StructureDesigner,
    SignatureGenerator,
    ImplementationGenerator,
    ExecutionEngine,
    OutputEvaluator,
    CodeFixer
)

from .prompts import (
    ProblemParsingPrompt,
    SolutionPlanningPrompt,
    StructureDesignPrompt,
    SignatureGenerationPrompt,
    ImplementationGenerationPrompt,
    OutputEvaluationPrompt,
    CodeFixingPrompt
)

from .utils import EnvManager, CodeRunner, Logger

class CodeGenerator:
    
    def __init__(self, workspace_dir=None, max_iterations=3):
        """
        Initialize the code generator with components and utilities.
        
        Args:
            workspace_dir (str, optional): Directory for generated code
            max_iterations (int): Maximum number of fix iterations
        """
        self.model = get_model()
        
        if workspace_dir is None:
            base_dir = os.path.join(os.path.dirname(__file__), '_temp')
            self.workspace_dir = os.path.join(base_dir, f"gen_{uuid.uuid4().hex[:8]}")
        else:
            self.workspace_dir = workspace_dir
        
        self.max_iterations = max_iterations
        
        # Initialize utilities
        self.env_manager = EnvManager(self.workspace_dir)
        self.code_runner = CodeRunner(self.workspace_dir)
        self.logger = Logger()
        
        # Initialize components with their corresponding prompts
        self.problem_parser = ProblemParser(ProblemParsingPrompt())
        self.solution_planner = SolutionPlanner(SolutionPlanningPrompt())
        self.structure_designer = StructureDesigner(StructureDesignPrompt())
        self.signature_generator = SignatureGenerator(SignatureGenerationPrompt())
        self.implementation_generator = ImplementationGenerator(ImplementationGenerationPrompt())
        self.execution_engine = ExecutionEngine()
        self.output_evaluator = OutputEvaluator(OutputEvaluationPrompt())
        self.code_fixer = CodeFixer(CodeFixingPrompt())
        
    def generate(self, problem_statement):
        """
        Execute the full code generation pipeline based on a problem statement.
        
        Args:
            problem_statement (str): The description of the coding problem to solve
            
        Returns:
            dict: Results of the code generation process including generated files and execution status
        """
        self.logger.info("Starting code generation process")
        
        self.logger.info("Parsing problem statement")
        parsed_problem = self.problem_parser.process(problem_statement)
        
        self.logger.info("Generating solution plan")
        solution_plan = self.solution_planner.process(parsed_problem)
        
        self.logger.info("Defining file structure")
        file_structure = self.structure_designer.process(solution_plan)
        
        for directory in file_structure.get("directories", []):
            os.makedirs(os.path.join(self.workspace_dir, directory), exist_ok=True)
        
        self.logger.info("Generating code signatures")
        signatures = self.signature_generator.process(file_structure)
        
        self.logger.info("Generating implementation code")
        implementation = self.implementation_generator.process(signatures)
        
        for file_path, content in implementation.get("implementation", {}).items():
            self.env_manager.create_file(file_path, content)
        
        self.logger.info("Executing generated code")
        main_file = implementation.get("main_file", "")
        execution_results = self.execution_engine.process({"main_file": main_file, "implementation": implementation})
        
        self.logger.info("Evaluating execution results")
        evaluation = self.output_evaluator.process(execution_results)
        
        iterations = 0
        while (not evaluation.get("success", False) and 
               iterations < self.max_iterations):
            self.logger.info(f"Code requires fixes. Starting iteration {iterations+1}")
            
            fixed_implementation = self.code_fixer.process({
                "evaluation": evaluation,
                "implementation": implementation
            })
            
            implementation = fixed_implementation.get("fixed_implementation", implementation)
            
            for file_path, content in implementation.items():
                self.env_manager.create_file(file_path, content)
            
            execution_results = self.execution_engine.process({"main_file": main_file, "implementation": implementation})
            evaluation = self.output_evaluator.process(execution_results)
            
            iterations += 1

        success = evaluation.get("success", False)
        status_msg = "Code generation successful" if success else "Code generation failed after fixes"
        self.logger.info(status_msg)
        
        return {
            "success": success,
            "workspace_dir": self.workspace_dir,
            "parsed_problem": parsed_problem,
            "solution_plan": solution_plan,
            "file_structure": file_structure,
            "implementation": implementation,
            "execution_results": execution_results,
            "evaluation": evaluation,
            "iterations": iterations
        }
