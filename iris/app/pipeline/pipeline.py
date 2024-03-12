from abc import ABCMeta


class Pipeline(metaclass=ABCMeta):
    """Abstract class for all pipelines"""

    implementation_id: str

    def __init__(self, implementation_id=None, **kwargs):
        self.implementation_id = implementation_id

    def __str__(self):
        return f"{self.__class__.__name__}"

    def __repr__(self):
        return f"{self.__class__.__name__}"

    def __call__(self, **kwargs):
        """
        Extracts the required parameters from the kwargs runs the pipeline.
        """
        raise NotImplementedError("Subclasses must implement the __call__ method.")

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if "__call__" not in cls.__dict__:
            raise NotImplementedError(
                "Subclasses of Pipeline interface must implement the __call__ method."
            )
