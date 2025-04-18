"""
DISCLAIMER:
This code is a Python adaptation of the original Apollon codebase, which was implemented in TypeScript.
Repository: https://github.com/ls1intum/Apollon.

The purpose of this adaptation is to ensure that the server-side layout renderer replicates the diagram paths as closely as possible to those created by users in the Apollon editor.
"""


import math
from typing import Dict, List, Optional, Any
from module_modeling_llm.helios_renderer.utils.constants import ENTITY_MARGIN, OVERLAP_THRESHOLD
from module_modeling_llm.helios_renderer.models.element import Element
from module_modeling_llm.helios_renderer.models.relationship import Relationship

# Directions enumeration as used in the original code for port/connection directions
class Direction:
    Up = 'Up'
    Down = 'Down'
    Left = 'Left'
    Right = 'Right'
    Upright = 'Upright'
    Upleft = 'Upleft'
    Downright = 'Downright'
    Downleft = 'Downleft'
    Topright = 'Topright'
    Topleft = 'Topleft'
    Bottomright = 'Bottomright'
    Bottomleft = 'Bottomleft'

def compute_relationship_path(source_element: Element, target_element: Element, rel: Relationship) -> List[Dict[str, float]]:
    """
    Compute the polyline path connecting two elements (source_element and target_element) based on their given relationship.

    The relationship includes hints about the direction of connection points (ports).
    This function uses a complex routing logic to produce a set of points (x,y) that represent the path between source and target.

    :param source_element: The element acting as the source of the connection.
    :param target_element: The element acting as the target of the connection.
    :param rel: A dictionary-like relationship object containing direction hints for source and target.
    :return: A list of dictionaries with 'x' and 'y' keys representing coordinates along the path.
    """

    # Extract direction hints from the relationship
    source_direction = rel['source'].get('direction', Direction.Right)
    target_direction = rel['target'].get('direction', Direction.Left)

    # Organize source and target data
    source = {'element': source_element, 'direction': source_direction}
    target = {'element': target_element, 'direction': target_direction}

    # Options control path routing strategy
    # 'isStraight': Whether to consider directly connecting points if possible
    # 'isVariable': Whether to attempt variable straight alignments if direct straight line isn't immediately possible
    options = {'isStraight': False, 'isVariable': True}

    # Compute the initial path using the main routing function
    path = compute_path(source, target, options)
    # "Beautify" the resulting path by removing unnecessary bends and points
    return beautify_path(path)

def compute_path(source: Dict[str, Any], target: Dict[str, Any], options: Dict[str, bool]) -> List[Dict[str, float]]:
    """
    Compute a path connecting source and target points, considering various options.

    This tries a few strategies:
    1. If 'isStraight' is set, try to connect source and target directly.
    2. If 'isVariable' is set and a straight alignment is possible (e.g., horizontally or vertically aligned), use it.
    3. Otherwise, resort to complex routing with margin-based detours around entity boxes.

    :param source: Dictionary containing 'element' (with bounds) and 'direction' for the source port.
    :param target: Dictionary containing 'element' (with bounds) and 'direction' for the target port.
    :param options: Options dict that can contain 'isStraight' and 'isVariable' booleans.
    :return: A path as a list of (x,y) dictionaries.
    """
    # Determine the precise port positions for source and target based on direction and element bounds
    source_port_position = get_port_position(source['element']['bounds'], source['direction'])
    target_port_position = get_port_position(target['element']['bounds'], target['direction'])

    # If a completely straight path is allowed and possible
    if options.get('isStraight'):
        straight_path = [source_port_position, target_port_position]
        if points_are_equal(straight_path[0], straight_path[1]):
            # Avoid zero-length lines by nudging the end point
            straight_path[1]['x'] += 1
            straight_path[1]['y'] += 1
        return straight_path

    # If variable alignment is allowed, try to find a straight path with some constraints
    if options.get('isVariable'):
        straight = try_find_straight_path(source, target)
        if straight is not None:
            # If both points coincide, nudge the second point
            if points_are_equal(straight[0], straight[1]):
                straight[1]['x'] += 1
                straight[1]['y'] += 1
            return straight

    # If no straightforward solution is found, use a complex routing with margins
    return route_with_margins(source, target, source_port_position, target_port_position)

