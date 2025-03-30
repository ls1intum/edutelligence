from app.models import get_model
from .component_interface import ComponentInterface

class BaseComponent(ComponentInterface):
    """
    Base class for all code generation components, implementing shared functionality.
    """
    
    def __init__(self, prompt_template=None):
        """
        Initialize the component with a model and optional prompt template.
        
        Args:
            prompt_template: The prompt template to use for this component
        """
        self.model = get_model()
        self.prompt_template = prompt_template
        
    def process(self, input_data, context=None):
        """
        Default implementation of the process method.
        
        Args:
            input_data: The data to be processed
            context (dict, optional): Additional context information
            
        Returns:
            The processed output
        """
        return input_data 
