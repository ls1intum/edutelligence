from abc import ABC, abstractmethod

class ComponentInterface(ABC):

    @abstractmethod
    def process(self, input_data, context=None):
        """
        Process the input data and return the result.
        
        Args:
            input_data: The data to be processed by this component
            context (dict, optional): Additional context information that might be needed
            
        Returns:
            The processed output of this component
        """
        pass 