def route_with_margins(source: Dict[str, Any], target: Dict[str, Any],
                       source_port_position: Dict[str, float],
                       target_port_position: Dict[str, float]) -> List[Dict[str, float]]:
    """
    Compute a path by navigating around the margins of source and target elements to avoid overlapping them.

    This logic tries to find a route along corners (extended by ENTITY_MARGIN) around the source and target boxes,
    picking a sequence of intermediate points (corners) to ensure a clear path that doesn't intersect the boxes themselves.

    If direct connections fail, it expands the path along margin-inflated rectangles that represent possible routing edges.

    :param source: Dictionary with 'element' and 'direction' for the source endpoint.
    :param target: Dictionary with 'element' and 'direction' for the target endpoint.
    :param source_port_position: The actual coordinate of the source connection port.
    :param target_port_position: The actual coordinate of the target connection port.
    :return: A list of (x,y) points representing the path.
    """
    # Create margin-inflated rectangles around source and target to route around
    source_margin_rect = enlarge_rect(source['element']['bounds'], ENTITY_MARGIN)
    target_margin_rect = enlarge_rect(target['element']['bounds'], ENTITY_MARGIN)

    # Slightly smaller margin rectangles (1px less) for intersection checks
    source_margin_rect1px = enlarge_rect(source['element']['bounds'], ENTITY_MARGIN - 1)
    target_margin_rect1px = enlarge_rect(target['element']['bounds'], ENTITY_MARGIN - 1)

    # Adjust start/end points outward depending on direction to start routing outside the margin
    start_point_on_margin_box = adjust_point_on_margin_box(source_port_position, source['direction'], ENTITY_MARGIN)
    end_point_on_margin_box = adjust_point_on_margin_box(target_port_position, target['direction'], ENTITY_MARGIN)

    # Find corners of source margin rect closest to the end point and vice versa
    source_corner_closest_to_end = find_closest_point(get_corners(source_margin_rect), end_point_on_margin_box)
    target_corner_closest_to_source = find_closest_point(get_corners(target_margin_rect), source_corner_closest_to_end)

    # Determine sequences of corners (queues) to try navigating around the source and target boxes
    source_queue = determine_corner_queue(
        source_margin_rect, source['direction'], start_point_on_margin_box, source_corner_closest_to_end
    )
    target_queue = determine_corner_queue(
        target_margin_rect, target['direction'], end_point_on_margin_box, target_corner_closest_to_source
    )

    # We'll build paths from start and end, then attempt to merge them
    path_from_start = [source_port_position, start_point_on_margin_box]
    path_from_end = [target_port_position, end_point_on_margin_box]

    current_start = start_point_on_margin_box.copy()
    current_end = end_point_on_margin_box.copy()

    # Attempt to connect these two partial paths by testing if a direct line segment can be drawn at each iteration
    while True:
        # Check if we can connect directly without intersecting boxes
        if can_connect_directly(current_start, current_end, source_margin_rect1px, target_margin_rect1px):
            # If so, merge paths (align axes if needed)
            merge_paths(path_from_start, path_from_end, current_start, current_end)
            break

        # If direct connection not possible, advance along source queue if available
        if source_queue:
            next_corner = source_queue.pop(0)
            path_from_start.append(next_corner)
            current_start = next_corner
        # Else try advancing along target queue
        elif target_queue:
            next_corner = target_queue.pop(0)
            path_from_end.append(next_corner)
            current_end = next_corner
        else:
            # As a fallback, if no routing is possible, just connect source and target directly
            return [source_port_position, target_port_position]

    # Combine the two partial paths (path_from_start and reversed(path_from_end)) into a full route
    full_path = path_from_start + list(reversed(path_from_end))
    return full_path

def can_connect_directly(start: Dict[str, float], end: Dict[str, float],
                         source_rect: Dict[str, float], target_rect: Dict[str, float]) -> bool:
    """
    Check if a direct line segment between start and end intersects the given source and target rectangles.

    :return: True if the direct line does not intersect either rectangle, False otherwise.
    """
    return (not line_segment_intersects_rect(start, end, source_rect)
            and not line_segment_intersects_rect(start, end, target_rect))

