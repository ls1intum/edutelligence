from abc import ABCMeta


class Pipeline(metaclass=ABCMeta):
    """Abstract class for all pipelines"""

    implementation_id: str

    def __init__(self, implementation_id=None):
        self.implementation_id = implementation_id

    def __call__(self, **kwargs):
        """
        Extracts the required parameters from the kwargs runs the pipeline.
        """
        raise NotImplementedError

