import base64
import os
import re
import tempfile
import threading
from typing import Optional

import fitz
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_text_splitters import RecursiveCharacterTextSplitter
from weaviate import WeaviateClient
from weaviate.classes.query import Filter

from iris.common.logging_config import get_logger
from iris.common.pipeline_enum import PipelineEnum
from iris.domain.ingestion.ingestion_pipeline_execution_dto import (
    IngestionPipelineExecutionDto,
)
from iris.domain.variant.variant import Variant

from ..common.pyris_message import IrisMessageRole, PyrisMessage
from ..domain.data.image_message_content_dto import ImageMessageContentDTO
from ..domain.data.lecture_unit_page_dto import LectureUnitPageDTO
from ..domain.data.text_message_content_dto import TextMessageContentDTO
from ..ingestion.abstract_ingestion import AbstractIngestion
from ..llm import (
    CompletionArguments,
    LlmRequestHandler,
)
from ..llm.langchain import IrisLangchainChatModel
from ..tracing import observe
from ..vector_database.lecture_unit_page_chunk_schema import (
    LectureUnitPageChunkSchema,
    init_lecture_unit_page_chunk_schema,
)
from ..web.status import ingestion_status_callback
from . import Pipeline

logger = get_logger(__name__)

batch_update_lock = threading.Lock()


_UNICODE_BULLETS = (
    "\u0095"  # BULLET (legacy Windows-1252)
    "\u2022"  # BULLET
    "\u2023"  # TRIANGULAR BULLET
    "\u2043"  # HYPHEN BULLET
    "\u3164"  # HANGUL FILLER
    "\u204c"  # BLACK LEFTWARDS BULLET
    "\u204d"  # BLACK RIGHTWARDS BULLET
    "\u2219"  # BULLET OPERATOR
    "\u25cb"  # WHITE CIRCLE
    "\u25cf"  # BLACK CIRCLE
    "\u25d8"  # INVERSE BULLET
    "\u25e6"  # WHITE BULLET
    "\u2619"  # REVERSED ROTATED FLORAL HEART BULLET
    "\u2765"  # ROTATED HEAVY BLACK HEART BULLET
    "\u2767"  # ROTATED FLORAL HEART BULLET
    "\u29be"  # CIRCLED WHITE BULLET
    "\u29bf"  # CIRCLED BULLET
    "\u002d"  # HYPHEN-MINUS
    "\u2013"  # EN DASH
    "\u00b7"  # MIDDLE DOT
    "\u2024"  # ONE DOT LEADER
    "\u002a"  # ASTERISK
)
_BULLET_PATTERN = re.compile(
    rf"^[^\S\n]*[{re.escape(_UNICODE_BULLETS)}][^\S\n]*",
    flags=re.MULTILINE,
)


def clean_text(
    text: str, *, bullets: bool = False, extra_whitespace: bool = False
) -> str:
    """Lightweight replacement for unstructured.cleaners.core.clean.

    Bullets are stripped first so the multiline-anchored regex can match
    line-leading bullets before newlines are collapsed by whitespace cleanup.
    """
    if bullets:
        text = _BULLET_PATTERN.sub("", text)
    if extra_whitespace:
        text = re.sub(r"\s+", " ", text).strip()
    return text


def cleanup_temporary_file(file_path):
    """
    Cleanup the temporary file
    """
    try:
        os.remove(file_path)
    except OSError as e:
        logger.error("Failed to remove temporary file %s: %s", file_path, e)


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
                "Failed to write to temporary PDF file %s: %s",
                temp_pdf_file_path,
                e,
            )
            raise
    return temp_pdf_file_path


