from unittest.mock import Mock, patch

import pytest
import subprocess
import os
import sys
import time
from threading import Thread
from queue import Queue, Empty


def enqueue_output(out, queue):
    for line in iter(out.readline, b''):
        queue.put(line)
    out.close()


@pytest.fixture
def run_module_programming_llm(monkeypatch):
    orig_pythonpath = os.environ.get('PYTHONPATH', '')

    monkeypatch.setenv("DATABASE_URL", "sqlite:///../data/integration_test_data.sqlite")
    monkeypatch.setenv("PRODUCTION", "1")

    # secrets
    monkeypatch.setenv("SECRET", "integration test MODULE_PROGRAMMING_LLM_SECRET")
    monkeypatch.setenv("LLM_DEFAULT_MODEL", "fake_model")

    current_cwd = os.getcwd() # global level Athena
    monkeypatch.setenv('PYTHONPATH', current_cwd + '/tests/integration_tests/integration_tests/mocks:' + os.environ.get('PYTHONPATH', ''))

    poetry_path = os.getenv("POETRY_PATH")
    if poetry_path is None:
        raise EnvironmentError("Set POETRY_PATH environment variable to run the test")

    module_cwd = os.path.join(current_cwd, "modules/programming/module_programming_llm")

    ON_POSIX = 'posix' in sys.builtin_module_names

    process = subprocess.Popen(
        [poetry_path, "run", "python", "-m", "module_programming_llm"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=module_cwd,
        close_fds=ON_POSIX,
        bufsize=1
    )
    queue = Queue()
    # TODO logs are written into the error stream, should be fixed in the future
    thread = Thread(target=enqueue_output, args=(process.stderr, queue))
    thread.daemon = True
    thread.start()

    ready = False
    stderr_output = ""
    for _ in range(5):
        while True:
            try:
                current_output = queue.get_nowait()
            except Empty:
                break
            else:
                if current_output == '':
                    break
                stderr_output = stderr_output + current_output

        if "Application startup complete" in stderr_output:
            ready = True
            break

        time.sleep(1)

    if not ready:
        process.terminate()
        process.wait()
        stderr_output = stderr_output + process.stderr.read()
        raise TimeoutError(f"Module Programming LLM didn't start at time.\nError: {stderr_output}")

    monkeypatch.delenv("DATABASE_URL")
    monkeypatch.delenv("PRODUCTION")
    monkeypatch.delenv("SECRET")
    monkeypatch.delenv("LLM_DEFAULT_MODEL")
    monkeypatch.setenv('PYTHONPATH', orig_pythonpath)

    yield process

    process.terminate()
    process.wait()

