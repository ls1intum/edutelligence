import os
import subprocess
from app.code_generation.environment.env import Env

class PythonEnv(Env):
    
    def store(self, text: str) -> None:
        with open(self.env_file_path, 'w') as file:
            file.write(text)
            
    def get(self) -> str:
        try:
            with open(self.env_file_path, 'r') as file:
                return file.read()
        except FileNotFoundError:
            raise FileNotFoundError(f"Environment file not found: {self.env_file_path}")
            
    def append(self, text: str) -> None:
        with open(self.env_file_path, 'a') as file:
            file.write(text)
            
    def remove(self) -> None:
        if os.path.exists(self.env_file_path):
            os.remove(self.env_file_path)
            
    def run(self, command: str) -> str:
        try:
            result = subprocess.run(
                ["python3", "-c", command],
                capture_output=True,
                text=True,
                check=True
            )
            return result.stdout
        except subprocess.CalledProcessError as e:
            error_msg = f"Command execution error: {e.stderr}"
            self.append(f"\n# {error_msg}")
            raise Exception(error_msg)
        except Exception as e:
            error_msg = f"Error during command execution: {str(e)}"
            self.append(f"\n# {error_msg}")
            raise Exception(error_msg)
