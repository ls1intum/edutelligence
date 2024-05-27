import base64
import os
import tempfile
import threading
from asyncio.log import logger
import fitz
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from weaviate import WeaviateClient
from weaviate.classes.query import Filter
from . import Pipeline
from ..domain import IrisMessageRole, PyrisMessage
from ..domain.data.image_message_content_dto import ImageMessageContentDTO

from ..domain.data.lecture_unit_dto import LectureUnitDTO
from app.domain.ingestion.ingestion_pipeline_execution_dto import (
    IngestionPipelineExecutionDto,
)
from ..domain.data.text_message_content_dto import TextMessageContentDTO
from ..llm.langchain import IrisLangchainChatModel
from ..vector_database.lecture_schema import init_lecture_schema, LectureSchema
from ..ingestion.abstract_ingestion import AbstractIngestion
from ..llm import (
    BasicRequestHandler,
    CompletionArguments,
    CapabilityRequestHandler,
    RequirementList,
)
from ..web.status import IngestionStatusCallback
from typing import TypedDict, Optional

batch_update_lock = threading.Lock()


def cleanup_temporary_file(file_path):
    """
    Cleanup the temporary file
    """
    try:
        os.remove(file_path)
    except OSError as e:
        logger.error(f"Failed to remove temporary file {file_path}: {e}")


def save_pdf(pdf_file_base64):
    """
    Save the pdf file to a temporary file
    """
    binary_data = base64.b64decode(pdf_file_base64)
    fd, temp_pdf_file_path = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    with open(temp_pdf_file_path, "wb") as temp_pdf_file:
        try:
            temp_pdf_file.write(binary_data)
        except Exception as e:
            logger.error(f"Failed to write to temporary PDF file {temp_pdf_file_path}: {e}")
            raise
    return temp_pdf_file_path


class PageData(TypedDict):
    """
    Page data to be ingested
    """

    lecture_id: int
    lecture_name: str
    lecture_unit_id: int
    lecture_unit_name: str
    course_id: int
    course_name: str
    course_description: str
    page_number: int
    page_text_content: str
    page_image_description: Optional[str]
    page_base64: Optional[str]