def merge_paths(path_from_start: List[Dict[str, float]], path_from_end: List[Dict[str, float]],
                current_start: Dict[str, float], current_end: Dict[str, float]) -> None:
    """
    Merge two partial paths by adding intermediate points if necessary to create a neat connection.

    This tries to align the last segment of path_from_start and the first segment of path_from_end either horizontally
    or vertically. If both segments are along the same axis, create a 'bridge' by adding intermediate points at midpoints.

    :param path_from_start: The partial path starting from the source.
    :param path_from_end: The partial path starting from the target.
    :param current_start: The current endpoint of the start side.
    :param current_end: The current endpoint of the end side.
    """
    start_axis = get_axis_for_path_segment(path_from_start[-2], path_from_start[-1])
    end_axis = get_axis_for_path_segment(path_from_end[-2], path_from_end[-1])

    # If both ends are horizontally aligned
    if start_axis == 'HORIZONTAL' and end_axis == 'HORIZONTAL':
        middle_x = (current_start['x'] + current_end['x']) / 2
        # Insert bend points to gracefully connect horizontally
        path_from_start.append({'x': middle_x, 'y': current_start['y']})
        path_from_start.append({'x': middle_x, 'y': current_end['y']})
    # If both ends are vertically aligned
    elif start_axis == 'VERTICAL' and end_axis == 'VERTICAL':
        middle_y = (current_start['y'] + current_end['y']) / 2
        # Insert bend points to gracefully connect vertically
        path_from_start.append({'x': current_start['x'], 'y': middle_y})
        path_from_start.append({'x': current_end['x'], 'y': middle_y})
    # If one end is horizontal and the other vertical, we can connect directly using one bend
    elif start_axis == 'HORIZONTAL' and end_axis == 'VERTICAL':
        path_from_start.append({'x': current_end['x'], 'y': current_start['y']})
    else:
        # Otherwise, connect by aligning along one coordinate
        path_from_start.append({'x': current_start['x'], 'y': current_end['y']})

def get_port_position(bounds: Dict[str, float], direction: str) -> Dict[str, float]:
    """
    Compute the coordinate of the port on an element's bounds based on the given direction.

    Directions indicate which side or corner of the rectangle is used to connect. For example:
    - Up: connect at midpoint of the top edge
    - Down: midpoint of the bottom edge
    - Left/Right: midpoints of left/right edges respectively
    - Other directions are variations of corners or fractional positions on the edges.
    """
    x = bounds['x']
    y = bounds['y']
    w = bounds['width']
    h = bounds['height']

    # Map direction to a specific point on the element's rectangle
    if direction == Direction.Up:
        return {'x': x + w/2, 'y': y}
    elif direction == Direction.Down:
        return {'x': x + w/2, 'y': y + h}
    elif direction == Direction.Left:
        return {'x': x, 'y': y + h/2}
    elif direction == Direction.Right:
        return {'x': x + w, 'y': y + h/2}
    elif direction == Direction.Upright:
        return {'x': x + w, 'y': y}
    elif direction == Direction.Upleft:
        return {'x': x, 'y': y}
    elif direction == Direction.Downright:
        return {'x': x + w, 'y': y + h}
    elif direction == Direction.Downleft:
        return {'x': x, 'y': y + h}
    elif direction == Direction.Topright:
        return {'x': x + w * 0.75, 'y': y}
    elif direction == Direction.Topleft:
        return {'x': x + w * 0.25, 'y': y}
    elif direction == Direction.Bottomright:
        return {'x': x + w * 0.75, 'y': y + h}
    elif direction == Direction.Bottomleft:
        return {'x': x + w * 0.25, 'y': y + h}
    else:
        # Fallback: center if direction not recognized
        return {'x': x + w/2, 'y': y + h/2}

