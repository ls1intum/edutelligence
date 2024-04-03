import base64
from typing import Dict
import fitz
import weaviate
from ...vector_database.lectureschema import init_lecture_schema, LectureSchema
from .abstract_ingestion import AbstractIngestion
from ...llm import BasicRequestHandler

image_interpretation_prompt = f'This page is part of a {lecture_name} lecture,' \
                              f' describe and explain it in no more than 500 tokens, respond only with the explanation nothing more,' \
                              f' here is a description of the lecture: {lecture_description}' \
                              f' Here is the content of the page before the one you need to interpret: {previous_page_content}'



def interpret_image(llm, img_base64, page_content, name_of_lecture, description_of_lecture):
    """ Interpret the image using the langchain model """
    pass


class LectureIngestion(AbstractIngestion):  # Inherits from the abstract class

    def __init__(self, client: weaviate.WeaviateClient):
        self.collection = init_lecture_schema(client)

    def chunk_data(self,
                   lecture_path: str,
                   llm: BasicRequestHandler,
                   name_of_lecture: str = None,
                   description_of_lecture: str = None):
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
                image_interpretation = interpret_image(llm,
                                                       img_base64,
                                                       page_content,
                                                       name_of_lecture,
                                                       description_of_lecture
                                                       )
                page_content = page.get_text()
                data.append(
                    {
                        LectureSchema.PAGE_TEXT_CONTENT: page_content,
                        LectureSchema.PAGE_IMAGE_DESCRIPTION: image_interpretation,
                        LectureSchema.PAGE_NUMBER: page_num + 1,
                        LectureSchema.LECTURE_NAME: lecture_path,
                        LectureSchema.PAGE_BASE64: img_base64,
                    }
                )

            else:
                page_content = page.get_text()
                data.append(
                    {
                        LectureSchema.PAGE_TEXT_CONTENT: page_content,
                        LectureSchema.PAGE_IMAGE_DESCRIPTION: "",
                        LectureSchema.PAGE_NUMBER: page_num + 1,
                        LectureSchema.LECTURE_NAME: lecture_path,
                        LectureSchema.PAGE_BASE64: "",
                    }
                )
        return data

    def ingest(
            self,
            lecture_path,
            image_llm: BasicRequestHandler = None,
            embedding_model: BasicRequestHandler = None,
    ) -> bool:
        """
        Ingest the repositories into the weaviate database
        """
        chunks = self.chunk_data(lecture_path)  # , image_llm)
        with self.collection.batch.dynamic() as batch:
            for index, chunk in enumerate(chunks):
                # embed the
                embed_chunk = embedding_model.embed(
                    chunk[LectureSchema.PAGE_TEXT_CONTENT]
                    + "\n"
                    + chunk[LectureSchema.PAGE_IMAGE_DESCRIPTION]
                )
                batch.add_object(properties=chunk, vector=embed_chunk)
        return True

    def update(self, lecture: Dict[str, str]):
        """
        Update a lecture in the weaviate database
        """
        # Implement update logic here or raise NotImplementedError if not applicable
        pass
