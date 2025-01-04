from typing import Dict, List, Tuple
import xml.etree.ElementTree as ET
from module_modeling_llm.helius_render.services.path_service import compute_relationship_path
from module_modeling_llm.helius_render.models.element import Element
from module_modeling_llm.helius_render.models.relationship import Relationship
from module_modeling_llm.helius_render.models.config_types import RelationshipConfig
from module_modeling_llm.helius_render.utils.template_manager import TemplateManager

class RelationshipRenderer:
    """
    Renders UML relationships into SVG <path> elements
    """
    def __init__(self, relationship_config: RelationshipConfig, template_manager: TemplateManager) -> None:
        self.rel_config = relationship_config
        self.template_manager = template_manager

    def render_relationship(self, rel: Relationship, svg: ET.Element, elements_by_id: Dict[str, Element]) -> None:
        """
        Render a UML relationship as an SVG path.   
        Args:
            rel (Relationship): The relationship data.
            svg (ET.Element): The SVG parent element to append the path to.
            elements_by_id (Dict[str, Element]): Map of element IDs to element objects. 
        Raises:
            ValueError: If source or target elements are missing.
        """
        source_element = elements_by_id.get(rel['source']['element'])
        target_element = elements_by_id.get(rel['target']['element'])

        if not source_element or not target_element:
            raise ValueError(f"Invalid relationship {rel['id']}, missing source or target.")

        # Compute the path for the relationship
        rel['path'] = compute_relationship_path(source_element, target_element, rel)

        # Compute a true midpoint along the entire polyline
        mid_x, mid_y = self._compute_midpoint_along_path(rel['path'])

        template = self.template_manager.get_template('relationship_path.svg.jinja')
        svg_content = template.render(
            rel=rel,
            path_d=self._create_path_string(rel['path']),
            mid_x=mid_x,
            mid_y=mid_y
        )
        element = ET.fromstring(svg_content)
        svg.append(element)

    def _create_path_string(self, points: List[Dict[str, float]]) -> str:
        if not points:
            return ""
        path = f"M {points[0]['x']} {points[0]['y']}"
        for p in points[1:]:
            path += f" L {p['x']} {p['y']}"
        return path

    def _compute_midpoint_along_path(self, path_points: List[Dict[str, float]]) -> Tuple[float, float]:
        if not path_points:
            return (0,0)

        # Compute total length of the polyline and store segments
        total_length = 0.0
        segments = []
        for i in range(len(path_points)-1):
            p1 = path_points[i]
            p2 = path_points[i+1]
            dx = p2['x'] - p1['x']
            dy = p2['y'] - p1['y']
            seg_length = (dx**2 + dy**2)**0.5
            segments.append((p1, p2, seg_length))
            total_length += seg_length

        # Target distance is half of total length
        half_length = total_length / 2.0

        # Walk along segments until we find the segment containing the midpoint
        distance_covered = 0.0
        for (start, end, seg_length) in segments:
            if distance_covered + seg_length == half_length:
                # Midpoint lies exactly at the end of this segment
                return (end['x'], end['y'])
            elif distance_covered + seg_length > half_length:
                # Midpoint lies within this segment
                remaining = half_length - distance_covered
                ratio = remaining / seg_length
                mid_x = start['x'] + ratio * (end['x'] - start['x'])
                mid_y = start['y'] + ratio * (end['y'] - start['y'])
                return (mid_x, mid_y)
            distance_covered += seg_length

        # Fallback: if something went wrong, return last point
        return (path_points[-1]['x'], path_points[-1]['y'])
