from src.maze import shortest_path


def test_shortest_path_avoids_walls():
    grid = [[0, 1, 0], [0, 0, 0], [1, 0, 0]]
    assert shortest_path(grid, (0, 0), (0, 2)) == 4


def test_unreachable_goal_returns_none():
    grid = [[0, 1], [1, 0]]
    assert shortest_path(grid, (0, 0), (1, 1)) is None