def adjust_point_on_margin_box(point: Dict[str, float], direction: str, margin: float) -> Dict[str, float]:
    """
    Adjust a point outward by a given margin depending on the direction.
    For example, if the direction is Up, we move the point up by 'margin' units.
    This creates a start/end point outside the entity margin box, ensuring room to route the line.

    :param point: The initial point (on the element border).
    :param direction: The direction from the element.
    :param margin: The margin distance to move outward.
    :return: The adjusted point.
    """
    adjusted = point.copy()
    if direction in [Direction.Up, Direction.Topleft, Direction.Topright]:
        adjusted['y'] -= margin
    elif direction in [Direction.Down, Direction.Bottomleft, Direction.Bottomright]:
        adjusted['y'] += margin
    elif direction in [Direction.Left, Direction.Upleft, Direction.Downleft]:
        adjusted['x'] -= margin
    elif direction in [Direction.Right, Direction.Upright, Direction.Downright]:
        adjusted['x'] += margin
    return adjusted

def enlarge_rect(rect: Dict[str, float], padding: float) -> Dict[str, float]:
    """
    Enlarge a given rectangle by 'padding' units on all sides.

    :param rect: The original rectangle defined by (x, y, width, height).
    :param padding: How much to expand each side by.
    :return: The enlarged rectangle.
    """
    return {
        'x': rect['x'] - padding,
        'y': rect['y'] - padding,
        'width': rect['width'] + 2 * padding,
        'height': rect['height'] + 2 * padding
    }

def get_corners(rect: Dict[str, float]) -> List[Dict[str, float]]:
    """
    Return a list of the four corners of a rectangle in order: top-left, top-right, bottom-right, bottom-left.
    """
    return [
        {'x': rect['x'], 'y': rect['y']},
        {'x': rect['x'] + rect['width'], 'y': rect['y']},
        {'x': rect['x'] + rect['width'], 'y': rect['y'] + rect['height']},
        {'x': rect['x'], 'y': rect['y'] + rect['height']}
    ]

def find_closest_point(candidates: List[Dict[str, float]], target: Dict[str, float]) -> Dict[str, float]:
    """
    Find the candidate point closest to the target point using Euclidean distance.

    :param candidates: A list of (x,y) points.
    :param target: The reference point.
    :return: The closest candidate point.
    """
    min_dist = float('inf')
    closest = candidates[0]
    for c in candidates:
        d = math.hypot(c['x'] - target['x'], c['y'] - target['y'])
        if d < min_dist:
            min_dist = d
            closest = c
    return closest

def determine_corner_queue(rect: Dict[str, float], direction: str, start: Dict[str, float], end: Dict[str, float]) -> List[Dict[str, float]]:
    """
    Determine the sequence (queue) of corners to attempt routing through, depending on the direction
    and the relative position of end point. This tries to find a shorter path around the rectangle corners.

    The logic chooses a clockwise or counterclockwise ordering of corners and selects the shorter route.

    :param rect: Margin rectangle around the element.
    :param direction: The direction from which we start (source/target direction).
    :param start: The starting point from which we're determining the corner route.
    :param end: The end reference point (we pick corners that lead us closer to this end).
    :return: A list of corner points in the chosen order.
    """
    corners = get_corners(rect)

    # Based on direction, define a clockwise and counter-clockwise corner order
    if direction in [Direction.Up, Direction.Topleft, Direction.Topright]:
        clockwise = [corners[1], corners[2], corners[3], corners[0]]
        counter = [corners[0], corners[3], corners[2], corners[1]]
    elif direction in [Direction.Right, Direction.Upright, Direction.Downright]:
        clockwise = [corners[2], corners[3], corners[0], corners[1]]
        counter = [corners[1], corners[0], corners[3], corners[2]]
    elif direction in [Direction.Down, Direction.Bottomleft, Direction.Bottomright]:
        clockwise = [corners[3], corners[0], corners[1], corners[2]]
        counter = [corners[2], corners[1], corners[0], corners[3]]
    elif direction in [Direction.Left, Direction.Upleft, Direction.Downleft]:
        clockwise = [corners[0], corners[1], corners[2], corners[3]]
        counter = [corners[3], corners[2], corners[1], corners[0]]
    else:
        # Default fallback
        clockwise = corners
        counter = list(reversed(corners))

    # Trim the sequences so they only go as far as the corner closest to the end point
    clockwise = shorten_queue_to_corner(clockwise, end)
    counter = shorten_queue_to_corner(counter, end)

    # Compute path lengths for both options and choose the shorter one
    path_length_cw = compute_path_length([start] + clockwise)
    path_length_ccw = compute_path_length([start] + counter)

    return clockwise if path_length_cw < path_length_ccw else counter

