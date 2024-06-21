import base64
import os
import tempfile
import threading
from asyncio.log import logger
import fitz
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from unstructured.cleaners.core import clean
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
from langchain_text_splitters import RecursiveCharacterTextSplitter

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
            logger.error(
                f"Failed to write to temporary PDF file {temp_pdf_file_path}: {e}"
            )
            raise
    return temp_pdf_file_path


def create_page_data(page_num, page_splits, lecture_unit_dto, course_language, base_url):
    """
    Create and return a list of dictionnaries to be ingested in the Vector Database.
    """
    return [
        {
            LectureSchema.LECTURE_ID.value: lecture_unit_dto.lecture_id,
            LectureSchema.LECTURE_NAME.value: lecture_unit_dto.lecture_name,
            LectureSchema.LECTURE_UNIT_ID.value: lecture_unit_dto.lecture_unit_id,
            LectureSchema.LECTURE_UNIT_NAME.value: lecture_unit_dto.lecture_unit_name,
            LectureSchema.COURSE_ID.value: lecture_unit_dto.course_id,
            LectureSchema.COURSE_NAME.value: lecture_unit_dto.course_name,
            LectureSchema.COURSE_DESCRIPTION.value: lecture_unit_dto.course_description,
            LectureSchema.BASE_URL.value: base_url,
            LectureSchema.COURSE_LANGUAGE.value: course_language,
            LectureSchema.PAGE_NUMBER.value: page_num + 1,
            LectureSchema.PAGE_TEXT_CONTENT.value: page_split.page_content,
        }
        for page_split in page_splits
    ]


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
        self.llm_chat = BasicRequestHandler(
            "azure-gpt-35-turbo"
        )  # TODO change use langain model
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
            # Here we check if the operation is for updating or for deleting,
            # we only check the first file because all the files will have the same operation
            if not self.dto.lecture_units[0].to_update:
                self.callback.skip("Lecture Chunking and interpretation Skipped")
                self.callback.skip("No new slides to update")
                return True
            self.callback.in_progress("Chunking and interpreting lecture...")
            chunks = []
            for i, lecture_unit in enumerate(self.dto.lecture_units):
                pdf_path = save_pdf(lecture_unit.pdf_file_base64)
                chunks.extend(
                    self.chunk_data(lecture_pdf=pdf_path,
                                    lecture_unit_dto=lecture_unit,
                                    base_url=self.dto.settings.artemis_base_url)
                )
                cleanup_temporary_file(pdf_path)
            self.callback.done("Lecture Chunking and interpretation Finished")
            self.callback.in_progress("Ingesting lecture chunks into database...")
            self.batch_update(chunks)
            self.callback.done("Lecture Ingestion Finished")
            logger.info(
                f"Lecture ingestion pipeline finished Successfully for course "
                f"{self.dto.lecture_units[0].course_name}"
            )
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
        base_url: str = None,
    ):
        """
        Chunk the data from the lecture into smaller pieces
        """
        doc = fitz.open(lecture_pdf)
        course_language = self.get_course_language(
            doc.load_page(min(5, doc.page_count - 1)).get_text()
        )
        data = []
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=512, chunk_overlap=102
        )
        for page_num in range(doc.page_count):
            page = doc.load_page(page_num)
            page_text = page.get_text()
            if page.get_images(full=False):
                # more pixels thus more details and better quality
                matrix = fitz.Matrix(20.0, 20.0)
                pix = page.get_pixmap(matrix=matrix)
                img_bytes = pix.tobytes("jpg")
                img_base64 = base64.b64encode(img_bytes).decode("utf-8")
                image_interpretation = self.interpret_image(
                    img_base64,
                    page_text,
                    lecture_unit_dto.lecture_name,
                    course_language,
                )
                page_text = self.merge_page_content_and_image_interpretation(
                    page_text, image_interpretation
                )
            page_splits = text_splitter.create_documents([page_text])
            data.extend(
                create_page_data(
                    page_num, page_splits, lecture_unit_dto, course_language, base_url
                )
            )
        return data

    def interpret_image(
        self,
        img_base64: str,
        last_page_content: str,
        name_of_lecture: str,
        course_language: str,
    ):
        """
        Interpret the image passed
        """
        image_interpretation_prompt = TextMessageContentDTO(
            text_content=f"This page is part of the {name_of_lecture} university lecture,"
            f" explain what is on the slide in an academic way,"
            f" respond only with the explanation in {course_language}."
            f" For more context here is the content of the previous slide: "
            f" {last_page_content}"
        )
        image = ImageMessageContentDTO(base64=img_base64)
        iris_message = PyrisMessage(
            sender=IrisMessageRole.USER, contents=[image_interpretation_prompt, image]
        )
        try:
            response = self.llm_vision.chat(
                [iris_message], CompletionArguments(temperature=0, max_tokens=400)
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
            dirname, ".", "prompts", "content_image_interpretation_merge_prompt.txt"
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
        return clean(
            (prompt | self.pipeline).invoke({}), bullets=True, extra_whitespace=True
        )

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
                    lecture_unit.course_id,
                    lecture_unit.lecture_id,
                    lecture_unit.lecture_unit_id,
                    self.dto.settings.artemis_base_url
                ):
                    logger.info("Lecture deleted successfully")
                else:
                    logger.error("Failed to delete lecture")
        except Exception as e:
            logger.error(f"Error deleting lecture unit: {e}")
            return False

    def delete_lecture_unit(self, course_id, lecture_id, lecture_unit_id, base_url):
        """
        Delete the lecture from the database
        """
        try:
            self.collection.data.delete_many(
                where=Filter.by_property(LectureSchema.BASE_URL.value).equal(base_url)
                & Filter.by_property(LectureSchema.COURSE_ID.value).equal(course_id)
                & Filter.by_property(LectureSchema.LECTURE_ID.value).equal(lecture_id)
                & Filter.by_property(LectureSchema.LECTURE_UNIT_ID.value).equal(
                    lecture_unit_id
                )
            )
            return True
        except Exception as e:
            logger.error(f"Error deleting lecture unit: {e}", exc_info=True)
            return False
