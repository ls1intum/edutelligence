from uuid import uuid4
from langchain.chat_models import init_chat_model
from langfuse.callback import CallbackHandler

from .renderer import context_renderer
from .models import convert_result_to_protobuf, StructuralConsistencyResult
from .prompts import structural_consistency_prompt

from app.grpc.hyperion_pb2 import (
    ConsistencyCheckRequest,
    ConsistencyCheckResponse,
    Metadata,
)

langfuse_handler = CallbackHandler()


class ConsistencyCheck:
    
    def __init__(self, model_name: str, model_provider: str):
        self.model = init_chat_model(model_name, model_provider=model_provider)

    def check_consistency(self, request: ConsistencyCheckRequest) -> ConsistencyCheckResponse:
        trace_id = uuid4()
        
        input_data = {
            "problem_statement": request.problem_statement,
            "template_repository": [{ "path": file.path, "content": file.content } for file in request.template_repository.files],
            "solution_repository": [{ "path": file.path, "content": file.content } for file in request.solution_repository.files],
            "test_repository": [{ "path": file.path, "content": file.content } for file in request.test_repository.files]
        }

        structural_consistency_chain = (
            context_renderer("problem_statement", "template_repository") 
          | structural_consistency_prompt
          | self.model.with_structured_output(StructuralConsistencyResult)
        )

        result: StructuralConsistencyResult = structural_consistency_chain.invoke(
            input_data, 
            config={ 
                "callbacks":[ langfuse_handler ], 
                "run_name": "consistency_check", 
                "run_id": trace_id 
            }
        )

        return ConsistencyCheckResponse(issues=convert_result_to_protobuf(result), metadata=Metadata(traceId=str(trace_id)))
