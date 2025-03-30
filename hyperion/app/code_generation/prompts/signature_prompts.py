"""
Signature generation prompt templates.
Contains prompts for creating class and function signatures.
"""

from .base_prompt import BasePrompt

class SignatureGenerationPrompt(BasePrompt):

    def __init__(self):
        template = """
        
        """
        # TODO
        super().__init__(template) 
