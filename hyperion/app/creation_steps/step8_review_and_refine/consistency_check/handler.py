from typing import Dict, List
from uuid import uuid4
from langchain.chat_models import init_chat_model
from langchain_core.runnables import RunnableParallel, RunnableLambda
from langfuse.callback import CallbackHandler

from app.models.openrouter import ChatOpenRouter

from .models import (
    Metadata,
    ConsistencyCheckRequest,
    ConsistencyCheckResponse,
    ConsistencyIssue,
)
from .checker.structural import init_structural_checker
from .checker.semantic import init_semantic_checker


langfuse_handler = CallbackHandler()


class ConsistencyCheck:

    def __init__(self, model_name: str):
        if model_name.startswith("openrouter:"):
            self.model = ChatOpenRouter(
                model_name=model_name.replace("openrouter:", ""),
            )
        else:
            self.model = init_chat_model(model_name)

    def check(self, request: ConsistencyCheckRequest) -> ConsistencyCheckResponse:
        trace_id = uuid4()

        input_data = {
            "problem_statement": request.problem_statement,
            "programming_language": request.programming_language,
            "template_repository": [
                {"path": file.path, "content": file.content}
                for file in request.template_repository.files
            ],
        }

        # Add optional repositories if they exist
        if request.solution_repository:
            input_data["solution_repository"] = [
                {"path": file.path, "content": file.content}
                for file in request.solution_repository.files
            ]

        if request.test_repository:
            input_data["test_repository"] = [
                {"path": file.path, "content": file.content}
                for file in request.test_repository.files
            ]

        structural_checker = init_structural_checker(self.model)
        semantic_checker = init_semantic_checker(self.model)

        def merge_issues(results: Dict) -> List[ConsistencyIssue]:
            """Merge issues from results."""
            return [issue for result in results.values() for issue in result.issues]

        merge = RunnableLambda(merge_issues, name="merge_issues")

        checker = (
            RunnableParallel(
                {
                    "structural": structural_checker,
                    "semantic": semantic_checker,
                }
            )
            | merge
        ).with_config(
            {
                "callbacks": [langfuse_handler],
                "run_name": "consistency_check",
                "run_id": trace_id,
            }
        )

        issues = checker.invoke(input_data)

        return ConsistencyCheckResponse(
            issues=issues,
            metadata=Metadata(trace_id=str(trace_id)),
        )
