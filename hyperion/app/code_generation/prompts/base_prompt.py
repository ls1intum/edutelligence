"""
Base implementation for prompt templates.
Provides common functionality for all prompts in the system,
including variable substitution and formatting.
"""

from .prompt_interface import PromptInterface

class BasePrompt(PromptInterface):
    """
    Base class for all prompt templates, implementing shared functionality.
    """
    
    def __init__(self, template):
        """
        Initialize the prompt with a template string.
        
        Args:
            template (str): The prompt template with placeholders
        """
        self.template = template
        
    def format(self, **kwargs):
        """
        Format the prompt template with the provided variables.
        
        Args:
            **kwargs: Variables to be inserted into the prompt template
            
        Returns:
            str: The formatted prompt
        """
        return self.template.format(**kwargs) 
