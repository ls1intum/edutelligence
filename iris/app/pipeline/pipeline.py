from abc import ABCMeta, abstractmethod
from operator import itemgetter

from langchain_core.output_parsers import StrOutputParser
from domain import IrisMessage, IrisMessageRole


class AbstractPipeline(metaclass=ABCMeta):
    """Abstract class for all pipelines"""

    def __init__(self, name=None):
        self.name = name

    def __repr__(self):
        return f"{self.__class__.__name__} {self.name if self.name is not None else id(self)}"

    def __str__(self):
        return f"{self.__class__.__name__} {self.name if self.name is not None else id(self)}"

    @abstractmethod
    def run(self, *args, **kwargs) -> IrisMessage:
        """Runs the pipeline"""
        raise NotImplementedError


class SimplePipeline(AbstractPipeline):
    """A simple pipeline that does not have any memory etc."""

    def __init__(self, llm, name=None):
        super().__init__(name=name)
        self.llm = llm
        self.pipeline = {"query": itemgetter("query")} | llm | StrOutputParser()

    def run(self, *args, query: IrisMessage, **kwargs) -> IrisMessage:
        if query is None:
            raise ValueError("IrisMessage must not be None")
        message = query.text
        response = self.pipeline.invoke({"query": message})
        return IrisMessage(role=IrisMessageRole.ASSISTANT, text=response)
