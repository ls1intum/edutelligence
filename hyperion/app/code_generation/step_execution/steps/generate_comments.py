from abc import ABC, abstractmethod
from typing import Dict, Any, TYPE_CHECKING
from ..step_execution import GenerationStep

if TYPE_CHECKING:
    from ...context import Context

class GenerateComments(GenerationStep):
    def process(self, context: 'Context') -> 'Context':
        self.logger.info("1.2) Generate comments")
            
        return context