import cairosvg
import xml.etree.ElementTree as ET
from typing import Tuple, List

from PIL import Image, ImageDraw, ImageFont

from module_modeling_llm.helius_render.models.config_types import AllConfigs
from module_modeling_llm.helius_render.models.diagram import UMLDiagram
from module_modeling_llm.helius_render.services.diagram_service import compute_diagram_bounds
from module_modeling_llm.helius_render.renderers.element_renderer import ElementRenderer
from module_modeling_llm.helius_render.renderers.relationship_renderer import RelationshipRenderer
from module_modeling_llm.helius_render.utils.template_manager import template_manager
from module_modeling_llm.helius_render.utils.constants import DEFAULT_DPI


class UMLRenderer:
    def __init__(self, configs: AllConfigs, css: str):
        self.configs = configs
        self.markers_config = configs['markers']
        self.element_config = configs['elements']
        self.relationship_config = configs['relationships']
        self.css = css
        # Always default to PIL's built-in font
        self.name_font = ImageFont.load_default()
        self.type_font = ImageFont.load_default()
        self.rel_font = ImageFont.load_default()

    def render_to_bytes(self, diagram_data: UMLDiagram) -> bytes:
        self.diagram = diagram_data
        self.elements_by_id = self.diagram['elements']
        self.relationships = self.diagram['relationships']

        # 1. Determine scale factor
        scale_factor = self._determine_scale_factor()

        # 2. Apply scale if needed
        if scale_factor > 1.0:
            self._scale_diagram(scale_factor)

        # 3. Finalize layout (shift diagram to (0,0))
        self._finalize_layout()

        # 4. Wrap text now that final sizes are known and store in elements
        self._wrap_all_element_texts()

        # 5. Create SVG and render elements and relationships
        svg = self._create_svg()

        elem_renderer = ElementRenderer(self.element_config, template_manager)
        for element in self.elements_by_id.values():
            if element['type'] not in ['ClassAttribute', 'ClassMethod']:
                elem_renderer.render(element, svg)

        rel_renderer = RelationshipRenderer(self.relationship_config, template_manager)
        for rel in self.relationships.values():
            rel_renderer.render_relationship(rel, svg, self.elements_by_id)

        # 6. Convert SVG to PNG
        svg_str = ET.tostring(svg, encoding='unicode')
        png_data = cairosvg.svg2png(bytestring=svg_str.encode('utf-8'), dpi=DEFAULT_DPI)
        if png_data is None:
            raise ValueError("Failed to convert SVG to PNG.")

        return png_data

    def _determine_scale_factor(self) -> float:
        """
        Try to fit text by wrapping first, then scale only if necessary.
        Returns scale factor (1.0 if no scaling needed).
        """
        max_scale = 1.0

        # First pass: Attempt text wrapping for all elements
        for elem in self.elements_by_id.values():
            elem_w = elem['bounds']['width']
            elem_h = elem['bounds']['height']
            name_text = elem.get('name', '')
            type_text = elem.get('type', '')

            # Try to fit text by wrapping
            name_lines, name_w, name_h = self._wrap_text_until_fit(
                name_text, self.name_font, elem_w, elem_h)
            type_lines, type_w, type_h = [], 0, 0
            vertical_gap = 0
            
            if type_text:
                type_lines, type_w, type_h = self._wrap_text_until_fit(
                    type_text, self.type_font, elem_w, elem_h - name_h if name_h > 0 else elem_h)
                if name_h > 0 and type_h > 0:
                    vertical_gap = 20

            total_h = name_h + type_h + vertical_gap
            total_w = max(name_w, type_w)

            # Store wrapped lines for later use
            elem['_wrapped_name_lines'] = name_lines
            elem['_wrapped_type_lines'] = type_lines

            # Only scale if wrapping couldn't make it fit
            if total_w > elem_w or total_h > elem_h:
                scale_w = (total_w / elem_w) if total_w > elem_w else 1.0
                scale_h = (total_h / elem_h) if total_h > elem_h else 1.0
                required_scale = max(scale_w, scale_h)
                if required_scale > max_scale:
                    max_scale = required_scale

        # Handle relationships (these can't be wrapped, only scaled)
        for rel in self.relationships.values():
            rel_name = rel.get('name', '')
            if rel_name:
                box_w, box_h = 40, 20
                rw, rh = self._text_bbox(rel_name, self.rel_font)
                scale_w = (rw / box_w) if rw > box_w else 1.0
                scale_h = (rh / box_h) if rh > box_h else 1.0
                required_scale = max(scale_w, scale_h)
                if required_scale > max_scale:
                    max_scale = required_scale

        return max_scale

    def _wrap_text_until_fit(self, text: str, font: ImageFont.ImageFont, 
                            max_width: float, max_height: float) -> Tuple[List[str], float, float]:
        """
        Iteratively wrap text until it fits within bounds or each word is on its own line.
        Returns (wrapped_lines, total_width, total_height).
        """
        if not text:
            return [], 0, 0

        words = text.split()
        if not words:
            return [], 0, 0

        # Try initial wrapping at max width
        lines = self.wrap_text_to_width(text, font, max_width)
        max_line_w, total_h = self._measure_wrapped_text(lines, font)

        # If it fits, we're done
        if max_line_w <= max_width and total_h <= max_height:
            return lines, max_line_w, total_h

        # If the text is still too wide or tall, keep wrapping more aggressively
        current_width = max_width
        while current_width >= 10:  # Don't try impossibly narrow widths
            current_width *= 0.8  # Try progressively narrower widths
            lines = self.wrap_text_to_width(text, font, current_width)
            max_line_w, total_h = self._measure_wrapped_text(lines, font)
            
            if max_line_w <= max_width and total_h <= max_height:
                return lines, max_line_w, total_h

        # If we still can't fit, put each word on its own line
        lines = words
        max_line_w, total_h = self._measure_wrapped_text(lines, font)
        return lines, max_line_w, total_h

    def _measure_wrapped_text(self, lines: List[str], font: ImageFont.ImageFont) -> Tuple[float, float]:
        """
        Measure the maximum width and total height of wrapped text lines.
        Returns (max_width, total_height).
        """
        if not lines:
            return 0, 0

        max_width = 0
        line_height = self._line_height(font)
        total_height = line_height * len(lines)

        for line in lines:
            w, _ = self._text_bbox(line, font)
            max_width = max(max_width, w)

        return max_width, total_height

    def _wrap_all_element_texts(self):
        """
        Formats any text that wasn't wrapped earlier (e.g., new elements)
        """
        for elem in self.elements_by_id.values():
            if '_wrapped_name_lines' not in elem:
                elem_w = elem['bounds']['width']
                name_text = elem.get('name', '')
                name_lines = self.wrap_text_to_width(name_text, self.name_font, elem_w) if name_text else []
                elem['_wrapped_name_lines'] = name_lines    
            if '_wrapped_type_lines' not in elem:
                elem_w = elem['bounds']['width']
                type_text = elem.get('type', '')
                type_lines = self.wrap_text_to_width(type_text, self.type_font, elem_w) if type_text else []
                elem['_wrapped_type_lines'] = type_lines

    def _measure_block(self, text: str, font: ImageFont.ImageFont, max_width: float) -> Tuple[float, float]:
        """
        Measure a text block when wrapped within max_width.
        Returns (block_width, block_height).
        """
        if not text:
            return (0,0)
        lines = self.wrap_text_to_width(text, font, max_width)
        if not lines:
            # If can't fit even a single word, measure as a single long line
            w,h = self._text_bbox(text, font)
            return (w,h)
        max_line_w = 0
        line_height = self._line_height(font)
        total_h = line_height * len(lines)

        for line in lines:
            w,h = self._text_bbox(line, font)
            if w > max_line_w:
                max_line_w = w

        return (max_line_w, total_h)

    def _scale_diagram(self, scale_factor: float):
        for elem in self.elements_by_id.values():
            elem['bounds']['x'] *= scale_factor
            elem['bounds']['y'] *= scale_factor
            elem['bounds']['width'] *= scale_factor
            elem['bounds']['height'] *= scale_factor

        for rel in self.relationships.values():
            for p in rel.get('path', []):
                p['x'] *= scale_factor
                p['y'] *= scale_factor

    def _finalize_layout(self):
        min_x, min_y, width, height = compute_diagram_bounds(self.diagram)
        shift_x = -min_x
        shift_y = -min_y

        self.width = width
        self.height = height

        for elem in self.elements_by_id.values():
            elem['bounds']['x'] += shift_x
            elem['bounds']['y'] += shift_y

        for rel in self.relationships.values():
            for p in rel['path']:
                p['x'] += shift_x
                p['y'] += shift_y

    def _create_svg(self):
        svg = ET.Element('svg', {
            'xmlns': 'http://www.w3.org/2000/svg',
            'width': str(self.width),
            'height': str(self.height),
            'viewBox': f'0 0 {self.width} {self.height}'
        })
        self._add_defs(svg)
        return svg

    def _add_defs(self, svg):
        defs = ET.SubElement(svg, 'defs')
        for marker_id, marker_conf in self.markers_config.items():
            marker = ET.SubElement(defs, 'marker', {
                'id': marker_id,
                'viewBox': marker_conf['viewBox'],
                'refX': marker_conf['refX'],
                'refY': marker_conf['refY'],
                'markerWidth': '10',
                'markerHeight': '10',
                'orient': 'auto'
            })
            ET.SubElement(marker, 'path', {
                'd': marker_conf['path'],
                'fill': marker_conf.get('fill', 'black'),
                'stroke': 'black'
            })
        self._add_styles(defs)

    def _add_styles(self, defs):
        if self.css.strip():
            style_element = ET.SubElement(defs, 'style', {'type': 'text/css'})
            style_element.text = self.css
        else:
            print("Warning: No CSS content provided. Styles will not be applied.")

    def wrap_text_to_width(self, text: str, font: ImageFont.ImageFont, max_width: float) -> List[str]:
        if not text:
            return []
        words = text.split()
        if not words:
            return []

        img = Image.new('RGB', (1,1))
        draw = ImageDraw.Draw(img)
        lines = []
        current_line = words[0]

        for word in words[1:]:
            test_line = current_line + " " + word
            left, top, right, bottom = draw.textbbox((0,0), test_line, font=font)
            line_width = right - left
            if line_width <= max_width:
                current_line = test_line
            else:
                lines.append(current_line)
                current_line = word

        lines.append(current_line)
        return lines

    def _line_height(self, font: ImageFont.ImageFont) -> float:
        # Estimate line height based on a single character
        w, h = self._text_bbox("M", font)
        return h * 1.2

    def _text_bbox(self, text: str, font: ImageFont.ImageFont) -> Tuple[float, float]:
        img = Image.new('RGB', (1,1))
        draw = ImageDraw.Draw(img)
        left, top, right, bottom = draw.textbbox((0,0), text, font=font)
        return (right - left, bottom - top)