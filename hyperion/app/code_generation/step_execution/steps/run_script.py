from typing import TYPE_CHECKING
from ..step_execution import GenerationStep

if TYPE_CHECKING:
    from ...context import Context

class RunScript(GenerationStep):
    def process(self, context: 'Context') -> 'Context':
        self.logger.info("2.1) Run script")
        # Implementation for running the generated script using the environment
        try:
            command = f"TODO"
            output = self.env.run(command=command)
            context.terminal_output = output
        except Exception as e:
            context.terminal_output = str(e)
            context.execution_successful = False
        return context