def shorten_queue_to_corner(queue: List[Dict[str,float]], corner: Dict[str,float]) -> List[Dict[str,float]]:
    """
    Cut the queue of corners at the specified corner if it exists in the queue.

    :param queue: A list of corner points.
    :param corner: A corner point to cut at.
    :return: The shortened queue ending at the given corner.
    """
    if corner in queue:
        idx = queue.index(corner)
        return queue[:idx+1]
    return queue

def compute_path_length(path: List[Dict[str, float]]) -> float:
    """
    Compute the total Euclidean length of a path defined by a sequence of points.

    :param path: List of (x,y) points.
    :return: The total length.
    """
    length = 0
    for i in range(len(path)-1):
        length += math.hypot(path[i+1]['x'] - path[i]['x'], path[i+1]['y'] - path[i]['y'])
    return length

def line_segment_intersects_rect(p: Dict[str, float], q: Dict[str, float], rect: Dict[str, float]) -> bool:
    """
    Check if a line segment defined by points p and q intersects any edge of the rectangle.

    :return: True if the segment intersects the rectangle boundary, else False.
    """
    # Define the 4 edges of the rectangle
    rect_lines = [
        ( {'x': rect['x'], 'y': rect['y']},
          {'x': rect['x'] + rect['width'], 'y': rect['y']} ),
        ( {'x': rect['x'] + rect['width'], 'y': rect['y']},
          {'x': rect['x'] + rect['width'], 'y': rect['y'] + rect['height']} ),
        ( {'x': rect['x'] + rect['width'], 'y': rect['y'] + rect['height']},
          {'x': rect['x'], 'y': rect['y'] + rect['height']} ),
        ( {'x': rect['x'], 'y': rect['y'] + rect['height']},
          {'x': rect['x'], 'y': rect['y']} ),
    ]
    # Check intersection with each edge
    for r_p, r_q in rect_lines:
        if line_segments_intersect(p, q, r_p, r_q):
            return True
    return False

def line_segments_intersect(p1, q1, p2, q2) -> bool:
    """
    Determine if two line segments (p1-q1 and p2-q2) intersect.

    Uses orientation tests and on-segment checks to see if the segments share any point.
    """
    def orientation(a, b, c):
        val = (b['y'] - a['y']) * (c['x'] - b['x']) - (b['x'] - a['x']) * (c['y'] - b['y'])
        if abs(val) < 1e-6:
            return 0
        return 1 if val > 0 else 2

    def on_segment(a, b, c):
        return (min(a['x'], c['x']) <= b['x'] <= max(a['x'], c['x'])
                and min(a['y'], c['y']) <= b['y'] <= max(a['y'], c['y']))

    # Compute orientations
    o1 = orientation(p1, q1, p2)
    o2 = orientation(p1, q1, q2)
    o3 = orientation(p2, q2, p1)
    o4 = orientation(p2, q2, q1)

    # General case: if orientations differ, there's an intersection
    if o1 != o2 and o3 != o4:
        return True
    # Special cases: checking collinear points lying on segments
    if o1 == 0 and on_segment(p1, p2, q1):
        return True
    if o2 == 0 and on_segment(p1, q2, q1):
        return True
    if o3 == 0 and on_segment(p2, p1, q2):
        return True
    if o4 == 0 and on_segment(p2, q1, q2):
        return True

    return False

def points_are_equal(p: Dict[str, float], q: Dict[str, float]) -> bool:
    """
    Check if two points are effectively the same, allowing for a negligible floating-point error.
    """
    return is_almost_zero(p['x'] - q['x']) and is_almost_zero(p['y'] - q['y'])

def is_almost_zero(value: float) -> bool:
    """
    Check if a value is close to zero, within a small epsilon.
    """
    return abs(value) < 1e-6

