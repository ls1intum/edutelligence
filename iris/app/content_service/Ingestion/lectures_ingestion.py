import base64
from typing import Dict
import fitz
import weaviate
from app.vector_database.lectureschema import init_lecture_schema, LectureSchema
from ..Ingestion.abstract_ingestion import AbstractIngestion
from app.llm import BasicRequestHandler


class LectureIngestion(AbstractIngestion):  # Inherits from the abstract class

    def __init__(self, client: weaviate.WeaviateClient):
        self.collection = init_lecture_schema(client)

    def chunk_data(self, lecture_path: str):
        doc = fitz.open(lecture_path)  # Explicitly annotate as an Iterable of fitz.Page
        data = []
        for page_num in range(doc.page_count):
            page = doc.load_page(page_num)
            # Check if the page has images
            if page.get_images(full=True):
                # Render the page to an image (pixmap)
                pix = page.get_pixmap()
                # Convert the pixmap to bytes
                img_bytes = pix.tobytes("png")
                # Encode the bytes to Base64 and then decode to a string
                img_base64 = base64.b64encode(img_bytes).decode("utf-8")
                page_content = page.get_text()
                data.append(
                    {
                        LectureSchema.PAGE_TEXT_CONTENT: page_content,
                        LectureSchema.PAGE_IMAGE_DESCRIPTION: "",  # image_interpretation,
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

    def ingest(self, lecture_path, embedding_model: BasicRequestHandler = None) -> bool:
        """
        Ingest the repositories into the weaviate database
        """
        chunks = self.chunk_data(lecture_path)
        with self.collection.batch.dynamic() as batch:
            for index, chunk in enumerate(chunks):
                # embed the
                embed_chunk = embedding_model.embed(
                    chunk[1][LectureSchema.PAGE_TEXT_CONTENT]
                    + "\n"
                    + chunk[1][LectureSchema.PAGE_IMAGE_DESCRIPTION]
                )
                batch.add_object(properties=chunk, vector=embed_chunk)
        return True

    def update(self, lecture: Dict[str, str]):
        """
        Update a lecture in the weaviate database
        """
        # Implement update logic here or raise NotImplementedError if not applicable
        pass
