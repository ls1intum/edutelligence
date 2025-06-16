import os.path
from typing import Optional

from jinja2 import Template


def create_template(template_str: Optional[str], file_path: str) -> Template:
    if template_str is None:
        # Get the directory of the current file (util)
        current_dir = os.path.dirname(os.path.abspath(__file__))
        # Get the root directory of the module (memiris)
        module_dir = os.path.dirname(current_dir)
        # Construct the absolute path to the template file
        template_path = os.path.join(module_dir, "default_templates", file_path)

        # Load the default template from the file
        with open(template_path, "r", encoding="utf-8") as file:
            template_content = file.read()
        return Template(template_content)
    else:
        # Load the template from the provided string
        return Template(template_str)
