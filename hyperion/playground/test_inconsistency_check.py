#!/usr/bin/env python3
"""
Test script for the inconsistency check functionality.

This script creates a sample programming exercise with intentional inconsistencies
and tests the CheckInconsistencies RPC method.
"""

import asyncio
import grpc
import logging
from typing import List

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from app.grpc import hyperion_pb2, hyperion_pb2_grpc

# Sample data for testing
SAMPLE_PROBLEM_STATEMENT = """
# Binary Search Implementation

Implement a binary search algorithm that finds the index of a target value in a sorted array.

## Requirements:
- Function name: `binary_search`
- Parameters: `arr` (sorted array), `target` (value to find)
- Return: Index of target if found, -1 if not found
- Time complexity: O(log n)

## Example:
```python
arr = [1, 3, 5, 7, 9, 11, 13]
target = 7
result = binary_search(arr, target)  # Should return 3
```
"""

SAMPLE_TEMPLATE_FILES = [
    {
        "path": "binary_search.py",
        "content": """def binary_search(arr, target):
    \"\"\"
    Implement binary search algorithm.
    
    Args:
        arr: Sorted array of integers
        target: Value to search for
        
    Returns:
        Index of target if found, -1 otherwise
    \"\"\"
    # TODO: Implement binary search
    pass
""",
    },
    {
        "path": "test_binary_search.py",
        "content": """import unittest
from binary_search import binary_search

class TestBinarySearch(unittest.TestCase):
    def test_found(self):
        arr = [1, 3, 5, 7, 9, 11, 13]
        self.assertEqual(binary_search(arr, 7), 3)
        
    def test_not_found(self):
        arr = [1, 3, 5, 7, 9, 11, 13]
        self.assertEqual(binary_search(arr, 6), -1)

if __name__ == '__main__':
    unittest.main()
""",
    },
]

SAMPLE_SOLUTION_FILES = [
    {
        "path": "binary_search.py",
        "content": """def binary_search(arr, target):
    \"\"\"
    Binary search implementation.
    
    Args:
        arr: Sorted array of integers
        target: Value to search for
        
    Returns:
        Index of target if found, -1 otherwise
    \"\"\"
    left, right = 0, len(arr) - 1
    
    while left <= right:
        mid = (left + right) // 2
        if arr[mid] == target:
            return mid
        elif arr[mid] < target:
            left = mid + 1
        else:
            right = mid - 1
    
    return -1
""",
    },
    {
        "path": "test_binary_search.py",
        "content": """import unittest
from binary_search import binary_search

class TestBinarySearch(unittest.TestCase):
    def test_found(self):
        arr = [1, 3, 5, 7, 9, 11, 13]
        self.assertEqual(binary_search(arr, 7), 3)
        
    def test_not_found(self):
        arr = [1, 3, 5, 7, 9, 11, 13]
        self.assertEqual(binary_search(arr, 6), -1)
        
    def test_empty_array(self):
        self.assertEqual(binary_search([], 5), -1)
        
    def test_single_element(self):
        self.assertEqual(binary_search([5], 5), 0)
        self.assertEqual(binary_search([5], 3), -1)

if __name__ == '__main__':
    unittest.main()
""",
    },
]


def create_repository_files(file_data: List[dict]) -> List[hyperion_pb2.RepositoryFile]:
    """Create gRPC RepositoryFile objects from file data."""
    return [
        hyperion_pb2.RepositoryFile(
            path=file_info["path"], content=file_info["content"]
        )
        for file_info in file_data
    ]


async def test_inconsistency_check():
    """Test the CheckInconsistencies RPC method."""
    logger.info("Starting inconsistency check test...")

    # Create the request
    template_files = create_repository_files(SAMPLE_TEMPLATE_FILES)
    solution_files = create_repository_files(SAMPLE_SOLUTION_FILES)

    template_repository = hyperion_pb2.Repository(files=template_files)
    solution_repository = hyperion_pb2.Repository(files=solution_files)

    request = hyperion_pb2.InconsistencyCheckRequest(
        problem_statement=SAMPLE_PROBLEM_STATEMENT,
        template_repository=template_repository,
        solution_repository=solution_repository,
        test_repository=hyperion_pb2.Repository(files=[]),  # Empty test repository
    )

    # Create a channel and stub
    channel = grpc.insecure_channel("localhost:50051")
    stub = hyperion_pb2_grpc.ReviewAndRefineStub(channel)

    try:
        # Make the RPC call
        logger.info("Calling CheckInconsistencies...")
        response = stub.CheckInconsistencies(request)

        logger.info("Response received:")
        logger.info(f"Inconsistencies found:\n{response.inconsistencies}")

        return response.inconsistencies

    except grpc.RpcError as e:
        logger.error(f"RPC failed: {e.code()}: {e.details()}")
        return None
    finally:
        channel.close()


async def main():
    """Main test function."""
    logger.info("Testing Hyperion inconsistency check functionality...")

    result = await test_inconsistency_check()

    if result:
        logger.info("Test completed successfully!")
        logger.info(f"Result length: {len(result)} characters")
    else:
        logger.error("Test failed!")

    return result


if __name__ == "__main__":
    asyncio.run(main())