def try_find_straight_path(source: Dict[str, Any], target: Dict[str, Any]) -> Optional[List[Dict[str, float]]]:
    """
    Attempt to find a straight (directly horizontal or vertical) path between two rectangles,
    given direction hints for the handles. This checks for overlapping ranges and alignment conditions.

    This tries:
    - Horizontal alignment if source's direction is Right and target's is Left (or vice versa),
      and their vertical spans overlap sufficiently.
    - Vertical alignment if source's direction is Down and target's is Up (or vice versa),
      and their horizontal spans overlap.

    If a suitable straight line is found, return two points defining it. Otherwise, return None.
    """
    source_bounds = source['element']['bounds']
    target_bounds = target['element']['bounds']
    source_edge = determine_handle_edge(source['direction'])
    target_edge = determine_handle_edge(target['direction'])

    # Horizontal alignment attempt
    if source_edge == Direction.Right and target_edge == Direction.Left and target_bounds['x'] >= source_bounds['x'] + source_bounds['width']:
        overlap_y = compute_overlap(
            [source_bounds['y'], source_bounds['y'] + max(OVERLAP_THRESHOLD, source_bounds['height'])],
            [target_bounds['y'], target_bounds['y'] + max(OVERLAP_THRESHOLD, target_bounds['height'])]
        )
        if overlap_y and (overlap_y[1] - overlap_y[0] >= OVERLAP_THRESHOLD):
            mid_y = (overlap_y[0] + overlap_y[1]) / 2
            return [{'x': source_bounds['x'] + source_bounds['width'], 'y': mid_y},
                    {'x': target_bounds['x'], 'y': mid_y}]

    if source_edge == Direction.Left and target_edge == Direction.Right and source_bounds['x'] >= target_bounds['x'] + target_bounds['width']:
        overlap_y = compute_overlap(
            [source_bounds['y'], source_bounds['y'] + max(OVERLAP_THRESHOLD, source_bounds['height'])],
            [target_bounds['y'], target_bounds['y'] + max(OVERLAP_THRESHOLD, target_bounds['height'])]
        )
        if overlap_y and (overlap_y[1] - overlap_y[0] >= OVERLAP_THRESHOLD):
            mid_y = (overlap_y[0] + overlap_y[1]) / 2
            return [{'x': source_bounds['x'], 'y': mid_y},
                    {'x': target_bounds['x'] + target_bounds['width'], 'y': mid_y}]

    # Vertical alignment attempt
    if source_edge == Direction.Down and target_edge == Direction.Up and target_bounds['y'] >= source_bounds['y'] + source_bounds['height']:
        overlap_x = compute_overlap(
            [source_bounds['x'], source_bounds['x'] + source_bounds['width']],
            [target_bounds['x'], target_bounds['x'] + target_bounds['width']]
        )
        if overlap_x and (overlap_x[1] - overlap_x[0] >= OVERLAP_THRESHOLD):
            mid_x = (overlap_x[0] + overlap_x[1]) / 2
            return [{'x': mid_x, 'y': source_bounds['y'] + source_bounds['height']},
                    {'x': mid_x, 'y': target_bounds['y']}]

    if source_edge == Direction.Up and target_edge == Direction.Down and source_bounds['y'] >= target_bounds['y'] + target_bounds['height']:
        overlap_x = compute_overlap(
            [source_bounds['x'], source_bounds['x'] + source_bounds['width']],
            [target_bounds['x'], target_bounds['x'] + target_bounds['width']]
        )
        if overlap_x and (overlap_x[1] - overlap_x[0] >= OVERLAP_THRESHOLD):
            mid_x = (overlap_x[0] + overlap_x[1]) / 2
            return [{'x': mid_x, 'y': source_bounds['y']},
                    {'x': mid_x, 'y': target_bounds['y'] + target_bounds['height']}]

    return None

