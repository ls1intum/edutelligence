import re
import logging
from typing import Dict, Callable, Awaitable

from langchain_core.prompts import PromptTemplate
from langfuse.callback import CallbackHandler

from app.settings import settings
from app.models import get_model
from app.actions.base_models import ActionInput, ActionUpdate

from .models import (
    ConsistencyCheckInput,
    ConsistencyCheckProgressUpdate,
    ConsistencyCheckResult,
    ConsistencyIssue
)
from .prompts import detector_prompt, summarizer_prompt

logger = logging.getLogger(__name__)
ActionUpdateCallback = Callable[[ActionUpdate], Awaitable[None]]

class ConsistencyCheckHandler:
    """Handler for consistency check actions."""
    action_name = "consistency_check"
    
    def __init__(self):
        """Initialize the consistency check handler."""
        callbacks = []
        if settings.langfuse_enabled:
            langfuse_handler = CallbackHandler()
            langfuse_handler.auth_check()
            callbacks.append(langfuse_handler)

        ChatModel = get_model(settings.MODEL_NAME)
        self.model = ChatModel().with_config(callbacks=callbacks)

        self.detector_prompt = PromptTemplate.from_template(detector_prompt)
        self.summarizer_prompt = PromptTemplate.from_template(summarizer_prompt)
        
    async def handle(self, input_data: ActionInput, send_update: ActionUpdateCallback) -> ActionUpdate:
        """
        Handle a consistency check request.
        
        Args:
            input_data: Input data for the consistency check
            send_update: Callback to send progress updates
            
        Returns:
            The final result of the consistency check
        """
        if not isinstance(input_data, ConsistencyCheckInput):
            raise TypeError("Input data must be a ConsistencyCheckInput instance")
            
        try:
            return await self._check_exercise_consistency(input_data, send_update)
        except Exception as e:
            logger.exception("Error during consistency check: %s", str(e))
            return ConsistencyCheckResult(
                issues=[],
                summary=f"Job execution failed: {str(e)}",
                status="error"
            )
    
    async def _check_file_consistency(
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

        formatted_prompt = self.detector_prompt.format(**prompt_args)
        response = await self.model.ainvoke(formatted_prompt)

        # Return empty string if no issues found
        if "no consistency issues found" in response.content.lower():
            return ""

        return response.content

    async def _check_exercise_consistency(
        self, exercise: ConsistencyCheckInput, send_update: ActionUpdateCallback
    ) -> ConsistencyCheckResult:
        """
        Check an entire exercise for consistency issues.

        Args:
            exercise: The programming exercise to check
            send_update: Callback to send updates

        Returns:
            ConsistencyCheckResponse with found issues and summary
        """
        # Get unique file paths from both repositories
        file_paths = set(exercise.template_repository.keys()) | set(
            exercise.solution_repository.keys()
        )
        total_files = len(file_paths)
        
        # Send initial update
        await send_update(ConsistencyCheckProgressUpdate(
            status_message=f"Starting consistency check for {total_files} files",
            progress=0,
            files_processed=0,
            total_files=total_files
        ))

        # Check each file for consistency issues
        file_issues: Dict[str, str] = {}
        for idx, file_path in enumerate(file_paths):
            template_content = exercise.template_repository.get(
                file_path, "File not found in template repository"
            )
            solution_content = exercise.solution_repository.get(
                file_path, "File not found in solution repository"
            )

            issues = await self._check_file_consistency(
                problem_statement=exercise.problem_statement,
                file_path=file_path,
                template_content=template_content,
                solution_content=solution_content,
            )

            if issues:
                file_issues[file_path] = issues
            
            # Send progress update periodically
            if idx % 3 == 0 or idx == len(file_paths) - 1:
                files_processed = idx + 1
                percent = (files_processed / total_files) * 100
                await send_update(ConsistencyCheckProgressUpdate(
                    status_message=f"Processed {files_processed}/{total_files} files",
                    progress=percent,
                    files_processed=files_processed,
                    total_files=total_files
                ))

        # If no issues found, return early
        if not file_issues:
            return ConsistencyCheckResult(
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

        # Send update that we're generating summary
        await send_update(ConsistencyCheckProgressUpdate(
            status_message="Generating summary of found issues",
            progress=95,
            files_processed=total_files,
            total_files=total_files
        ))

        summary = await self._generate_summary(
            exercise.problem_statement, formatted_issues
        )

        return ConsistencyCheckResult(
            issues=issues_list, 
            summary=summary, 
            status="success"
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