from typing import Sequence, List

from langchain.chains.qa_with_sources.retrieval import RetrievalQAWithSourcesChain
from langchain_community.document_loaders import AsyncChromiumLoader
from langchain_community.document_transformers import BeautifulSoupTransformer
from duckduckgo_search import DDGS
import re

from langchain_community.retrievers import WebResearchRetriever
from langchain_community.utilities import GoogleSearchAPIWrapper
from langchain_community.vectorstores import Chroma
from langchain_core.documents import Document
from langchain_core.tools import Tool
from langchain_openai import OpenAIEmbeddings

from module_programming_llm.helpers.models import ModelConfigType


def bulk_search(queries: Sequence[str], model: ModelConfigType) -> List[str]:
    result = []
    for query in queries:
        result.append(answer_query(query, model))
    return result
#
#
# def search(query: str) -> List[str]:
#     results = DDGS().text(query, max_results=5)
#     urls = []
#     for result in results:
#         url = result['href']
#         urls.append(url)
#
#     docs = get_page(urls)
#
#     content = []
#     for doc in docs:
#         page_text = re.sub("\n\n+", "\n", doc.page_content)
#         text = truncate(page_text)
#         content.append(text)
#
#     return content
#
#
# def get_page(urls: List[str]) -> Sequence[Document]:
#     loader = AsyncChromiumLoader(urls, headless=True)
#     html = loader.load()
#
#     bs_transformer = BeautifulSoupTransformer()
#     docs_transformed = bs_transformer.transform_documents(html, tags_to_extract=["p"], remove_unwanted_tags=["a"])
#
#     return docs_transformed
#
#
# def truncate(text) -> str:
#     words = text.split()
#     truncated = " ".join(words[:1000])
#
#     return truncated

def answer_query(query, model: ModelConfigType):
    model = model.get_model()  # type: ignore[attr-defined]
    vectorstore = Chroma(
        embedding_function=OpenAIEmbeddings(), persist_directory="./chroma_db_oai"
    )

    # Search
    search = GoogleSearchAPIWrapper()

    # # Initialize
    web_search_retriever = WebResearchRetriever.from_llm(
        vectorstore=vectorstore, llm=model, search=search, allow_dangerous_requests=True
    )
    qa_chain = RetrievalQAWithSourcesChain.from_chain_type(
        model, retriever=web_search_retriever
    )
    result = qa_chain({"question": query})

    search = GoogleSearchAPIWrapper()

    tool = Tool(
        name="google_search",
        description="Search Google for recent results.",
        func=search.run,
    )

    return tool.run(query)
