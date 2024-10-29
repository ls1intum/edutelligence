from typing import Sequence, List

from langchain.chains.qa_with_sources.retrieval import RetrievalQAWithSourcesChain

from langchain_community.retrievers import WebResearchRetriever
from langchain_community.utilities import GoogleSearchAPIWrapper
from langchain_community.vectorstores import Chroma
from langchain_core.tools import Tool
from langchain_openai import OpenAIEmbeddings

from llm_core.models import ModelConfigType


def bulk_search(queries: Sequence[str], model: ModelConfigType) -> List[str]:
    result = []
    for query in queries:
        result.append(answer_query(query, model))
    return result


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
