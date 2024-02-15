from abc import ABCMeta, abstractmethod

from domain import IrisMessage


class AbstractPipeline(metaclass=ABCMeta):
    """Abstract class for all pipelines"""

    name: str

    def __init__(self, name=None):
        self.name = name

    def __call__(self, **kwargs):
        return self._run(**kwargs)

    @abstractmethod
    def _run(self, **kwargs) -> IrisMessage:
        """
        Runs the pipeline and is intended to be called by __call__
        :param kwargs: keyword arguments
        :return: IrisMessage
        """
        raise NotImplementedError
