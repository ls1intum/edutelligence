from app.llm import BasicRequestHandler
from app.llm.external.cohere_client import CohereAzureClient
from app.pipeline import Pipeline
import cohere


class CohereRerankerPipeline(Pipeline):
    def __init__(self):
        super().__init__(implementation_id="cohere_reranker_pipeline")
        self.cohere_client = BasicRequestHandler("cohere")

    def __call__(self, query: str, documents: [], top_n: int, content_field_name: str):
        print("reranker running...")
        mapped_responses = list(map(lambda x: x.properties[content_field_name], documents))

        _, reranked_results, _ = self.cohere_client.rerank(query=query,
                                                    documents=mapped_responses,
                                                    top_n=5,
                                                    model='rerank-multilingual-v3.5')
        ranked_documents = []
        for result in reranked_results[1]:
            ranked_documents.append(documents[result.index])
        return ranked_documents