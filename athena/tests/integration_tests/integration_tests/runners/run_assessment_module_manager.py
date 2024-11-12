from abc import ABC, abstractmethod

import pytest
import subprocess
import os
import sys
import time
from threading import Thread
from queue import Queue, Empty

from langchain_core.language_models import FakeListLLM
from pydantic import BaseModel


class FakeLLMConfig(BaseModel, ABC):

    @abstractmethod
    def get_model(self) -> FakeListLLM:
        pass

def enqueue_output(out, queue):
    for line in iter(out.readline, b''):
        queue.put(line)
    out.close()


@pytest.fixture
def run_assessment_module_manager(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///../data/integration_test_data.sqlite")
    monkeypatch.setenv("PRODUCTION", "1")

    # secrets
    monkeypatch.setenv("LMS_LOCAL_SECRET", "integration test lms local secret")
    monkeypatch.setenv("MODULE_EXAMPLE_SECRET", "integration test MODULE_EXAMPLE_SECRET")
    monkeypatch.setenv("MODULE_PROGRAMMING_LLM_SECRET", "integration test MODULE_PROGRAMMING_LLM_SECRET")
    monkeypatch.setenv("MODULE_TEXT_LLM_SECRET", "integration test MODULE_TEXT_LLM_SECRET")
    monkeypatch.setenv("MODULE_TEXT_COFEE_SECRET", "integration test MODULE_TEXT_COFEE_SECRET")
    monkeypatch.setenv("MODULE_PROGRAMMING_THEMISML_SECRET", "integration test MODULE_PROGRAMMING_THEMISML_SECRET")
    monkeypatch.setenv("MODULE_PROGRAMMING_APTED_SECRET", "integration test MODULE_PROGRAMMING_APTED_SECRET")
    monkeypatch.setenv("MODULE_MODELING_LLM_SECRET", "integration test MODULE_MODELING_LLM_SECRET")

    poetry_path = os.getenv("POETRY_PATH")
    if poetry_path is None:
        raise EnvironmentError("Set POETRY_PATH environment variable to run the test")

    current_cwd = os.getcwd()
    module_cwd = os.path.join(current_cwd, "assessment_module_manager")

    ON_POSIX = 'posix' in sys.builtin_module_names

    process = subprocess.Popen(
        [poetry_path, "run", "python", "-m", "assessment_module_manager"],
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
                stderr_output = stderr_output + current_output

        if "Application startup complete" in stderr_output:
            ready = True
            break

        time.sleep(1)

    if not ready:
        process.terminate()
        process.wait()
        stderr_output = stderr_output + process.stderr.read()
        raise TimeoutError(f"Assessment Module Manager didn't start at time.\nError: {stderr_output}")

    monkeypatch.delenv("DATABASE_URL")
    monkeypatch.delenv("PRODUCTION")
    monkeypatch.delenv("LMS_LOCAL_SECRET")
    monkeypatch.delenv("MODULE_EXAMPLE_SECRET")
    monkeypatch.delenv("MODULE_PROGRAMMING_LLM_SECRET")
    monkeypatch.delenv("MODULE_TEXT_LLM_SECRET")
    monkeypatch.delenv("MODULE_TEXT_COFEE_SECRET")
    monkeypatch.delenv("MODULE_PROGRAMMING_THEMISML_SECRET")
    monkeypatch.delenv("MODULE_PROGRAMMING_APTED_SECRET")
    monkeypatch.delenv("MODULE_MODELING_LLM_SECRET")

    yield process

    process.terminate()
    process.wait()
