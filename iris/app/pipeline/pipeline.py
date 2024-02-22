from abc import abstractmethod, ABCMeta


class Pipeline(metaclass=ABCMeta):
    """Abstract class for all pipelines"""

    implementation_id: str

    def __init__(self, implementation_id=None, **kwargs):
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

    @classmethod
    def __subclasshook__(cls, subclass) -> bool:
        # Check if the subclass implements the __call__ method and checks if the subclass is callable
        return hasattr(subclass, "__call__") and callable(subclass.__call__)