class LectureIngestionPipeline(AbstractIngestion, Pipeline):

    def __init__(
        self,
        client: WeaviateClient,
        dto: IngestionPipelineExecutionDto,
        callback: IngestionStatusCallback,
    ):
        super().__init__()
        self.collection = init_lecture_schema(client)
        self.dto = dto
        self.llm_vision = BasicRequestHandler("azure-gpt-4-vision")
        self.llm_chat = BasicRequestHandler("azure-gpt-35-turbo")# TODO change use langain model
        self.llm_embedding = BasicRequestHandler("embedding-small")
        self.callback = callback
        request_handler = CapabilityRequestHandler(
            requirements=RequirementList(
                gpt_version_equivalent=3.5,
                context_length=16385,
                privacy_compliance=True,
            )
        )
        completion_args = CompletionArguments(temperature=0.2, max_tokens=2000)
        self.llm = IrisLangchainChatModel(
            request_handler=request_handler, completion_args=completion_args
        )
        self.pipeline = self.llm | StrOutputParser()

    def __call__(self) -> bool:
        try:
            self.callback.in_progress("Deleting old slides from database...")
            self.delete_old_lectures()
            self.callback.done("Old slides removed")
            #Here we check if the operation is for updating or for deleting,
            # we only check the first file because all the files will have the same operation
            if not self.dto.lecture_units[0].to_update:
                self.callback.skip("Lecture Chunking and interpretation Skipped")
                self.callback.skip("No new slides to update")
                return True
            self.callback.in_progress("Chunking and interpreting lecture...")
            chunks = []
            for i, lecture_unit in enumerate(self.dto.lecture_units):
                pdf_path = save_pdf(lecture_unit.pdf_file_base64)
                chunks = self.chunk_data(
                    lecture_pdf=pdf_path, lecture_unit_dto=lecture_unit
                )
                cleanup_temporary_file(pdf_path)
            self.callback.done("Lecture Chunking and interpretation Finished")
            self.callback.in_progress("Ingesting lecture chunks into database...")
            self.batch_update(chunks)
            self.callback.done("Lecture Ingestion Finished")
            return True
        except Exception as e:
            logger.error(f"Error updating lecture unit: {e}")
            self.callback.error(f"Failed to ingest lectures into the database: {e}")
            return False

    def batch_update(self, chunks):
        """
        Batch update the chunks into the database
        This method is thread-safe and can only be executed by one thread at a time.
        Weaviate limitation.
        """
        global batch_update_lock
        with batch_update_lock:
            with self.collection.batch.rate_limit(requests_per_minute=600) as batch:
                try:
                    for index, chunk in enumerate(chunks):
                        embed_chunk = self.llm_embedding.embed(
                            chunk[LectureSchema.PAGE_TEXT_CONTENT.value]
                        )
                        batch.add_object(properties=chunk, vector=embed_chunk)
                except Exception as e:
                    logger.error(f"Error updating lecture unit: {e}")
                    self.callback.error(
                        f"Failed to ingest lectures into the database: {e}"
                    )

    def chunk_data(
        self,
        lecture_pdf: str,
        lecture_unit_dto: LectureUnitDTO = None,
    ):
        """
        Chunk the data from the lecture into smaller pieces
        """
        doc = fitz.open(lecture_pdf)
        course_language = self.get_course_language(
            doc.load_page(min(5, doc.page_count - 1)).get_text()
        )
        data = []
        last_page_content = ""
        for page_num in range(doc.page_count):
            page = doc.load_page(page_num)
            page_content = page.get_text()
            img_base64 = ""
            if page.get_images(full=True):
                page_snapshot = page.get_pixmap()
                img_bytes = page_snapshot.tobytes("png")
                img_base64 = base64.b64encode(img_bytes).decode("utf-8")
                image_interpretation = self.interpret_image(
                    img_base64,
                    last_page_content,
                    lecture_unit_dto.lecture_name,
                )
                page_content = self.merge_page_content_and_image_interpretation(
                    page_content, image_interpretation
                )
            page_data: PageData = {
                LectureSchema.LECTURE_ID.value: lecture_unit_dto.lecture_id,
                LectureSchema.LECTURE_NAME.value: lecture_unit_dto.lecture_name,
                LectureSchema.LECTURE_UNIT_ID.value: lecture_unit_dto.lecture_unit_id,
                LectureSchema.LECTURE_UNIT_NAME.value: lecture_unit_dto.lecture_unit_name,
                LectureSchema.COURSE_ID.value: lecture_unit_dto.course_id,
                LectureSchema.COURSE_NAME.value: lecture_unit_dto.course_name,
                LectureSchema.COURSE_DESCRIPTION.value: lecture_unit_dto.course_description,
                LectureSchema.COURSE_LANGUAGE.value: course_language,
                LectureSchema.PAGE_NUMBER.value: page_num + 1,
                LectureSchema.PAGE_TEXT_CONTENT.value: page_content,
                LectureSchema.PAGE_BASE64.value: img_base64,
            }
            last_page_content = page_content
            data.append(page_data)
        return data

    def interpret_image(
        self,
        img_base64: str,
        last_page_content: str,
        name_of_lecture: str,
    ):
        """
        Interpret the image passed
        """
        image_interpretation_prompt = TextMessageContentDTO(
            text_content=f"This page is part of the {name_of_lecture} lecture, describe and explain it in no more "
            f"than 300 tokens, respond only with the explanation nothing more, "
            f"Here is the content of the previous slide,"
            f" it's content is most likely related to the slide you need to interpret: \n"
            f" {last_page_content}"
            f"Intepret the image below based on the provided context and the content of the previous slide.\n"
        )
        image = ImageMessageContentDTO(base64=img_base64)
        iris_message = PyrisMessage(
            sender=IrisMessageRole.SYSTEM, contents=[image_interpretation_prompt, image]
        )
        try:
            response = self.llm_vision.chat(
                [iris_message], CompletionArguments(temperature=0.2, max_tokens=500)
            )
        except Exception as e:
            logger.error(f"Error interpreting image: {e}")
            return None
        return response.contents[0].text_content

    def merge_page_content_and_image_interpretation(
        self, page_content: str, image_interpretation: str
    ):
        """
        Merge the text and image together
        """
        dirname = os.path.dirname(__file__)
        prompt_file_path = os.path.join(
            dirname, ".", "prompts", "lecture_ingestion_prompt.txt"
        )
        with open(prompt_file_path, "r") as file:
            logger.info("Loading ingestion prompt...")
            lecture_ingestion_prompt = file.read()
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", lecture_ingestion_prompt),
            ]
        )
        prompt_val = prompt.format_messages(
            page_content=page_content,
            image_interpretation=image_interpretation,
        )
        prompt = ChatPromptTemplate.from_messages(prompt_val)
        return (prompt | self.pipeline).invoke({})

    def get_course_language(self, page_content: str) -> str:
        """
        Translate the student query to the course language. For better retrieval.
        """
        prompt = (
            f"You will be provided a chunk of text, respond with the language of the text. Do not respond with "
            f"anything else than the language.\nHere is the text: \n{page_content}"
        )
        iris_message = PyrisMessage(
            sender=IrisMessageRole.SYSTEM,
            contents=[TextMessageContentDTO(text_content=prompt)],
        )
        response = self.llm_chat.chat(
            [iris_message], CompletionArguments(temperature=0, max_tokens=20)
        )
        return response.contents[0].text_content

    def delete_old_lectures(self):
        """
        Delete the lecture unit from the database
        """
        try:
            for lecture_unit in self.dto.lecture_units:
                if self.delete_lecture_unit(
                    lecture_unit.lecture_id, lecture_unit.lecture_unit_id
                ):
                    logger.info("Lecture deleted successfully")
                else:
                    logger.error("Failed to delete lecture")
        except Exception as e:
            logger.error(f"Error deleting lecture unit: {e}")
            return False

    def delete_lecture_unit(self, lecture_id, lecture_unit_id):
        """
        Delete the lecture from the database
        """
        try:
            self.collection.data.delete_many(
                where=Filter.by_property(LectureSchema.LECTURE_ID.value).equal(
                    lecture_id
                )
                & Filter.by_property(LectureSchema.LECTURE_UNIT_ID.value).equal(
                    lecture_unit_id
                )
            )
            return True
        except Exception as e:
            print(f"Error deleting lecture unit: {e}")
            return False
