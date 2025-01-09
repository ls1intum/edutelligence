import os
import json
from typing import Dict
from module_modeling_llm.helios_renderer.models.config_types import AllConfigs, ElementConfigEntry, RelationshipConfigEntry, MarkerConfigEntry

def load_config(filename: str):
    base_dir = os.path.dirname(os.path.dirname(__file__))
    config_path = os.path.join(base_dir, 'config', filename)
    with open(config_path, 'r', encoding='utf-8') as file:
        return json.load(file)

def load_all_configs() -> AllConfigs:
    elements = load_config('diagram_elements.json')
    relationships = load_config('diagram_relationships.json')
    markers = load_config('markers.json')

    # Cast the loaded data to typed dictionaries
    elements_typed: Dict[str, ElementConfigEntry] = elements
    relationships_typed: Dict[str, RelationshipConfigEntry] = relationships
    markers_typed: Dict[str, MarkerConfigEntry] = markers

    return {
        'elements': elements_typed,
        'relationships': relationships_typed,
        'markers': markers_typed
    }
