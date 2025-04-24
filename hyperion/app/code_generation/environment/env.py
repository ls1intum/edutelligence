from abc import ABC, abstractmethod

class Env(ABC):
    def __init__(self, env_file_path: str):
        self.env_file_path = env_file_path
        
    @abstractmethod
    def store(self, text: str) -> None:
        """
        Write text to the environment file, overwriting any existing content.
        
        Args:
            text: The text content to write to the file
        """
        pass
            
    @abstractmethod
    def get(self) -> str:
        """
        Read and return the contents of the environment file.
        
        Returns:
            The content of the environment file as a string
        """
        pass
            
    @abstractmethod
    def append(self, text: str) -> None:
        """
        Append text to the existing content of the environment file.
        
        Args:
            text: The text to append to the file
        """
        pass
            
    @abstractmethod
    def remove(self) -> None:
        """
        Remove the environment file if it exists.
        """
        pass
            
    @abstractmethod
    def run(self, command: str) -> str:
        """
        Execute a command in the environment.
        
        Args:
            command: The command to execute
            
        Returns:
            The output of the command execution
        """
        pass
