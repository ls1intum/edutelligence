from abc import abstractmethod

from common import SingletonABCMeta


class Pipeline(metaclass=SingletonABCMeta):
    """Abstract class for all pipelines"""

    _is_abstract = True
    implementation_id: str

    def __init__(self, implementation_id=None):
        self.implementation_id = implementation_id

    def __str__(self):
        return f"{self.__class__.__name__}"

    def __repr__(self):
        return f"{self.__class__.__name__}"

    @abstractmethod
    def __call__(self, **kwargs):
        """
        Extracts the required parameters from the kwargs runs the pipeline.
        """
        raise NotImplementedError("Subclasses must implement the __call__ method.")
