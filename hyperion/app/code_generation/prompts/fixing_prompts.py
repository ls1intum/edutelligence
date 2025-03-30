"""
Code fixing prompt templates.
Contains prompts for correcting errors in generated code.
"""

from .base_prompt import BasePrompt

class CodeFixingPrompt(BasePrompt):

    def __init__(self):
        template = """
        
        """
        # TODO
        super().__init__(template) 