def determine_handle_edge(direction: str) -> str:
    """
    Given a handle direction (which might be a corner like 'Upleft' or just 'Left'),
    determine the main edge axis (Up, Down, Left, or Right) it corresponds to.
    """
    if direction in [Direction.Left, Direction.Upleft, Direction.Downleft]:
        return Direction.Left
    elif direction in [Direction.Right, Direction.Upright, Direction.Downright]:
        return Direction.Right
    elif direction in [Direction.Up, Direction.Topleft, Direction.Topright]:
        return Direction.Up
    elif direction in [Direction.Down, Direction.Bottomleft, Direction.Bottomright]:
        return Direction.Down
    return Direction.Right

def compute_overlap(range1: List[float], range2: List[float]) -> Optional[List[float]]:
    """
    Compute the overlapping segment between two 1D ranges (if any).

    :param range1: [start1, end1]
    :param range2: [start2, end2]
    :return: The overlapping [start, end] if they overlap, otherwise None.
    """
    from1, to1 = range1
    from2, to2 = range2
    larger_from = max(from1, from2)
    smaller_to = min(to1, to2)
    if larger_from <= smaller_to:
        return [larger_from, smaller_to]
    return None

def beautify_path(path: List[Dict[str, float]]) -> List[Dict[str, float]]:
    """
    Clean up the generated path by:
    1. Removing consecutive identical points.
    2. Merging consecutive segments aligned on the same axis.
    3. Flattening 'waves' or unnecessary zig-zags.
    4. Removing unnecessary transit nodes that don't change direction.

    :param path: The original path.
    :return: A simplified, cleaner path.
    """
    path = remove_consecutive_identical_points(path)
    path = merge_consecutive_same_axis_deltas(path)
    path = flatten_waves(path)
    path = remove_transit_nodes(path)
    return path

def remove_consecutive_identical_points(path: List[Dict[str, float]]) -> List[Dict[str, float]]:
    """
    Remove any repeated points that follow one another directly.
    """
    new_path = []
    for p in path:
        if not new_path or not points_are_equal(p, new_path[-1]):
            new_path.append(p)
    return new_path

def merge_consecutive_same_axis_deltas(path: List[Dict[str, float]]) -> List[Dict[str, float]]:
    """
    Merge consecutive line segments that lie along the same axis (purely horizontal or vertical)
    into a single straight segment. This avoids unnecessary intermediate points.
    """
    deltas = compute_path_deltas(path)
    if len(deltas) <= 1:
        return path

    new_deltas = []
    for delta in deltas:
        prev = new_deltas[-1] if new_deltas else None
        if not prev:
            new_deltas.append(delta)
        # If current and previous deltas are both horizontal or both vertical, merge them
        elif (is_almost_zero(prev['dx']) and is_almost_zero(delta['dx'])) or \
             (is_almost_zero(prev['dy']) and is_almost_zero(delta['dy'])):
            new_deltas[-1] = {'dx': prev['dx'] + delta['dx'], 'dy': prev['dy'] + delta['dy']}
        else:
            new_deltas.append(delta)
    return create_path_from_deltas(path[0], new_deltas)

def flatten_waves(path: List[Dict[str, float]]) -> List[Dict[str, float]]:
    """
    Attempt to remove 'waves' or zig-zag patterns in the path by simplifying delta patterns.

    This looks for certain patterns of horizontal/vertical/horizontal (or vertical/horizontal/vertical) moves
    that can be simplified into straighter segments.
    """
    if len(path) < 4:
        return path
    deltas = compute_path_deltas(path)
    simplified = simplify_deltas(deltas)
    return create_path_from_deltas(path[0], simplified)

def remove_transit_nodes(path: List[Dict[str, float]]) -> List[Dict[str, float]]:
    """
    Remove transit nodes that lie perfectly on a straight line between their neighbors,
    reducing the path complexity.
    """
    for i in range(len(path)-2):
        p,q,r = path[i], path[i+1], path[i+2]
        if is_horizontal_line_segment(p,q,r) or is_vertical_line_segment(p,q,r):
            # Recursively remove and attempt again, ensuring all unnecessary nodes are cleaned up
            return remove_transit_nodes(path[:i+1] + path[i+2:])
    return path

