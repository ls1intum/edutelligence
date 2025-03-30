"""
Output evaluation prompt templates.
Contains prompts for analyzing execution results and code quality.
"""

from .base_prompt import BasePrompt

class OutputEvaluationPrompt(BasePrompt):

    def __init__(self):
        template = """
        
        """
        # TODO
        super().__init__(template) 
