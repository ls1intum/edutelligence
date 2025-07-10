"""Phase 1: Solution Planning & Structure."""

import logging
import json
from typing import List, Dict, Any, TYPE_CHECKING
from langchain_core.language_models.chat_models import BaseLanguageModel

from .models import SolutionCreationContext, SolutionPlan, FileStructure
from .exceptions import SolutionCreatorException
from ..workspace.file_manager import FileManager

if TYPE_CHECKING:
    from app.grpc import hyperion_pb2

logger = logging.getLogger(__name__)


class CodeGenerator:
    """Phase 1: Solution Planning & Structure.

    This phase handles:
    - Step 1.1: Generate Solution Plan
    - Step 1.2: Define File Structure
    - Step 1.3: Generate Class and Function Headers
    - Step 1.4: Generate Core Logic
    """

    def __init__(self, model: BaseLanguageModel) -> None:
        """
        Args:
            model: The AI language model to use for solution generation
        """
        self.model: BaseLanguageModel = model
        self.file_manager: FileManager = FileManager()

    async def execute(
        self, context: SolutionCreationContext
    ) -> SolutionCreationContext:
        """Execute the complete planning phase."""
        logger.info("Starting Phase 1: Solution Planning & Structure")

        try:
            context = await self._step_1_1_generate_solution_plan(context)
            context = await self._step_1_2_define_file_structure(context)
            context = await self._step_1_3_generate_headers(context)
            context = await self._step_1_4_generate_core_logic(context)
            context = self._create_solution_repository(context)
        except Exception as e:
            logger.error(f"CodeGenerator execution failed: {e}", exc_info=True)
            raise SolutionCreatorException(f"CodeGenerator failed: {e}") from e

        logger.info("Completed Phase 1: Solution Planning & Structure")
        return context

    async def _step_1_1_generate_solution_plan(
        self, context: SolutionCreationContext
    ) -> SolutionCreationContext:
        """Step 1.1: Generate Solution Plan."""
        logger.info("Step 1.1: Generating solution plan")
        prompt: str = self._build_solution_planning_prompt(context)
        response = await self.model.ainvoke(prompt)
        solution_plan = self._parse_solution_plan_response(response.content)
        context.solution_plan = solution_plan
        logger.info("Solution plan generated successfully")
        return context

    def _build_solution_planning_prompt(self, context: SolutionCreationContext) -> str:
        """Build the prompt for AI-based solution planning.

        Args:
            context: The solution creation context

        Returns:
            Formatted prompt string for the AI model
        """
        prompt = f"""
            You are an expert software engineer tasked with creating a solution plan for a programming exercise.

            Problem Statement:
            Title: {context.boundary_conditions.title}
            Problem Statement: {context.boundary_conditions.problem_statement}

            Boundary Conditions:
            - Programming Language: {context.boundary_conditions.programming_language}
            - Project Type: {context.boundary_conditions.project_type}

            Please analyze the problem and provide a detailed solution plan.
            Consider the programming language and project type when making your recommendations.

            Your response must be a valid JSON object with the following structure:
            {{
                "architecture_description": "A detailed description of the "
                "high-level solution architecture and approach",
                "required_classes": ["List", "of", "class", "names", "needed"],
                "required_functions": ["list", "of", "function", "names", "needed"],
                "algorithms": ["list", "of", "algorithms", "to", "implement"],
                "design_patterns": ["list", "of", "design", "patterns", "to", "use"]
            }}

            Guidelines:
            1. Architecture description should explain the overall approach and structure
            2. Required classes should include all main classes needed for the solution
            3. Required functions should include key functions/methods (including main entry points)
            4. Algorithms should list specific algorithms or techniques to be implemented
            5. Design patterns should suggest appropriate patterns for the given language and problem complexity

            Ensure your response is valid JSON and follows the exact structure specified above.
            The JSON needs to be in valid format and complete. Only output the JSON, no other text.
        """
        return prompt.strip()

    def _parse_solution_plan_response(self, response: str) -> SolutionPlan:
        """Parse the response from the AI model into a SolutionPlan object."""
        logger.debug(
            f"Parsing solution plan response (first 100 chars): {response[:100]}"
        )
        try:
            parsed_data: Dict[str, Any] = json.loads(response.strip())

            architecture_description: str = parsed_data.get(
                "architecture_description", ""
            )
            required_classes: List[str] = parsed_data.get("required_classes", [])
            required_functions: List[str] = parsed_data.get("required_functions", [])
            algorithms: List[str] = parsed_data.get("algorithms", [])
            design_patterns: List[str] = parsed_data.get("design_patterns", [])

            if len(architecture_description) == 0:
                logger.debug(
                    "No architecture description found in response, using raw response"
                )
                architecture_description = response
            if len(required_classes) == 0:
                logger.debug(
                    "Required classes is not a list in response, using empty list"
                )
                required_classes = []
            if len(required_functions) == 0:
                logger.debug(
                    "Required functions is not a list in response, using empty list"
                )
                required_functions = []
            if len(algorithms) == 0:
                logger.debug("Algorithms is not a list in response, using empty list")
                algorithms = []
            if len(design_patterns) == 0:
                logger.debug(
                    "Design patterns is not a list in response, using empty list"
                )
                design_patterns = []

            logger.debug("Successfully parsed solution plan from JSON response")
            return SolutionPlan(
                architecture_description=architecture_description,
                required_classes=required_classes,
                required_functions=required_functions,
                algorithms=algorithms,
                design_patterns=design_patterns,
            )

        except json.JSONDecodeError as e:
            logger.warning(
                f"Invalid JSON in response, using fallback solution plan: {e}"
            )
        except (KeyError, ValueError, TypeError) as e:
            logger.warning(f"Invalid solution plan structure, using fallback: {e}")
        except Exception as e:
            logger.error(f"Unexpected error parsing solution plan, using fallback: {e}")

        logger.info(
            "Using fallback solution plan with raw response as architecture description"
        )
        return SolutionPlan(
            architecture_description=response,
            required_classes=[],
            required_functions=[],
            algorithms=[],
            design_patterns=[],
        )

    async def _step_1_2_define_file_structure(
        self, context: SolutionCreationContext
    ) -> SolutionCreationContext:
        """Step 1.2: Define File Structure."""
        logger.info("Step 1.2: Defining file structure")
        prompt: str = self._build_file_structure_prompt(context)
        response = await self.model.ainvoke(prompt)
        file_structure: FileStructure = self._parse_file_structure_response(
            response.content
        )
        context.file_structure = file_structure
        self.file_manager.create_file_structure(context, file_structure)
        logger.info("File structure defined successfully")
        return context

    def _build_file_structure_prompt(self, context: SolutionCreationContext) -> str:
        """Build the prompt for AI-based file structure definition.

        Args:
            context: The solution creation context

        Returns:
            Formatted prompt string for the AI model
        """
        solution_plan: SolutionPlan = context.solution_plan
        architecture_desc: str = (
            solution_plan.architecture_description
            if solution_plan
            else "No solution plan available"
        )
        required_classes: List[str] = (
            solution_plan.required_classes if solution_plan else []
        )
        required_functions: List[str] = (
            solution_plan.required_functions if solution_plan else []
        )

        prompt = f"""
            You are an expert software engineer tasked with defining the file
            structure for a programming exercise solution.

            Problem Statement:
            Title: {context.boundary_conditions.title}
            Problem Statement: {context.boundary_conditions.problem_statement}

            Boundary Conditions:
            - Programming Language: {context.boundary_conditions.programming_language}
            - Project Type: {context.boundary_conditions.project_type}

            Solution Plan:
            Architecture: {architecture_desc}
            Required Classes: {', '.join(required_classes) if required_classes else 'None specified'}
            Required Functions: {', '.join(required_functions) if required_functions else 'None specified'}

            Based on the above information, create an appropriate file and directory structure. Consider:

            1. **Programming Language Conventions**: Follow standard conventions
            for {context.boundary_conditions.programming_language}
            2. **Project Type Requirements**: Structure according to
            {context.boundary_conditions.project_type} project type
            3. **Solution Architecture**: Organize files to support the planned solution architecture
            4. **Best Practices**: Use industry-standard project organization

            Your response must be a valid JSON object with the following structure:
            {{
                "directories": ["list", "of", "directory", "paths", "to", "create"],
                "files": ["list", "of", "source", "file", "paths", "to", "create"],
                "build_files": ["list", "of", "build", "configuration", "files"]
            }}

            Guidelines by Project Type:
            - **PLAIN**: Simple directory structure with source files
            - **PLAIN_MAVEN**: Standard Maven directory structure (src/main/java, src/test/java, pom.xml)
            - **PLAIN_GRADLE**: Standard Gradle structure (src/main/java, src/test/java, build.gradle)

            Guidelines by Programming Language:
            - **JAVA**: Use package structure, .java files, appropriate build files
            - **PYTHON**: Use module structure, .py files, setup.py or requirements.txt if needed

            Ensure all paths use forward slashes and are relative to the project root.
            Only output the JSON, no other text.
        """
        return prompt.strip()

    def _parse_file_structure_response(self, response: str) -> FileStructure:
        """Parse the response from the AI model into a FileStructure object."""
        logger.debug(
            f"Parsing file structure response (first 100 chars): {response[:100]}"
        )
        try:
            parsed_data: Dict[str, Any] = json.loads(response.strip())

            directories: List[str] = parsed_data.get("directories", [])
            files: List[str] = parsed_data.get("files", [])
            build_files: List[str] = parsed_data.get("build_files", [])

            directories: List[str] = [
                d.strip().replace("\\", "/") for d in directories if d.strip()
            ]
            files: List[str] = [
                f.strip().replace("\\", "/") for f in files if f.strip()
            ]
            build_files: List[str] = [
                b.strip().replace("\\", "/") for b in build_files if b.strip()
            ]

            logger.debug(
                f"Successfully parsed file structure: {len(directories)} dirs, "
                f"{len(files)} files, {len(build_files)} build files"
            )
            return FileStructure(
                directories=directories, files=files, build_files=build_files
            )

        except json.JSONDecodeError as e:
            logger.warning(
                f"Invalid JSON in file structure response, using fallback: {e}"
            )
        except (KeyError, ValueError, TypeError) as e:
            logger.warning(f"Invalid file structure format, using fallback: {e}")
        except Exception as e:
            logger.error(
                f"Unexpected error parsing file structure, using fallback: {e}"
            )

        logger.info("Using empty file structure as fallback")
        return FileStructure(directories=[], files=[], build_files=[])

    async def _step_1_3_generate_headers(
        self, context: SolutionCreationContext
    ) -> SolutionCreationContext:
        """Step 1.3: Generate Class and Function Headers."""
        logger.info("Step 1.3: Generating class and function headers")
        if not context.file_structure or not context.file_structure.files:
            logger.warning("No source files in structure, skipping header generation.")
            return context

        source_files = context.file_structure.files
        for file_path in source_files:
            logger.debug(f"Generating headers for file: {file_path}")
            prompt: str = self._build_file_headers_prompt(context, file_path)
            response = await self.model.ainvoke(prompt)
            headers_content: str = self._parse_file_headers_response(
                response.content, file_path
            )
            self.file_manager.write_file(context, file_path, headers_content)
            logger.debug(f"Headers generated and written for: {file_path}")

        logger.info("Class and function headers generated successfully")
        return context

    def _build_file_headers_prompt(
        self, context: SolutionCreationContext, file_path: str
    ) -> str:
        """Build the prompt for generating file headers.

        Args:
            context: The solution creation context
            file_path: Path to the file to generate headers for

        Returns:
            Formatted prompt string for the AI model
        """
        solution_plan: SolutionPlan = context.solution_plan
        architecture_desc: str = (
            solution_plan.architecture_description
            if solution_plan
            else "No solution plan available"
        )
        required_classes: List[str] = (
            solution_plan.required_classes if solution_plan else []
        )
        required_functions: List[str] = (
            solution_plan.required_functions if solution_plan else []
        )
        algorithms: List[str] = solution_plan.algorithms if solution_plan else []
        file_purpose: str = self._determine_file_purpose(file_path, context)

        all_files: List[str] = (
            context.file_structure.files if context.file_structure else []
        )

        prompt = f"""
            You are an expert software engineer tasked with generating class and
            function headers for a specific file in a programming exercise solution.

            Problem Statement:
            Title: {context.boundary_conditions.title}
            Problem Statement: {context.boundary_conditions.problem_statement}

            Boundary Conditions:
            - Programming Language: {context.boundary_conditions.programming_language}
            - Project Type: {context.boundary_conditions.project_type}

            Solution Plan:
            Architecture: {architecture_desc}
            Required Classes: {', '.join(required_classes) if required_classes else 'None specified'}
            Required Functions: {', '.join(required_functions) if required_functions else 'None specified'}
            Algorithms: {', '.join(algorithms) if algorithms else 'None specified'}

            File Structure Context:
            All Files: {', '.join(all_files)}
            Current File: {file_path}
            File Purpose: {file_purpose}

            Generate the complete header structure for the file "{file_path}". Include:

            1. **File Header Comment**: Brief description of the file's purpose and contents
            2. **Imports/Includes**: Necessary imports for the programming language
            3. **Class Definitions**: All classes that should be in this file with:
            - Class documentation/comments
            - Constructor/init method signatures
            - Method signatures with parameters and return types
            - Property definitions where appropriate
            4. **Function Definitions**: Standalone functions with:
            - Function documentation/comments
            - Parameter definitions with types
            - Return type annotations
            5. **Constants/Variables**: Any module-level constants or variables

            Requirements:
            - **NO IMPLEMENTATION**: Only signatures, headers, and documentation
            - **Language Conventions**: Follow
            {context.boundary_conditions.programming_language} naming and style conventions
            - **Type Annotations**: Include proper type hints/annotations where supported
            - **Documentation**: Add docstrings/comments explaining purpose of each element
            - **Proper Structure**: Organize code logically within the file

            Generate ONLY the code content for this file. Do not include explanations or markdown formatting.
        """
        return prompt.strip()

    def _parse_file_headers_response(self, response: str, file_path: str) -> str:
        """Parse the response from the AI model for file headers."""
        logger.debug(
            f"Parsing headers for {file_path} (first 100 chars): {response[:100]}"
        )
        try:
            content = response.strip()

            # Remove markdown code blocks if present
            if content.startswith("```"):
                lines = content.split("\n")
                # Remove first line (```language)
                if lines[0].startswith("```"):
                    lines = lines[1:]
                # Remove last line (```)
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                content = "\n".join(lines)

            # Ensure content ends with newline
            if content and not content.endswith("\n"):
                content += "\n"

            logger.debug(
                f"Successfully parsed headers for {file_path}: {len(content)} characters"
            )
            return content

        except Exception as e:
            logger.error(f"Error parsing headers response for {file_path}: {e}")
            return response.strip() + "\n"

    def _determine_file_purpose(
        self, file_path: str, context: SolutionCreationContext
    ) -> str:
        """Determine the purpose of a file based on its path and context.

        Args:
            file_path: Path to the file
            context: The solution creation context

        Returns:
            Description of the file's purpose
        """
        file_name = file_path.split("/")[-1].lower()
        path_parts = file_path.lower().split("/")

        if "test" in file_name or "test" in path_parts:
            return "Test file containing unit tests for the solution"
        elif "main" in file_name:
            return "Main entry point file containing the primary application logic"
        elif any(part in path_parts for part in ["src", "main"]):
            return "Source file containing core solution implementation"
        elif (
            file_name.endswith("util.py")
            or file_name.endswith("utils.py")
            or file_name.endswith("helper.py")
        ):
            return "Utility file containing helper functions and common utilities"
        elif file_name.endswith("config.py") or file_name.endswith("settings.py"):
            return "Configuration file containing application settings and constants"
        else:
            return "Source file containing solution components"

    async def _step_1_4_generate_core_logic(
        self, context: SolutionCreationContext
    ) -> SolutionCreationContext:
        """Step 1.4: Generate Core Logic."""
        logger.info("Step 1.4: Generating core logic")
        if not context.file_structure or not context.file_structure.files:
            logger.warning("No source files in structure, skipping logic generation.")
            return context

        source_files = context.file_structure.files
        for file_path in source_files:
            logger.debug(f"Generating core logic for file: {file_path}")
            existing_content: str = self.file_manager.read_file(context, file_path)
            prompt: str = self._build_implementation_prompt(
                context, file_path, existing_content
            )
            response = await self.model.ainvoke(prompt)
            implementation_content: str = response.content
            self.file_manager.write_file(context, file_path, implementation_content)
            logger.debug(f"Core logic generated and written for: {file_path}")

        logger.info("Core logic generated successfully for all files")
        return context

    def _build_implementation_prompt(
        self, context: SolutionCreationContext, file_path: str, existing_content: str
    ) -> str:
        """Build the prompt for generating complete file implementation.

        Args:
            context: The solution creation context
            file_path: Path to the file to generate implementation for
            existing_content: Current content of the file (headers)

        Returns:
            Formatted prompt string for the AI model
        """
        solution_plan: SolutionPlan = context.solution_plan
        architecture_desc: str = (
            solution_plan.architecture_description
            if solution_plan
            else "No solution plan available"
        )
        required_classes: List[str] = (
            solution_plan.required_classes if solution_plan else []
        )
        required_functions: List[str] = (
            solution_plan.required_functions if solution_plan else []
        )
        algorithms: List[str] = solution_plan.algorithms if solution_plan else []
        file_purpose: str = self._determine_file_purpose(file_path, context)

        other_files_context: str = self._get_other_files_context(context, file_path)

        prompt = f"""
            You are an expert software engineer tasked with implementing the complete
            logic for a specific file in a programming exercise solution.

            Problem Statement:
            Title: {context.boundary_conditions.title}
            Description: {context.boundary_conditions.description}

            Boundary Conditions:
            - Programming Language: {context.boundary_conditions.programming_language}
            - Project Type: {context.boundary_conditions.project_type}
            - Difficulty: {context.boundary_conditions.difficulty}

            Solution Plan:
            Architecture: {architecture_desc}
            Required Classes: {', '.join(required_classes) if required_classes else 'None specified'}
            Required Functions: {', '.join(required_functions) if required_functions else 'None specified'}
            Algorithms: {', '.join(algorithms) if algorithms else 'None specified'}

            File Context:
            Current File: {file_path}
            File Purpose: {file_purpose}

            Current File Headers:
            {existing_content}

            Other Files Context:
            {other_files_context}

            Generate the complete implementation for the file "{file_path}". Requirements:

            1. **Complete Implementation**: Fill in all method bodies and function implementations
            2. **Algorithm Implementation**: Implement the required algorithms and logic
            3. **Error Handling**: Add appropriate error handling and validation
            4. **Documentation**: Maintain existing documentation and add implementation comments
            5. **Integration**: Ensure the implementation works with other files in the project
            6. **Best Practices**: Follow
            {context.boundary_conditions.programming_language} best practices and conventions

            Important Guidelines:
            - **Replace the entire file content** with the complete implementation
            - **Keep existing structure** but add full implementation
            - **Implement all methods and functions** completely
            - **Add necessary imports** at the top of the file
            - **Follow the solution plan** and architecture requirements
            - **Make it functional** - the code should be executable and solve the problem

            Generate ONLY the complete file content. Do not include explanations or markdown formatting.
        """
        return prompt.strip()

    def _get_other_files_context(
        self, context: SolutionCreationContext, current_file_path: str
    ) -> str:
        """Get context about other files in the project.

        Args:
            context: The solution creation context
            current_file_path: Path to the current file

        Returns:
            String containing context about other files
        """
        if not context.file_structure or not context.file_structure.files:
            return "No other files in the project."

        other_files = [
            f for f in context.file_structure.files if f != current_file_path
        ]

        if not other_files:
            return "No other files in the project."

        context_lines = []
        for file_path in other_files[
            :5
        ]:  # Limit to first 5 files to avoid token limits
            try:
                file_content = self.file_manager.read_file(context, file_path)
                file_preview = self._get_file_preview(file_content, file_path)
                context_lines.append(f"File: {file_path}\n{file_preview}")
            except Exception as e:
                context_lines.append(f"File: {file_path}\nError reading file: {e}")

        return "\n\n".join(context_lines)

    def _get_file_preview(self, content: str, file_path: str) -> str:
        """Get a preview of a file's content.

        Args:
            content: The file content
            file_path: Path to the file

        Returns:
            String containing a preview of the file content
        """
        if not content.strip():
            return "Empty file"

        lines = content.split("\n")
        if len(lines) <= 20:
            return content

        # Show first 10 lines and last 5 lines
        preview_lines = lines[:10] + ["... (content truncated) ..."] + lines[-5:]
        return "\n".join(preview_lines)

    def _create_solution_repository(
        self, context: SolutionCreationContext
    ) -> SolutionCreationContext:
        """Create the solution repository from the generated files.

        Args:
            context: The solution creation context

        Returns:
            Updated context with solution repository
        """
        logger.info("Creating solution repository from generated files")

        try:
            # Import at runtime to avoid protobuf version issues
            from app.grpc import hyperion_pb2

            repository_files = []

            if context.file_structure:
                # Add source files
                for file_path in context.file_structure.files:
                    try:
                        file_content = self.file_manager.read_file(context, file_path)
                        repository_files.append(
                            hyperion_pb2.RepositoryFile(
                                path=file_path, content=file_content
                            )
                        )
                        logger.debug(f"Added file to repository: {file_path}")
                    except Exception as e:
                        logger.warning(f"Failed to read file {file_path}: {e}")

                # Add build files
                for file_path in context.file_structure.build_files:
                    try:
                        file_content = self.file_manager.read_file(context, file_path)
                        repository_files.append(
                            hyperion_pb2.RepositoryFile(
                                path=file_path, content=file_content
                            )
                        )
                        logger.debug(f"Added build file to repository: {file_path}")
                    except Exception as e:
                        logger.warning(f"Failed to read build file {file_path}: {e}")

            context.solution_repository = hyperion_pb2.Repository(
                files=repository_files
            )
            logger.info(
                f"Solution repository created with {len(repository_files)} files"
            )

        except Exception as e:
            logger.error(f"Failed to create solution repository: {e}")
            # Import at runtime to avoid protobuf version issues
            from app.grpc import hyperion_pb2

            context.solution_repository = hyperion_pb2.Repository(files=[])

        return context
