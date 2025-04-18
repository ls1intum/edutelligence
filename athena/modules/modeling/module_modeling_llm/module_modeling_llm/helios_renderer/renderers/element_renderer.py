from typing import Dict
import xml.etree.ElementTree as ET

from jinja2 import Template
from module_modeling_llm.helios_renderer.models.bounds import Bounds
from module_modeling_llm.helios_renderer.models.config_types import ElementConfig, ElementConfigEntry
from module_modeling_llm.helios_renderer.models.element import Element
from module_modeling_llm.helios_renderer.utils.template_manager import TemplateManager

class ElementRenderer:
    """
    Renders UML elements (like classes) into an SVG <g> element using a Jinja2 template.
    """
     
    def __init__(self, element_config: ElementConfig, template_manager: TemplateManager):
        self.element_config = element_config
        self.template_manager = template_manager

    def render(self, element: Element, svg: ET.Element) -> None:
        """
        Render a single UML element into the given SVG root.

        Args:
            element (Element): The UML element to render.
            svg (ET.Element): The SVG root element to append to.
            elements_by_id (Dict[str, Element]): All elements keyed by ID (not always needed here).
        """
        
        elem_type = element.get('type', 'default')
        config: ElementConfigEntry = self.element_config.get(elem_type, self.element_config['default'])
        bounds = Bounds(**element['bounds'])

        template: Template = self.template_manager.get_template('element.svg.jinja')
        svg_content: str = template.render(
            element=element,
            bounds=bounds,
            element_shape=config['shape'],
            element_class=config['class_name'],
            element_text_class=config['text_class']
        )
        group: ET.Element = ET.fromstring(svg_content)
        svg.append(group)