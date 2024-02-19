from abc import abstractmethod, ABCMeta

from domain import IrisMessage
from pipeline import Pipeline


class ChatPipeline(Pipeline, metaclass=ABCMeta):
    """
    Abstract class for the programming exercise tutor chat pipeline implementations.
    This class defines the signature of all implementations of this Iris feature.
    """

    @abstractmethod
    def __call__(self, query: IrisMessage, **kwargs) -> IrisMessage:
        """
        Runs the pipeline and returns the response message.
        """
        raise NotImplementedError
