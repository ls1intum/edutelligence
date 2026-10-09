def shortest_path(grid, start, goal):
    if not grid:
        return None
    queue = [(start, 0)]
    visited = set()
    while queue:
        (row, column), distance = queue.pop(0)
        if (row, column) == goal:
            return distance
        visited.add((row, column))
    return None
