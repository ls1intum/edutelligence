from typing import Optional

from jinja2 import Template


def create_template(template_str: Optional[str], file_path: str) -> Template:
    if template_str is None:
        # Load the default template from the file located at memiris.default_templates
        with open(f"./default_templates/{file_path}", "r", encoding="utf-8") as file:
            template_content = file.read()
        return Template(template_content)
    else:
        # Load the template from the provided string
        return Template(template_str)
