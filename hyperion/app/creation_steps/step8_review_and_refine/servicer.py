import logging
import re
import time
from typing import Dict

from app.grpc import hyperion_pb2_grpc
from app.grpc.hyperion_pb2 import (
    InconsistencyCheckResponse,
    Priority,
    RewriteProblemStatementResponse,
    SuggestionItem,
)
from app.models import get_model
from app.settings import settings
from langchain_core.prompts import PromptTemplate

from .prompts import checker_prompt, prettify_prompt, rewrite_prompt

logger = logging.getLogger(__name__)


class ReviewAndRefineServicer(hyperion_pb2_grpc.ReviewAndRefineServicer):

    def CheckInconsistencies(self, request, context):
        logger.info("Running inconsistency check...")

        model = get_model(settings.MODEL_NAME)()

        # Set up the prompts and chains
        checker_prompt_template = PromptTemplate.from_template(checker_prompt)
        checker = checker_prompt_template | model

        prettify_prompt_template = PromptTemplate.from_template(prettify_prompt)
        prettify = prettify_prompt_template | model

        # Generate dict of file paths to their contents from both repositories
        template_files = {
            file.path: file.content for file in request.template_repository.files
        }
        solution_files = {
            file.path: file.content for file in request.solution_repository.files
        }

        # Get all unique file paths
        file_paths = set(template_files.keys()) | set(solution_files.keys())

        # First, for each file in the exercise, check for consistency issues via the solver
        consistency_issues: Dict[str, str] = {}
        checker_inputs = [
            {
                "file_path": file_path,
                "problem_statement": request.problem_statement,
                "template_file": template_files.get(file_path, "no file found"),
                "solution_file": solution_files.get(file_path, "no file found"),
            }
            for file_path in file_paths
        ]

        # Process each file and collect results
        file_responses = checker.map().invoke(checker_inputs)
        consistency_issues = {
            file_path: response.content
            for file_path, response in zip(file_paths, file_responses)
        }

        # Second, prettify the consistency issues and provide a summary
        formatted_consistency_issues = "\n".join(
            [
                f"<PotentialFileIssues filePath=`{file_path}`>\n{issues}\n</PotentialFileIssues>"
                for file_path, issues in consistency_issues.items()
            ]
        )

        summary_response = prettify.invoke(
            {
                "problem_statement": request.problem_statement,
                "consistency_issues": formatted_consistency_issues,
            }
        )

        result = summary_response.content.strip()

        # Remove ``` from start and end if exists
        if result.startswith("```") and result.endswith("```"):
            result = result[3:-3]
            if result.startswith("markdown"):
                result = result[8:]
            result = result.strip()

        # Remove first heading or heading containing 'Summary of Consistency Issues'
        result = re.sub(r"^#\s.*?\n", "", result)
        result = re.sub(r"^#+.*?Summary of Consistency Issues\s*\n", "", result)

        return InconsistencyCheckResponse(inconsistencies=result)

    def RewriteProblemStatement(self, request, context):
        logger.info("Rewriting problem statement text...")

        model = get_model(settings.MODEL_NAME)()

        # Set up the rewriting prompt and chain
        rewrite_prompt_template = PromptTemplate.from_template(rewrite_prompt)
        rewriter = rewrite_prompt_template | model

        # Rewrite the text
        response = rewriter.invoke({"text": request.text})
        rewritten_text = response.content.strip()

        return RewriteProblemStatementResponse(rewritten_text=rewritten_text)
    
    def SuggestImprovements(self, request, context):
        logger.info("Suggesting improvements for problem statement...")

        yield SuggestionItem(
            description=f"Here is the problem statement from the request: {request.problem_statement}",
            index_start=0,
            index_end=0,
            priority=Priority.LOW
        )
        
        # Add delay to observe streaming
        time.sleep(1)

        yield SuggestionItem(
            description="This is a low priority suggestion.",
            index_start=0,
            index_end=10,
            priority=Priority.LOW
        )
        
        # Add delay to observe streaming
        time.sleep(1)
        
        yield SuggestionItem(
            description="This is a medium priority suggestion.",
            index_start=11,
            index_end=20,
            priority=Priority.MEDIUM
        )
        
        # Add delay to observe streaming
        time.sleep(1)
                
        yield SuggestionItem(
            description="This is a high priority suggestion.",
            index_start=21,
            index_end=30,
            priority=Priority.HIGH
        )
