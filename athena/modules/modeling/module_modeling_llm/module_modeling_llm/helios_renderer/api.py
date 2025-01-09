import json
from typing import Dict, Optional, cast
from module_modeling_llm.helios_renderer.models.diagram import UMLDiagram
from module_modeling_llm.helios_renderer.utils.config_loader import load_all_configs
from module_modeling_llm.helios_renderer.renderers.uml_renderer import UMLRenderer
from module_modeling_llm.helios_renderer.utils.css_loader import load_css

# Global initialization
# Load configs and css once
_CONFIGS = load_all_configs()
_CSS = load_css()
_RENDERER = UMLRenderer(_CONFIGS, _CSS)

def render_diagram(json_data: str, name_map: Optional[Dict[str, str]] = None) -> bytes:

    # Parse diagram
    diagram_data = json.loads(json_data)
    diagram = cast(UMLDiagram, diagram_data)

    if name_map:
        for elem in diagram['elements'].values():
            elem_id = elem['id']
            if elem_id in name_map:
                elem['name'] = name_map[elem_id]

        for rel in diagram['relationships'].values():
            rel_id = rel['id']
            if rel_id in name_map:
                rel['name'] = name_map[rel_id]

    # Render using the pre-initialized renderer
    png_data = _RENDERER.render_to_bytes(diagram)

    return png_data