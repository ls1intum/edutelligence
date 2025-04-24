from typing import TYPE_CHECKING
from ..step_execution import GenerationStep

if TYPE_CHECKING:
    from ...context import Context

class EvaluateTerminalOutput(GenerationStep):
    def process(self, context: 'Context') -> 'Context':
        self.logger.info("2.2) Evaluate terminal output")
            
        return context