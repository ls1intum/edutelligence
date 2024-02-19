from abc import ABC, abstractmethod

from domain import IrisMessage
from pipeline import Pipeline


class ProgrammingExerciseTutorChatPipeline(Pipeline, ABC):
    """
    Abstract class for the programming exercise tutor chat pipeline implementations.
    This class defines the signature of all implementations of this Iris feature.
    """

    def __call__(self, query: IrisMessage, **kwargs) -> IrisMessage:
        return self._run(query)

    @abstractmethod
    def _run(self, query: IrisMessage) -> IrisMessage:
        """
        Runs the pipeline and returns the response message.
        """
        raise NotImplementedError
