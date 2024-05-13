from app.domain import PipelineExecutionDTO
from app.domain.chat.chat_pipeline_execution_base_data_dto import ChatPipelineExecutionBaseDataDTO


class ChatPipelineExecutionDTO(PipelineExecutionDTO):
    base: ChatPipelineExecutionBaseDataDTO
