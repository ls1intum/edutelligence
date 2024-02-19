import json
import os
import time

import fitz  # PyMuPDF
import openai
import weaviate
from unstructured.cleaners.core import clean
import weaviate.classes as wvc

from data.lecture.lecture_schema import init_schema, COLLECTION_NAME, LectureSlideChunk


def chunk_files(subdirectory_path, subdirectory):
    data = []
    # Process each PDF file in this subdirectory
    for filename in os.listdir(subdirectory_path):
        if not filename.endswith(".pdf"):
            continue
        file_path = os.path.join(subdirectory_path, filename)
        # Open the PDF
        with fitz.open(file_path) as doc:
            for page_num in range(len(doc)):
                page_text = doc[page_num].get_text()
                page_text = clean(page_text, bullets=True, extra_whitespace=True)
                data.append(
                    {
                        LectureSlideChunk.PAGE_CONTENT: page_text,
                        LectureSlideChunk.COURSE_ID: "",
                        LectureSlideChunk.LECTURE_ID: "",
                        LectureSlideChunk.LECTURE_NAME: "",
                        LectureSlideChunk.LECTURE_UNIT_ID: "",
                        LectureSlideChunk.LECTURE_UNIT_NAME: "",
                        LectureSlideChunk.FILENAME: file_path,
                        LectureSlideChunk.PAGE_NUMBER: "",
                    }
                )
    return data


class Lectures:

    def __init__(self, client: weaviate.WeaviateClient):
        self.collection = init_schema(client)

    def ingest(self, lectures):
        pass

    def search(self, query, k=3, filter=None):
        pass

    def batch_import(self, directory_path, subdirectory):
        data = chunk_files(directory_path, subdirectory)
        with self.collection.batch.dynamic() as batch:
            for i, properties in enumerate(data):
                embeddings_created = False
                for j in range(5):  # max 5 retries
                    if not embeddings_created:
                        try:
                            batch.add_data_object(properties, COLLECTION_NAME)
                            embeddings_created = True  # Set flag to True on success
                            break  # Break the loop as embedding creation was successful
                        except openai.error.RateLimitError:
                            time.sleep(2**j)  # wait 2^j seconds before retrying
                            print("Retrying import...")
                    else:
                        break  # Exit loop if embeddings already created
                # Raise an error if embeddings were not created after retries
                if not embeddings_created:
                    raise RuntimeError("Failed to create embeddings.")

    def retrieve(self, user_message: str, lecture_id: int = None):
        response = self.collection.query.near_text(
            near_text=user_message,
            filters=(
                wvc.query.Filter.by_property(LectureSlideChunk.LECTURE_ID).equal(
                    lecture_id
                )
                if lecture_id
                else None
            ),
            return_properties=[
                LectureSlideChunk.PAGE_CONTENT,
                LectureSlideChunk.COURSE_NAME,
            ],
            limit=5,
        )
        print(json.dumps(response, indent=2))
        return response
