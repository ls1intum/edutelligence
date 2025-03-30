"""
Logging utility for the code generation pipeline.
Provides consistent logging functionality across all components,
capturing the process flow and results for analysis.
"""

import logging
import os
from datetime import datetime

class Logger:
    
    def __init__(self, log_dir=None, level=logging.INFO):
        """
        Initialize the logger with a log directory and level.
        
        Args:
            log_dir (str, optional): Directory to store log files
            level (int): Logging level
        """
        self.logger = logging.getLogger('code_generation')
        self.logger.setLevel(level)
        
        if self.logger.handlers:
            self.logger.handlers.clear()
        
        console_handler = logging.StreamHandler()
        console_handler.setLevel(level)
        console_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        console_handler.setFormatter(console_formatter)
        self.logger.addHandler(console_handler)
        
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            log_file = os.path.join(log_dir, f"code_generation_{timestamp}.log")
            
            file_handler = logging.FileHandler(log_file)
            file_handler.setLevel(level)
            file_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            file_handler.setFormatter(file_formatter)
            self.logger.addHandler(file_handler)
    
    def info(self, message):
        self.logger.info(message)
    
    def debug(self, message):
        self.logger.debug(message)
    
    def warning(self, message):
        self.logger.warning(message)
    
    def error(self, message):
        self.logger.error(message)
    
    def critical(self, message):
        self.logger.critical(message)
        
    def log_component(self, component_name, input_data, output_data):
        """
        Log component execution with input and output data.
        
        Args:
            component_name (str): Name of the component
            input_data: Component input
            output_data: Component output
        """
        self.info(f"Component: {component_name} - Processing started")
        self.debug(f"Component: {component_name} - Input: {input_data}")
        self.debug(f"Component: {component_name} - Output: {output_data}")
        self.info(f"Component: {component_name} - Processing completed") 
