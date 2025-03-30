"""
Defines the interface for all prompt templates used in the code generation pipeline.
Ensures a consistent format and behavior for prompts across the system.
"""

from abc import ABC, abstractmethod

class PromptInterface(ABC):
    """
    Abstract base class defining the interface for all prompt templates.
    """
    
    @abstractmethod
    def format(self, **kwargs):
        """
        Format the prompt template with the provided variables.
        
        Args:
            **kwargs: Variables to be inserted into the prompt template
            
        Returns:
            str: The formatted prompt ready to be sent to the model
        """
        pass 
