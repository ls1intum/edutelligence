import runpy
import shutil
import subprocess  # nosec B404 - fixed local javac/java commands
from pathlib import Path

import pytest

QA_ROOT = Path(__file__).parents[1] / "qa"


def _java_tools() -> tuple[str, str]:
    javac = shutil.which("javac")
    java = shutil.which("java")
    if not javac or not java:
        pytest.skip("A JDK is required to execute the Java QA repository fixture")
    return javac, java


def _compile_and_run_sort(source: Path, tmp_path: Path) -> subprocess.CompletedProcess:
    javac, java = _java_tools()
    harness = tmp_path / "SortHarness.java"
    harness.write_text(
        """package de.tum.in.ase;
import java.util.Arrays;

public final class SortHarness {
    public static void main(String[] args) {
        int[] values = {3, -1, 3, 0};
        Sort.insertionSort(values);
        if (!Arrays.equals(values, new int[]{-1, 0, 3, 3})) {
            throw new AssertionError(Arrays.toString(values));
        }
    }
}
""",
        encoding="utf-8",
    )
    classes = tmp_path / "classes"
    classes.mkdir()
    compiled = subprocess.run(  # nosec B603 - argument list, fixed executables
        [javac, "-d", str(classes), str(source), str(harness)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert compiled.returncode == 0, compiled.stderr
    return subprocess.run(  # nosec B603 - argument list, fixed executables
        [java, "-cp", str(classes), "de.tum.in.ase.SortHarness"],
        capture_output=True,
        text=True,
        check=False,
    )


def test_python_maze_reference_solution_matches_its_public_tests():
    module = runpy.run_path(
        str(QA_ROOT / "artifacts/programming/maze/solution/src/maze.py")
    )
    shortest_path = module["shortest_path"]

    grid = [[0, 1, 0], [0, 0, 0], [1, 0, 0]]
    assert shortest_path(grid, (0, 0), (0, 2)) == 4
    assert shortest_path([[0, 1], [1, 0]], (0, 0), (1, 1)) is None


def test_student_maze_snapshot_reproduces_the_recorded_failure():
    module = runpy.run_path(
        str(QA_ROOT / "artifacts/programming/maze/student/latest/src/maze.py")
    )
    shortest_path = module["shortest_path"]

    grid = [[0, 1, 0], [0, 0, 0], [1, 0, 0]]
    assert shortest_path(grid, (0, 0), (0, 2)) is None


def test_java_sorting_reference_solution_matches_its_hidden_test(tmp_path):
    source = QA_ROOT / "artifacts/programming/sorting/solution/src/Sort.java"

    completed = _compile_and_run_sort(source, tmp_path)

    assert completed.returncode == 0, completed.stderr


def test_java_sorting_student_snapshot_reproduces_hidden_test_failure(tmp_path):
    source = (
        QA_ROOT / "artifacts/programming/sorting/student/failing-tests/src/Sort.java"
    )

    completed = _compile_and_run_sort(source, tmp_path)

    assert completed.returncode != 0
    assert "AssertionError" in completed.stderr


def test_java_sorting_compile_failure_snapshot_reproduces_build_failure(tmp_path):
    javac, _ = _java_tools()
    source = (
        QA_ROOT / "artifacts/programming/sorting/student/compile-failure/src/Sort.java"
    )

    completed = subprocess.run(  # nosec B603 - argument list, fixed executable
        [javac, "-d", str(tmp_path), str(source)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode != 0
    assert "error" in completed.stderr.casefold()
