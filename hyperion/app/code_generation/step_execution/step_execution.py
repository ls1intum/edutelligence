from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..code_generator import CodeGenerator
    from ..context import Context

class GenerationStep(ABC):
    def __init__(self, generator: 'CodeGenerator'):
        self.generator = generator
        self.model = generator.model
        self.logger = generator.logger
        self.env = generator.env
    
    def execute(self, context: 'Context') -> 'Context':
        """Template method defining the execution flow of each step"""
        self.logger.info(f"Starting step: {self.__class__.__name__}")
        result = self.process(context)
        self.logger.info(f"Completed step: {self.__class__.__name__}")
        return result
    
    @abstractmethod
    def process(self, context: 'Context') -> 'Context':
        """Abstract method to be implemented by concrete steps"""
        pass
    