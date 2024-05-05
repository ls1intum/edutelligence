import base64
import os
import tempfile
from asyncio.log import logger
import fitz
import weaviate
import weaviate.classes as wvc
from . import Pipeline
from ..domain import IrisMessageRole, PyrisMessage
from ..domain.data.image_message_content_dto import ImageMessageContentDTO
from ..domain.data.lecture_unit_dto import LectureUnitDTO
from app.domain.ingestion.ingestion_pipeline_execution_dto import (
    IngestionPipelineExecutionDto,
)
from ..vector_database.lecture_schema import init_lecture_schema, LectureSchema
from ..content_service.Ingestion.abstract_ingestion import AbstractIngestion
from ..llm import BasicRequestHandler, CompletionArguments
from ..web.status import IngestionStatusCallback


def cleanup_temporary_file(file_path):
    """
    Cleanup the temporary file
    """
    # Delete the temporary file
    os.remove(file_path)


def save_pdf(pdf_file_base64):
    """
    Save the pdf file to a temporary file
    """
    binary_data = base64.b64decode(pdf_file_base64)
    fd, temp_pdf_file_path = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    with open(temp_pdf_file_path, "wb") as temp_pdf_file:
        temp_pdf_file.write(binary_data)
    return temp_pdf_file_path


class LectureIngestionPipeline(AbstractIngestion, Pipeline):

    def __init__(
        self,
        client: weaviate.WeaviateClient,
        dto: IngestionPipelineExecutionDto,
        callback: IngestionStatusCallback,
    ):
        super().__init__()
        self.collection = init_lecture_schema(client)
        self.dto = dto
        self.llm_vision = BasicRequestHandler("gptvision")
        self.llm = BasicRequestHandler("gpt35")
        self.llm_embedding = BasicRequestHandler("ada")
        self.callback = callback

    def __call__(self) -> bool:
        try:
            self.callback.in_progress("Deleting old slides from database...")
            self.delete_old_lectures()
            self.callback.done("Old slides removed")
            if not self.dto.lecture_units[0].to_update:
                self.callback.skip("Lecture Chunking and interpretation Skipped")
                self.callback.skip("No new slides to update")
                return True
            self.callback.in_progress("Chunking and interpreting lecture...")
            chunks = []
            for i, lecture_unit in enumerate(self.dto.lecture_units):
                pdf_path = save_pdf(lecture_unit.pdf_file_base64)
                chunks = self.chunk_data(
                    lecture_path=pdf_path, lecture_unit_dto=lecture_unit
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
        """
        with self.collection.batch.dynamic() as batch:
            self.callback.in_progress("Ingesting lecture chunks into databse")
            for index, chunk in enumerate(chunks):
                embed_chunk = self.llm_embedding.embed(
                    chunk[LectureSchema.PAGE_TEXT_CONTENT.value]
                    + "\n"
                    + chunk[LectureSchema.PAGE_IMAGE_DESCRIPTION.value]
                )
                batch.add_object(properties=chunk, vector=embed_chunk)

    def delete_old_lectures(self):
        """
        Delete the lecture unit from the database
        """
        try:
            for lecture_unit in self.dto.lecture_units:
                self.delete_lecture_unit(
                    lecture_unit.lecture_id, lecture_unit.lecture_unit_id
                )
        except Exception as e:
            logger.error(f"Error deleting lecture unit: {e}")
            return False

    def chunk_data(
        self,
        lecture_path: str,
        lecture_unit_dto: LectureUnitDTO = None,
    ):
        """
        Chunk the data from the lecture into smaller pieces
        """
        doc = fitz.open(lecture_path)
        data = []
        page_content = ""
        for page_num in range(doc.page_count):
            page = doc.load_page(page_num)
            if page.get_images(full=True):
                pix = page.get_pixmap()
                img_bytes = pix.tobytes("png")
                img_base64 = base64.b64encode(img_bytes).decode("utf-8")
                image_interpretation = self.interpret_image(
                    img_base64,
                    page_content,
                    lecture_unit_dto.lecture_name,
                )
                page_content = page.get_text()
                data.append(
                    {
                        LectureSchema.LECTURE_ID.value: lecture_unit_dto.lecture_id,
                        LectureSchema.LECTURE_NAME.value: lecture_unit_dto.lecture_name,
                        LectureSchema.LECTURE_UNIT_ID.value: lecture_unit_dto.lecture_unit_id,
                        LectureSchema.LECTURE_UNIT_NAME.value: lecture_unit_dto.lecture_unit_name,
                        LectureSchema.COURSE_ID.value: lecture_unit_dto.course_id,
                        LectureSchema.COURSE_NAME.value: lecture_unit_dto.course_name,
                        LectureSchema.COURSE_DESCRIPTION.value: lecture_unit_dto.course_description,
                        LectureSchema.PAGE_NUMBER.value: page_num + 1,
                        LectureSchema.PAGE_TEXT_CONTENT.value: page_content,
                        LectureSchema.PAGE_IMAGE_DESCRIPTION.value: image_interpretation,
                        LectureSchema.PAGE_BASE64.value: img_base64,
                    }
                )

            else:
                page_content = page.get_text()
                data.append(
                    {
                        LectureSchema.LECTURE_ID.value: lecture_unit_dto.lecture_id,
                        LectureSchema.LECTURE_NAME.value: lecture_unit_dto.lecture_name,
                        LectureSchema.LECTURE_UNIT_ID.value: lecture_unit_dto.lecture_unit_id,
                        LectureSchema.LECTURE_UNIT_NAME.value: lecture_unit_dto.lecture_unit_name,
                        LectureSchema.COURSE_ID.value: lecture_unit_dto.course_id,
                        LectureSchema.COURSE_NAME.value: lecture_unit_dto.course_name,
                        LectureSchema.COURSE_DESCRIPTION.value: lecture_unit_dto.course_description,
                        LectureSchema.PAGE_NUMBER.value: page_num + 1,
                        LectureSchema.PAGE_TEXT_CONTENT.value: page_content,
                        LectureSchema.PAGE_IMAGE_DESCRIPTION.value: "",
                        LectureSchema.PAGE_BASE64.value: "",
                    }
                )
        return data

    def delete_lecture_unit(self, lecture_id, lecture_unit_id):
        """
        Delete the lecture from the database
        """
        try:
            self.collection.data.delete_many(
                where=wvc.query.Filter.by_property(LectureSchema.LECTURE_ID.value).equal(
                    lecture_id
                )
                & wvc.query.Filter.by_property(LectureSchema.LECTURE_UNIT_ID.value).equal(
                    lecture_unit_id
                )
            )
            return True
        except Exception as e:
            print(f"Error deleting lecture unit: {e}")
            return False

    def interpret_image(
        self, img_base64: str, last_page_content: str, name_of_lecture: str
    ):
        """
        Interpret the image passed
        """
        image_interpretation_prompt = (
            f"This page is part of the {name_of_lecture} lecture, describe and explain it in no more"
            f" than 500 tokens, respond only with the explanation nothing more, "
            f"Here is the content of the page before the one you need to interpret: "
            f" {last_page_content}"
        )
        image = ImageMessageContentDTO(
            base64=[img_base64], prompt=image_interpretation_prompt
        )
        iris_message = PyrisMessage(sender=IrisMessageRole.SYSTEM, contents=[image])
        response = self.llm_vision.chat(
            [iris_message], CompletionArguments(temperature=0.2, max_tokens=1000)
        )
        return response.contents[0].text_content