def compute_path_deltas(path: List[Dict[str, float]]) -> List[Dict[str, float]]:
    """
    Compute delta vectors between consecutive points in the path.
    Each delta is {dx, dy} indicating the change from one point to the next.
    """
    deltas = []
    for i in range(len(path)-1):
        dx = path[i+1]['x'] - path[i]['x']
        dy = path[i+1]['y'] - path[i]['y']
        deltas.append({'dx': dx, 'dy': dy})
    return deltas

def create_path_from_deltas(start: Dict[str, float], deltas: List[Dict[str, float]]) -> List[Dict[str, float]]:
    """
    Reconstruct a path from a starting point and a list of deltas.
    """
    points = [start]
    current = start.copy()
    for d in deltas:
        current = {'x': current['x'] + d['dx'], 'y': current['y'] + d['dy']}
        points.append(current)
    return points

def simplify_deltas(deltas: List[Dict[str, float]]) -> List[Dict[str, float]]:
    """
    Look for 'wave' patterns in the deltas and try to simplify them.

    This is a more complex cleanup step that reduces unnecessary directional changes:
    For example, a pattern like horizontal->vertical->horizontal that forms a small 'wave'
    is replaced by a simpler two-segment route if possible.
    """
    i = 0
    while i < len(deltas) - 3:
        d1, d2, d3, d4 = deltas[i], deltas[i+1], deltas[i+2], deltas[i+3]

        # First pattern: Horizontal, vertical, horizontal segment forming a wave
        if (
            is_almost_zero(d1['dy']) and
            is_almost_zero(d2['dx']) and
            is_almost_zero(d3['dy']) and
            math.copysign(1, d1['dx']) == math.copysign(1, d3['dx']) and
            math.copysign(1, d2['dy']) == math.copysign(1, d4['dy'])
        ):
            new_deltas = (
                deltas[:i] +
                [
                    {'dx': d1['dx'] + d3['dx'], 'dy': 0},
                    {'dx': 0, 'dy': d2['dy']}
                ] +
                deltas[i+4:]
            )
            return simplify_deltas(new_deltas)

        # Second pattern: Vertical, horizontal, vertical wave
        if (
            is_almost_zero(d1['dx']) and
            is_almost_zero(d2['dy']) and
            is_almost_zero(d3['dx']) and
            math.copysign(1, d1['dy']) == math.copysign(1, d3['dy']) and
            math.copysign(1, d2['dx']) == math.copysign(1, d4['dx'])
        ):
            new_deltas = (
                deltas[:i] +
                [
                    {'dx': 0, 'dy': d1['dy'] + d3['dy']},
                    {'dx': d2['dx'], 'dy': 0}
                ] +
                deltas[i+4:]
            )
            return simplify_deltas(new_deltas)

        i += 1
    return deltas

def get_axis_for_path_segment(p1: Dict[str, float], p2: Dict[str, float]) -> Optional[str]:
    """
    Determine if a segment between p1 and p2 is purely horizontal or vertical.

    :return: 'HORIZONTAL' if the segment is along the x-axis, 'VERTICAL' if along the y-axis, or None otherwise.
    """
    if is_almost_zero(p1['x'] - p2['x']) and not is_almost_zero(p1['y'] - p2['y']):
        return 'VERTICAL'
    elif is_almost_zero(p1['y'] - p2['y']) and not is_almost_zero(p1['x'] - p2['x']):
        return 'HORIZONTAL'
    return None

def is_horizontal_line_segment(p, q, r):
    """
    Check if three points p, q, r lie on the same horizontal line and q is between p and r on the x-axis.
    """
    return (are_almost_equal(p['y'], q['y']) and are_almost_equal(q['y'], r['y'])
            and ((p['x'] >= q['x'] >= r['x']) or (p['x'] <= q['x'] <= r['x'])))

def is_vertical_line_segment(p, q, r):
    """
    Check if three points p, q, r lie on the same vertical line and q is between p and r on the y-axis.
    """
    return (are_almost_equal(p['x'], q['x']) and are_almost_equal(q['x'], r['x'])
            and ((p['y'] >= q['y'] >= r['y']) or (p['y'] <= q['y'] <= r['y'])))

def are_almost_equal(a, b):
    """
    Check if two floating-point values are nearly equal.
    """
    return is_almost_zero(a - b)