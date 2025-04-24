from abc import ABC, abstractmethod
from typing import Dict, Any, TYPE_CHECKING
from ..step_execution import GenerationStep

if TYPE_CHECKING:
    from ...context import Context

class GenerateCoreLogic(GenerationStep):
    def process(self, context: 'Context') -> 'Context':
        self.logger.info("1.3) Generate core logic")
            
        return context