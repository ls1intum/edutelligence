"""
Core service implementation for the consistency checker.
"""

import logging
import re
from typing import Dict

from langchain_core.prompts import PromptTemplate
from langfuse.callback import CallbackHandler

from app.settings import settings
from app.models import get_model
from app.consistency_checker.models import (
    ConsistencyIssue,
    ProgrammingExercise,
    ConsistencyCheckResponse,
)
from app.consistency_checker.prompts import solver_prompt, summarizer_prompt

logger = logging.getLogger(__name__)


class ConsistencyCheckerService:
    """
    A service for checking consistency between problem statements, template repositories, and solution repositories.
    """

    def __init__(self):
        """Initialize the consistency checker with language model."""
        callbacks = []
        if settings.langfuse_enabled:
            langfuse_handler = CallbackHandler()
            langfuse_handler.auth_check()
            callbacks.append(langfuse_handler)

        ChatModel = get_model(settings.MODEL_NAME)
        self.model = ChatModel().with_config(callbacks=callbacks)

        self.solver_prompt = PromptTemplate.from_template(solver_prompt)
        self.summarizer_prompt = PromptTemplate.from_template(summarizer_prompt)

    async def check_file_consistency(
        self,
        problem_statement: str,
        file_path: str,
        template_content: str,
        solution_content: str,
    ) -> str:
        """
        Check a single file for consistency issues.

        Args:
            problem_statement: The exercise problem statement
            file_path: Path to the file being checked
            template_content: Content of the template file
            solution_content: Content of the solution file

        Returns:
            Description of consistency issues found in the file, or empty string if none
        """
        prompt_args = {
            "problem_statement": problem_statement,
            "file_path": file_path,
            "template_file": template_content,
            "solution_file": solution_content,
        }

        formatted_prompt = self.solver_prompt.format(**prompt_args)
        response = await self.model.ainvoke(formatted_prompt)

        # Return empty string if no issues found
        if "no consistency issues found" in response.content.lower():
            return ""

        return response.content

    async def check_exercise_consistency(
        self, exercise: ProgrammingExercise
    ) -> ConsistencyCheckResponse:
        """
        Check an entire exercise for consistency issues.

        Args:
            exercise: The programming exercise to check

        Returns:
            ConsistencyCheckResponse with found issues and summary
        """
        try:
            # Get unique file paths from both repositories
            file_paths = set(exercise.template_repository.keys()) | set(
                exercise.solution_repository.keys()
            )

            # Check each file for consistency issues
            file_issues: Dict[str, str] = {}
            for file_path in file_paths:
                template_content = exercise.template_repository.get(
                    file_path, "File not found in template repository"
                )
                solution_content = exercise.solution_repository.get(
                    file_path, "File not found in solution repository"
                )

                issues = await self.check_file_consistency(
                    problem_statement=exercise.problem_statement,
                    file_path=file_path,
                    template_content=template_content,
                    solution_content=solution_content,
                )

                if issues:
                    file_issues[file_path] = issues

            # If no issues found, return early
            if not file_issues:
                return ConsistencyCheckResponse(
                    issues=[],
                    summary="No consistency issues were found in the exercise.",
                    status="success",
                )

            # Create structured issues list
            issues_list = [
                ConsistencyIssue(file_path=file_path, description=description)
                for file_path, description in file_issues.items()
            ]

            # Generate summary using the summarizer
            formatted_issues = "\n\n".join(
                [
                    f"File: {file_path}\n{description}"
                    for file_path, description in file_issues.items()
                ]
            )

            summary = await self._generate_summary(
                exercise.problem_statement, formatted_issues
            )

            return ConsistencyCheckResponse(
                issues=issues_list, summary=summary, status="success"
            )

        except Exception as e:
            logger.exception("Error checking exercise consistency: %s", str(e))
            return ConsistencyCheckResponse(
                issues=[],
                summary=f"Error checking consistency: {str(e)}",
                status="error",
            )

    async def _generate_summary(
        self, problem_statement: str, identified_issues: str
    ) -> str:
        """
        Generate a summary of the consistency issues.

        Args:
            problem_statement: The exercise problem statement
            identified_issues: The issues identified in each file

        Returns:
            A summary of all consistency issues
        """
        prompt_args = {
            "problem_statement": problem_statement,
            "identified_issues": identified_issues,
        }

        formatted_prompt = self.summarizer_prompt.format(**prompt_args)
        response = await self.model.ainvoke(formatted_prompt)
        result = response.content.strip()

        # Clean up common formatting issues
        if result.startswith("```") and result.endswith("```"):
            result = result[3:-3]
            if result.startswith("markdown"):
                result = result[8:]

        result = result.strip()

        # Remove redundant headings
        result = re.sub(r"^#\s*Consistency Issues Summary\s*\n", "", result)
        result = re.sub(r"^#\s*Summary\s*\n", "", result)

        return result
