
from module_modeling_llm.helios_renderer.models.diagram import UMLDiagram
from module_modeling_llm.helios_renderer.models.bounds import Bounds
from module_modeling_llm.helios_renderer.utils.constants import (PADDING_LEFT, PADDING_RIGHT, PADDING_TOP, PADDING_BOTTOM, MARKER_SIZE)

def compute_diagram_bounds(diagram: UMLDiagram):
    """
    Compute the minimal bounding box that contains all elements and relationships in the diagram.

    Args:
        diagram (UMLDiagram): The diagram data structure.

    Returns:
        tuple: (min_x, min_y, width, height) representing the overall diagram bounds.
    """
    
    elements = diagram['elements'].values()
    relationships = diagram['relationships'].values()
    
    min_x, min_y, max_x, max_y = float('inf'), float('inf'), float('-inf'), float('-inf')
    
    for elem in elements:
        b = elem['bounds']
        min_x = min(min_x, b['x'])
        min_y = min(min_y, b['y'])
        max_x = max(max_x, b['x'] + b['width'])
        max_y = max(max_y, b['y'] + b['height'])

    for rel in relationships:
        for p in rel['path']:
            min_x = min(min_x, p['x'] - MARKER_SIZE)
            min_y = min(min_y, p['y'] - MARKER_SIZE)
            max_x = max(max_x, p['x'] + MARKER_SIZE)
            max_y = max(max_y, p['y'] + MARKER_SIZE)

    if min_x == float('inf'):
        min_x, min_y, max_x, max_y = 0,0,0,0

    width = (max_x - min_x) + PADDING_LEFT + PADDING_RIGHT
    height = (max_y - min_y) + PADDING_TOP + PADDING_BOTTOM
    return (min_x - PADDING_LEFT, min_y - PADDING_TOP, width, height)