def create_page_data(
    page_num, page_splits, lecture_unit_dto, course_language, base_url
):
    """
    Create and return a list of dictionnaries to be ingested in the Vector Database.
    """
    return [
        {
            LectureUnitPageChunkSchema.LECTURE_ID.value: lecture_unit_dto.lecture_id,
            LectureUnitPageChunkSchema.LECTURE_UNIT_ID.value: lecture_unit_dto.lecture_unit_id,
            LectureUnitPageChunkSchema.COURSE_ID.value: lecture_unit_dto.course_id,
            LectureUnitPageChunkSchema.COURSE_LANGUAGE.value: course_language,
            LectureUnitPageChunkSchema.PAGE_NUMBER.value: page_num + 1,
            LectureUnitPageChunkSchema.PAGE_TEXT_CONTENT.value: page_split.page_content,
            LectureUnitPageChunkSchema.BASE_URL.value: base_url,
            LectureUnitPageChunkSchema.PAGE_VERSION.value: lecture_unit_dto.attachment_version,
        }
        for page_split in page_splits
    ]


class LectureUnitPageIngestionPipeline(AbstractIngestion, Pipeline):
    """LectureUnitPageIngestionPipeline ingests lecture unit pages into the database by chunking lecture PDFs,
    processing the content, and updating the vector database."""

    PIPELINE_ID = "lecture_unit_page_ingestion_pipeline"
    ROLES = {"chat", "embedding"}
    VARIANT_DEFS = [
        (
            "default",
            "Default",
            "Default lecture ingestion variant using efficient models "
            "for text processing and embeddings.",
        ),
        (
            "advanced",
            "Advanced",
            "Advanced lecture ingestion variant using higher-quality models for improved accuracy.",
        ),
    ]

    def __init__(
        self,
        client: WeaviateClient,
        dto: Optional[IngestionPipelineExecutionDto],
        callback: ingestion_status_callback,
        variant: Variant,
        local: bool = False,
    ):
        super().__init__(implementation_id=self.PIPELINE_ID)
        self.collection = init_lecture_unit_page_chunk_schema(client)
        self.dto = dto
        self.callback = callback
        chat_model = variant.model("chat", local)
        embedding_model = variant.model("embedding", local)
        self.llm_chat = LlmRequestHandler(chat_model)
        self.llm_embedding = LlmRequestHandler(embedding_model)
        request_handler = LlmRequestHandler(chat_model)
        completion_args = CompletionArguments(temperature=0.2, max_tokens=2000)
        self.llm = IrisLangchainChatModel(
            request_handler=request_handler, completion_args=completion_args
        )
        self.pipeline = self.llm | StrOutputParser()
        self.tokens = []
        self.course_language = None

    @observe(name="Lecture Unit Page Ingestion Pipeline")
    def __call__(self) -> (str, []):
        try:
            if not self.check_if_attachment_needs_update():
                pdf_path = save_pdf(self.dto.lecture_unit.pdf_file_base64)
                doc = fitz.open(pdf_path)
                self.course_language = self.get_course_language(
                    doc.load_page(min(5, doc.page_count - 1)).get_text()
                )
                self.callback.in_progress("skipping slide removal")
                self.callback.done()
                self.callback.in_progress("skipping slide interpretation")
                self.callback.done()
                self.callback.in_progress("skipping slide ingestion")
                self.callback.done()
                return self.course_language, self.tokens
            self.callback.in_progress("Deleting old slides from database...")
            self.delete_lecture_unit(
                self.dto.lecture_unit.course_id,
                self.dto.lecture_unit.lecture_id,
                self.dto.lecture_unit.lecture_unit_id,
                self.dto.settings.artemis_base_url,
            )
            self.callback.done("Old slides removed")
            self.callback.in_progress("Chunking and interpreting lecture...")
            chunks = []
            pdf_path = save_pdf(self.dto.lecture_unit.pdf_file_base64)
            chunks.extend(
                self.chunk_data(
                    lecture_pdf=pdf_path,
                    lecture_unit_slide_dto=self.dto.lecture_unit,
                    base_url=self.dto.settings.artemis_base_url,
                )
            )
            cleanup_temporary_file(pdf_path)
            self.callback.done("Lecture Chunking and interpretation Finished")
            self.callback.in_progress("Ingesting lecture chunks into database...")
            logger.info(
                "[%s] Embedding and indexing %d chunks into Weaviate",
                self.dto.lecture_unit.lecture_unit_name,
                len(chunks),
            )
            self.batch_update(chunks)

            self.callback.done("Lecture Ingestion Finished", tokens=self.tokens)

            logger.info(
                "Lecture ingestion pipeline finished Successfully for course %s",
                self.dto.lecture_unit.course_name,
            )
            return self.course_language, self.tokens
        except Exception as e:
            logger.error("Error updating lecture unit", exc_info=e)
            self.callback.error(
                f"Failed to ingest lectures into the database: {e}",
                exception=e,
                tokens=self.tokens,
            )
            return "", []

    def check_if_attachment_needs_update(self) -> bool:
        page_chunk_filter = Filter.by_property(
            LectureUnitPageChunkSchema.BASE_URL.value
        ).equal(self.dto.settings.artemis_base_url)
        page_chunk_filter &= Filter.by_property(
            LectureUnitPageChunkSchema.COURSE_ID.value
        ).equal(self.dto.lecture_unit.course_id)
        page_chunk_filter &= Filter.by_property(
            LectureUnitPageChunkSchema.LECTURE_ID.value
        ).equal(self.dto.lecture_unit.lecture_id)
        page_chunk_filter &= Filter.by_property(
            LectureUnitPageChunkSchema.LECTURE_UNIT_ID.value
        ).equal(self.dto.lecture_unit.lecture_unit_id)

        page_chunk = self.collection.query.fetch_objects(
            filters=page_chunk_filter, limit=1
        ).objects

        if len(page_chunk) == 0:
            return True
        version = page_chunk[0].properties.get(
            LectureUnitPageChunkSchema.PAGE_VERSION.value
        )

        return version < self.dto.lecture_unit.attachment_version

    def batch_update(self, chunks):
        """
        Batch update the chunks into the database
        This method is thread-safe and can only be executed by one thread at a time.
        Weaviate limitation.
        """
        total = len(chunks)
        with batch_update_lock:
            with self.collection.batch.rate_limit(requests_per_minute=600) as batch:
                try:
                    for i, chunk in enumerate(chunks):
                        if i % 10 == 0:
                            self.callback.in_progress(
                                f"Ingesting lecture chunk {i + 1}/{total} into database..."
                            )
                        embed_chunk = self.llm_embedding.embed(
                            chunk[LectureUnitPageChunkSchema.PAGE_TEXT_CONTENT.value]
                        )
                        batch.add_object(properties=chunk, vector=embed_chunk)
                except Exception as e:
                    logger.error("Error updating lecture unit", exc_info=e)
                    self.callback.error(
                        f"Failed to ingest lectures into the database: {e}",
                        exception=e,
                        tokens=self.tokens,
                    )

    def chunk_data(
        self,
        lecture_pdf: str,
        lecture_unit_slide_dto: LectureUnitPageDTO = None,
        base_url: str = None,
    ):  # pylint: disable=arguments-renamed
        """
        Chunk the data from the lecture into smaller pieces
        """
        doc = fitz.open(lecture_pdf)
        self.course_language = self.get_course_language(
            doc.load_page(min(5, doc.page_count - 1)).get_text()
        )
        data = []
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=512, chunk_overlap=102
        )
        prefix = f"[{lecture_unit_slide_dto.lecture_name} / {lecture_unit_slide_dto.lecture_unit_name}]"
        logger.info("%s Starting PDF chunking: %d pages", prefix, doc.page_count)
        old_page_text = ""
        for page_num in range(doc.page_count):
            self.callback.in_progress(
                f"Chunking and interpreting lecture page {page_num + 1}/{doc.page_count}"
            )
            page = doc.load_page(page_num)
            page_text = page.get_text()
            if page.get_images(full=False):
                logger.info(
                    "%s Page %d/%d: has images, interpreting with LLM",
                    prefix,
                    page_num + 1,
                    doc.page_count,
                )
                # more pixels thus more details and better quality
                matrix = fitz.Matrix(5, 5)
                pix = page.get_pixmap(matrix=matrix)
                img_bytes = pix.tobytes("jpg")
                img_base64 = base64.b64encode(img_bytes).decode("utf-8")
                image_interpretation = self.interpret_image(
                    img_base64,
                    old_page_text,
                    lecture_unit_slide_dto.lecture_name,
                    self.course_language,
                )
                page_text = self.merge_page_content_and_image_interpretation(
                    page_text, image_interpretation
                )
            page_splits = text_splitter.create_documents([page_text])
            data.extend(
                create_page_data(
                    page_num,
                    page_splits,
                    lecture_unit_slide_dto,
                    self.course_language,
                    base_url,
                )
            )
            old_page_text = page_text
        logger.info(
            "%s PDF chunking complete: %d chunks from %d pages",
            prefix,
            len(data),
            doc.page_count,
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
            text_content=f"This page is part of the {name_of_lecture} university lecture."
            f"I am the professor that created these slides, "
            f" please interpret this slide in an academic way. "
            f"For more context here is the content of the previous slide:\n "
            f" {last_page_content} \n\n"
            f" Only repond with the slide explanation and interpretation in {course_language}, "
            f"do not add anything else to your response.Your explanation should not exceed 350 words."
        )
        image = ImageMessageContentDTO(base64=img_base64)
        iris_message = PyrisMessage(
            sender=IrisMessageRole.USER,
            contents=[image_interpretation_prompt, image],
        )
        try:
            response = self.llm_chat.chat(
                [iris_message],
                CompletionArguments(temperature=0),
                tools=[],
            )
            self._append_tokens(
                response.token_usage, PipelineEnum.IRIS_LECTURE_INGESTION
            )
        except Exception as e:
            logger.error("Error interpreting image: %s", e)
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
            dirname,
            ".",
            "prompts",
            "content_image_interpretation_merge_prompt.txt",
        )
        with open(prompt_file_path, "r", encoding="utf-8") as file:
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
        clean_output = clean_text(
            (prompt | self.pipeline).invoke({}),
            bullets=True,
            extra_whitespace=True,
        )
        self._append_tokens(self.llm.tokens, PipelineEnum.IRIS_LECTURE_INGESTION)
        return clean_output

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
            [iris_message],
            CompletionArguments(temperature=0),
            tools=[],
        )
        self._append_tokens(response.token_usage, PipelineEnum.IRIS_LECTURE_INGESTION)
        return response.contents[0].text_content

    def delete_old_lectures(
        self,
        lecture_units_slides: list[LectureUnitPageDTO],
        artemis_base_url: str,
    ):
        """
        Delete the lecture unit from the database
        """
        try:
            for lecture_unit in lecture_units_slides:
                if self.delete_lecture_unit(
                    lecture_unit.course_id,
                    lecture_unit.lecture_id,
                    lecture_unit.lecture_unit_id,
                    artemis_base_url,
                ):
                    logger.info("Lecture deleted successfully")
                else:
                    logger.error("Failed to delete lecture")
            self.callback.done("Old slides removed")
        except Exception as e:
            logger.error("Error deleting lecture unit: %s", e)
            self.callback.error("Error while removing old slides")
            return False

    def delete_lecture_unit(self, course_id, lecture_id, lecture_unit_id, base_url):
        """
        Delete the lecture from the database
        """
        try:
            self.collection.data.delete_many(
                where=Filter.by_property(
                    LectureUnitPageChunkSchema.BASE_URL.value
                ).equal(base_url)
                & Filter.by_property(LectureUnitPageChunkSchema.COURSE_ID.value).equal(
                    course_id
                )
                & Filter.by_property(LectureUnitPageChunkSchema.LECTURE_ID.value).equal(
                    lecture_id
                )
                & Filter.by_property(
                    LectureUnitPageChunkSchema.LECTURE_UNIT_ID.value
                ).equal(lecture_unit_id)
            )
            return True
        except Exception as e:
            logger.error("Error deleting lecture unit: %s", e, exc_info=True)
            return False
