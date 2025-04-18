import os
from jinja2 import Environment, FileSystemLoader

class TemplateManager:
    def __init__(self):
        template_path = os.path.join(os.path.dirname(__file__), '..', 'templates')
        self.env = Environment(loader=FileSystemLoader(template_path))
        
    def get_template(self, name: str):
        return self.env.get_template(name)

template_manager = TemplateManager()  # Singleton-like usage
