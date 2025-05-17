#!/usr/bin/env python
"""
Script to test the inconsistency checking functionality.

Usage:
    cd hyperion
    poetry run python playground/test_inconsistency_check.py
"""

import sys
import grpc
import time
from pathlib import Path

# Add the project root to the path so we can import app modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.grpc import hyperion_pb2, hyperion_pb2_grpc
from app.grpc.models import Repository, RepositoryFile


def main():
    """Test the VerifyConfiguration service by sending an InconsistencyCheckRequest."""
    print("Testing inconsistency checking functionality...")

    channel = grpc.insecure_channel("localhost:50051")
    stub = hyperion_pb2_grpc.VerifyConfigurationStub(channel)

    # Create a simple test case with a problem statement and inconsistent files
    problem_statement = """
    # Exercise: Calculator

    In this exercise, you need to implement a simple calculator that supports addition, subtraction, multiplication,
    and division.
    """

    template_files = [
        RepositoryFile(
            path="calculator.py",
            content="""
            class Calculator:
                def add(self, a, b):
                    pass

                def subtract(self, a, b):
                    pass

                def multiply(self, a, b):
                    pass

                # Division method is missing
            """,
        )
    ]

    solution_files = [
        RepositoryFile(
            path="calculator.py",
            content="""
            class Calculator:
                def add(self, a, b):
                    return a + b

                def subtract(self, a, b):
                    return a - b

                def multiply(self, a, b):
                    return a * b

                def divide(self, a, b):
                    if b == 0:
                        raise ValueError("Cannot divide by zero")
                    return a / b
            """,
        )
    ]

    # Create repositories
    template_repo = Repository(files=template_files)
    solution_repo = Repository(files=solution_files)
    test_repo = Repository(files=[])  # Empty for now

    # Create request
    request = hyperion_pb2.InconsistencyCheckRequest(
        problem_statement=problem_statement,
        solution_repository=solution_repo.to_grpc(),
        template_repository=template_repo.to_grpc(),
        test_repository=test_repo.to_grpc(),
    )

    try:
        # Send request
        print("Sending inconsistency check request...")
        start_time = time.time()
        response = stub.CheckInconsistencies(request)
        elapsed = time.time() - start_time

        print(f"Response received in {elapsed:.2f} seconds")
        print("Inconsistencies found:")
        print("-" * 50)
        print(response.inconsistencies)
        print("-" * 50)

        return 0
    except grpc.RpcError as e:
        print(f"RPC failed: {e.code()} - {e.details()}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
