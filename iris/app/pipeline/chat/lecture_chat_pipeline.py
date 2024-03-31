import logging
from typing import List

from langchain_core.prompts import (
    ChatPromptTemplate,
    AIMessagePromptTemplate,
    SystemMessagePromptTemplate,
)
from langchain_core.runnables import Runnable

from ..prompts.iris_tutor_chat_prompts import (
    iris_lecture_initial_system_prompt,
    chat_history_system_prompt,
    guide_lecture_system_prompt,
)
from ...content_service.Retrieval.lecture_retrieval import LectureRetrieval
from ...domain import TutorChatPipelineExecutionDTO
from ...domain.data.message_dto import MessageDTO
from ...vector_database.lectureschema import LectureSchema
from ...web.status.status_update import TutorChatStatusCallback
from ...llm.langchain import IrisLangchainChatModel, IrisLangchainEmbeddingModel
from ..pipeline import Pipeline
from weaviate import WeaviateClient
from ...vector_database.db import VectorDatabase
from ..shared.summary_pipeline import add_conversation_to_prompt

logger = logging.getLogger(__name__)


class LectureChatPipeline(Pipeline):
    """Exercise chat pipeline that answers exercises related questions from students."""

    llm: IrisLangchainChatModel
    llm_embedding: IrisLangchainEmbeddingModel
    pipeline: Runnable
    callback: TutorChatStatusCallback
    prompt: ChatPromptTemplate
    db: WeaviateClient
    retriever: LectureRetrieval

    def __init__(
        self,
        callback: TutorChatStatusCallback,
        pipeline: Runnable,
        llm: IrisLangchainChatModel,
        llm_embedding: IrisLangchainEmbeddingModel,
    ):
        super().__init__(implementation_id="lecture_chat_pipeline")
        self.llm = llm
        self.llm_embedding = llm_embedding
        self.callback = callback
        self.pipeline = pipeline
        self.db = VectorDatabase().client
        self.retriever = LectureRetrieval(self.db)

    def __repr__(self):
        return f"{self.__class__.__name__}(llm={self.llm})"

    def __str__(self):
        return f"{self.__class__.__name__}(llm={self.llm})"

    def __call__(self, dto: TutorChatPipelineExecutionDTO, **kwargs):
        """
        Runs the pipeline
            :param kwargs: The keyword arguments
        """
        # Set up the initial prompt
        self.prompt = ChatPromptTemplate.from_messages(
            [
                ("system", iris_lecture_initial_system_prompt),
                ("system", chat_history_system_prompt),
            ]
        )
        logger.info("Running tutor chat pipeline...")
        history: List[MessageDTO] = dto.chat_history[:-1]
        query: MessageDTO = dto.chat_history[-1]

        # Add the chat history and user question to the prompt
        self.prompt = add_conversation_to_prompt(history, query, self.prompt)
        self.callback.in_progress("Looking up files in the repository...")
        retrieved_lecture_chunks = self.retriever.retrieve(
            query.contents[0].text_content,
            hybrid_factor=1,
            embedding_vector=self.llm_embedding.embed_query(
                query.contents[0].text_content
            ),
        )
        self._add_relevant_chunks_to_prompt(retrieved_lecture_chunks)
        self.prompt += SystemMessagePromptTemplate.from_template(
            "Answer the user query based on the above provided Context"
        )
        self.callback.done("Looked up files in the repository")
        self.callback.in_progress("Generating response...")
        try:
            response_draft = (self.prompt | self.pipeline).invoke({})
            self.prompt += AIMessagePromptTemplate.from_template(f"{response_draft}")
            self.prompt += SystemMessagePromptTemplate.from_template(
                guide_lecture_system_prompt
            )
            response = (self.prompt | self.pipeline).invoke({})
            logger.info(f"Response from Lecture chat pipeline: {response}")
            self.callback.done("Generated response", final_result=response)
        except Exception as e:
            self.callback.error(f"Failed to generate response: {e}")

    def _add_relevant_chunks_to_prompt(self, retrieved_lecture_chunks: List[dict]):
        """
        Adds the relevant chunks of the lecture to the prompt
        :param retrieved_lecture_chunks: The retrieved lecture chunks
        """
        # Iterate over the chunks to create formatted messages for each
        for i, chunk in enumerate(retrieved_lecture_chunks, start=1):
            text_content_msg = (
                f" {chunk.get(LectureSchema.PAGE_TEXT_CONTENT)}" + "\n"
            )
            text_content_msg = text_content_msg.replace("{", "{{").replace("}", "}}")
            self.prompt += SystemMessagePromptTemplate.from_template(text_content_msg)
