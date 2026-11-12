from collections import deque


def shortest_path(
    grid: list[list[int]], start: tuple[int, int], goal: tuple[int, int]
) -> int | None:
    queue = deque([(start, 0)])
    visited = {start}
    while queue:
        (row, column), distance = queue.popleft()
        if (row, column) == goal:
            return distance
        for delta_row, delta_column in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            neighbor = row + delta_row, column + delta_column
            next_row, next_column = neighbor
            if (
                0 <= next_row < len(grid)
                and 0 <= next_column < len(grid[0])
                and grid[next_row][next_column] == 0
                and neighbor not in visited
            ):
                visited.add(neighbor)
                queue.append((neighbor, distance + 1))
    return None
