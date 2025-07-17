from uuid import uuid4
from langchain.chat_models import init_chat_model
from langfuse.callback import CallbackHandler

from app.creation_steps.models import Metadata

from .renderer import context_renderer
from .models import (
    ConsistencyCheckRequest,
    ConsistencyCheckResponse,
    ConsistencyIssue,
    ArtifactLocation,
    ConsistencyIssueType,
)
from .prompts import structural_consistency_prompt, StructuralConsistencyResult


langfuse_handler = CallbackHandler()


class ConsistencyCheck:

    def __init__(self, model_name: str):
        self.model = init_chat_model(model_name)

    def check(self, request: ConsistencyCheckRequest) -> ConsistencyCheckResponse:
        trace_id = uuid4()

        input_data = {
            "problem_statement": request.problem_statement,
            "template_repository": [
                {"path": file.path, "content": file.content}
                for file in request.template_repository.files
            ],
            "solution_repository": [
                {"path": file.path, "content": file.content}
                for file in request.solution_repository.files
            ],
            "test_repository": [
                {"path": file.path, "content": file.content}
                for file in request.test_repository.files
            ],
        }

        structural_consistency_chain = (
            context_renderer("problem_statement", "template_repository")
            | structural_consistency_prompt
            | self.model.with_structured_output(StructuralConsistencyResult)
        )

        result: StructuralConsistencyResult = structural_consistency_chain.invoke(
            input_data,
            config={
                "callbacks": [langfuse_handler],
                "run_name": "consistency_check",
                "run_id": trace_id,
            },
        )

        # Convert StructuralConsistencyIssue to ConsistencyIssue for response
        converted_issues = []
        for issue in result.issues:
            # Convert ArtifactLocation from prompts format to models format
            primary_location = ArtifactLocation(
                type=issue.primary_location.type,
                file_path=issue.primary_location.file_path,
                start_line=issue.primary_location.start_line,
                end_line=issue.primary_location.end_line,
                description=None,
            )

            related_locations = []
            for loc in issue.related_locations:
                related_location = ArtifactLocation(
                    type=loc.type,
                    file_path=loc.file_path,
                    start_line=loc.start_line,
                    end_line=loc.end_line,
                    description=None,
                )
                related_locations.append(related_location)

            converted_issue = ConsistencyIssue(
                description=issue.description,
                severity=issue.severity,
                type=ConsistencyIssueType.STRUCTURAL,  # StructuralConsistencyIssue is always STRUCTURAL
                category=issue.category,
                primary_location=primary_location,
                related_locations=related_locations,
                suggested_fix=issue.suggested_fix,
            )
            converted_issues.append(converted_issue)

        return ConsistencyCheckResponse(
            issues=converted_issues,
            metadata=Metadata(trace_id=str(trace_id)),
        )
