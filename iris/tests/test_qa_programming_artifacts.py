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


def _compile_and_run_build_planner(
    source_root: Path, tmp_path: Path
) -> subprocess.CompletedProcess:
    javac, java = _java_tools()
    harness = tmp_path / "BuildPlannerHarness.java"
    harness.write_text(
        """package edu.tum.build;
import java.util.Set;

public final class BuildPlannerHarness {
    public static void main(String[] args) {
        var graph = new InMemoryDependencyGraph();
        graph.addDependency("api", "core");
        graph.addDependency("web", "api");
        var planner = new BuildPlanner(graph, new BuildPlanCache());
        if (!Set.copyOf(planner.plan(Set.of("core")))
                .equals(Set.of("core", "api", "web"))) {
            throw new AssertionError("reverse dependent traversal failed");
        }
        graph.addDependency("cli", "api");
        if (!Set.copyOf(planner.plan(Set.of("core")))
                .equals(Set.of("core", "api", "web", "cli"))) {
            throw new AssertionError("graph revision cache invalidation failed");
        }
    }
}
""",
        encoding="utf-8",
    )
    classes = tmp_path / "build-planner-classes"
    classes.mkdir()
    sources = sorted(source_root.rglob("*.java"))
    compiled = subprocess.run(  # nosec B603 - fixed executable and local paths
        [javac, "-d", str(classes), *(str(path) for path in sources), str(harness)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert compiled.returncode == 0, compiled.stderr
    return subprocess.run(  # nosec B603 - fixed executable and local class
        [java, "-cp", str(classes), "edu.tum.build.BuildPlannerHarness"],
        capture_output=True,
        text=True,
        check=False,
    )


def test_build_planner_reference_solution_satisfies_both_failure_cases(tmp_path):
    source_root = (
        QA_ROOT
        / "artifacts/challenge/build-planner/solution/src/main/java/edu/tum/build"
    )

    completed = _compile_and_run_build_planner(source_root, tmp_path)

    assert completed.returncode == 0, completed.stderr


def test_build_planner_latest_snapshot_reproduces_recorded_failure(tmp_path):
    source_root = (
        QA_ROOT
        / "artifacts/challenge/build-planner/student/latest/src/main/java/edu/tum/build"
    )

    completed = _compile_and_run_build_planner(source_root, tmp_path)

    assert completed.returncode != 0
    assert "reverse dependent traversal failed" in completed.stderr


def _compile_and_run_batch_retry(
    source_root: Path, tmp_path: Path, *, student_snapshot: bool
) -> subprocess.CompletedProcess:
    javac, java = _java_tools()
    harness = tmp_path / "BatchRetryHarness.java"
    constructor = (
        "new BatchProcessor(accounts, new AuditSink(), new RetryPolicy(3))"
        if student_snapshot
        else "new BatchProcessor(accounts)"
    )
    harness.write_text(
        """package edu.tum.payments;

import java.util.ArrayList;
import java.util.List;

public final class BatchRetryHarness {
    public static void main(String[] args) {
        List<String> failures = new ArrayList<>();

        var accounts = new AccountStore();
        accounts.put("a", 100);
        accounts.put("b", 10);
        var processor = __CONSTRUCTOR__;
        var batch = new Batch(
                "north", "71", List.of(new Debit("a", 30), new Debit("b", 20)));
        try {
            processor.process(batch);
            failures.add("insufficient batch unexpectedly succeeded");
        } catch (IllegalStateException expected) {
            // Contract: the failed operation may be retried after balances change.
        }
        if (accounts.balance("a") != 100 || accounts.balance("b") != 10) {
            failures.add("failed batch was not atomic");
        }
        accounts.put("b", 50);
        if (processor.process(batch) != ProcessResult.APPLIED
                || accounts.balance("a") != 70
                || accounts.balance("b") != 30) {
            failures.add("retry repeated a debit from the failed attempt");
        }

        accounts = new AccountStore();
        accounts.put("shared", 100);
        processor = __CONSTRUCTOR__;
        processor.process(new Batch("north", "71", List.of(new Debit("shared", 10))));
        ProcessResult otherTenant = processor.process(
                new Batch("south", "71", List.of(new Debit("shared", 10))));
        if (otherTenant != ProcessResult.APPLIED || accounts.balance("shared") != 80) {
            failures.add("request identity was not tenant scoped");
        }

        if (!failures.isEmpty()) {
            throw new AssertionError(String.join("; ", failures));
        }
    }
}
""".replace("__CONSTRUCTOR__", constructor),
        encoding="utf-8",
    )
    classes = tmp_path / "batch-retry-classes"
    classes.mkdir()
    sources = sorted(source_root.rglob("*.java"))
    compiled = subprocess.run(  # nosec B603 - fixed executable and local paths
        [javac, "-d", str(classes), *(str(path) for path in sources), str(harness)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert compiled.returncode == 0, compiled.stderr
    return subprocess.run(  # nosec B603 - fixed executable and local class
        [java, "-cp", str(classes), "edu.tum.payments.BatchRetryHarness"],
        capture_output=True,
        text=True,
        check=False,
    )


def test_batch_retry_reference_solution_satisfies_the_hidden_contract(tmp_path):
    source_root = (
        QA_ROOT
        / "artifacts/advanced/batch-retry/solution/src/main/java/edu/tum/payments"
    )

    completed = _compile_and_run_batch_retry(
        source_root, tmp_path, student_snapshot=False
    )

    assert completed.returncode == 0, completed.stderr


def test_batch_retry_latest_snapshot_reproduces_hidden_failures(tmp_path):
    source_root = (
        QA_ROOT
        / "artifacts/advanced/batch-retry/student/latest/src/main/java/edu/tum/payments"
    )

    completed = _compile_and_run_batch_retry(
        source_root, tmp_path, student_snapshot=True
    )

    assert completed.returncode != 0
    assert "failed batch was not atomic" in completed.stderr
    assert "retry repeated a debit from the failed attempt" in completed.stderr
    assert "request identity was not tenant scoped" in completed.stderr


def test_batch_retry_first_attempt_is_complete_and_reproduces_failures(tmp_path):
    source_root = (
        QA_ROOT
        / "artifacts/advanced/batch-retry/student/first-attempt/src/main/java/edu/tum/payments"
    )

    completed = _compile_and_run_batch_retry(
        source_root, tmp_path, student_snapshot=False
    )

    assert completed.returncode != 0
    assert "failed batch was not atomic" in completed.stderr
    assert "retry repeated a debit from the failed attempt" in completed.stderr
    assert "request identity was not tenant scoped" in completed.stderr
