"""
Integration test for Step 3 Solution Repository Creator.

Run with:
    pytest -s app/creation_steps/step3_create_solution_repository/tests/integration.py

"""

import pytest
import tempfile
import shutil
from unittest.mock import Mock, AsyncMock, patch
from pathlib import Path
import sys

# Add project root to path for imports
project_root = Path(__file__).parent.parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from app.creation_steps.step3_create_solution_repository.servicer import (
    SolutionRepositoryCreatorServicer,
)
from langchain_core.language_models.chat_models import BaseLanguageModel


class TestSolutionRepositoryCreatorIntegration:
    """Integration test for the complete solution repository creation flow."""

    @pytest.fixture
    def mock_model(self):
        """Create a mock AI model with predefined responses for each step."""
        model = Mock(spec=BaseLanguageModel)

        mock_responses = {
            # Step 1.1: Solution Plan (JSON response)
            "solution_plan": """{
                "architecture_description": "A simple binary search implementation with input validation and comprehensive testing. The solution follows a modular approach with separate functions for validation and the core search algorithm.",
                "required_classes": ["BinarySearchSolution"],
                "required_functions": ["binary_search", "validate_input", "main"],
                "algorithms": ["Binary Search", "Input Validation"],
                "design_patterns": ["Guard Clause Pattern", "Single Responsibility Principle"]
            }""",
            # Step 1.2: File Structure (JSON response)
            "file_structure": """{
                "directories": ["src", "tests"],
                "files": ["src/binary_search.py", "tests/test_binary_search.py"],
                "build_files": ["requirements.txt"]
            }""",
            # Step 1.3: Headers for binary_search.py
            "headers_binary_search": '''
                """
                Binary Search Implementation

                This module provides a binary search algorithm implementation
                with proper input validation and error handling.
                """
                from typing import List, Optional


                class BinarySearchSolution:
                    """Binary search algorithm implementation."""
                    
                    def __init__(self):
                        """Initialize the binary search solution."""
                        pass
                    
                    def binary_search(self, arr: List[int], target: int) -> int:
                        """
                        Perform binary search on a sorted array.
                        
                        Args:
                            arr: Sorted list of integers
                            target: Target value to search for
                            
                        Returns:
                            Index of target if found, -1 otherwise
                        """
                        # TODO: Implement binary search logic
                        pass
                    
                    def validate_input(self, arr: List[int]) -> bool:
                        """
                        Validate input array for binary search.
                        
                        Args:
                            arr: Array to validate
                            
                        Returns:
                            True if valid, False otherwise
                        """
                        # TODO: Implement input validation
                        pass


                def main():
                    """Main function for testing the binary search implementation."""
                    # TODO: Implement main logic
                    pass


                if __name__ == "__main__":
                    main()
            ''',
            # Step 1.3: Headers for test_binary_search.py
            "headers_test": '''
                """
                Test module for binary search implementation.
                """
                import unittest
                from src.binary_search import BinarySearchSolution


                class TestBinarySearch(unittest.TestCase):
                    """Test cases for binary search implementation."""
                    
                    def setUp(self):
                        """Set up test fixtures."""
                        # TODO: Initialize test fixtures
                        pass
                    
                    def test_binary_search_found(self):
                        """Test binary search when target is found."""
                        # TODO: Implement test case
                        pass
                    
                    def test_binary_search_not_found(self):
                        """Test binary search when target is not found."""
                        # TODO: Implement test case
                        pass
                    
                    def test_empty_array(self):
                        """Test binary search with empty array."""
                        # TODO: Implement test case
                        pass
                    
                    def test_single_element(self):
                        """Test binary search with single element array."""
                        # TODO: Implement test case
                        pass


                if __name__ == "__main__":
                    unittest.main()
            ''',
            # Step 1.4: Implementation for binary_search.py
            "implementation_binary_search": '''"""
                Binary Search Implementation

                This module provides a binary search algorithm implementation
                with proper input validation and error handling.
                """
                from typing import List, Optional


                class BinarySearchSolution:
                    """Binary search algorithm implementation."""
                    
                    def __init__(self):
                        """Initialize the binary search solution."""
                        pass
                    
                    def binary_search(self, arr: List[int], target: int) -> int:
                        """
                        Perform binary search on a sorted array.
                        
                        Args:
                            arr: Sorted list of integers
                            target: Target value to search for
                            
                        Returns:
                            Index of target if found, -1 otherwise
                        """
                        if not self.validate_input(arr):
                            return -1
                        
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
                    
                    def validate_input(self, arr: List[int]) -> bool:
                        """
                        Validate input array for binary search.
                        
                        Args:
                            arr: Array to validate
                            
                        Returns:
                            True if valid, False otherwise
                        """
                        if not isinstance(arr, list):
                            return False
                        
                        if len(arr) == 0:
                            return True  # Empty array is valid
                        
                        # Check if array is sorted
                        for i in range(1, len(arr)):
                            if arr[i] < arr[i-1]:
                                return False
                        
                        return True


                def main():
                    """Main function for testing the binary search implementation."""
                    solution = BinarySearchSolution()
                    
                    # Test cases
                    test_array = [1, 3, 5, 7, 9, 11, 13, 15]
                    
                    print("Binary Search Implementation Test")
                    print("Array:", test_array)
                    
                    # Test existing element
                    target = 7
                    result = solution.binary_search(test_array, target)
                    print(f"Search for {target}: Index {result}")
                    
                    # Test non-existing element
                    target = 6
                    result = solution.binary_search(test_array, target)
                    print(f"Search for {target}: Index {result}")
                    
                    # Test edge cases
                    print("\\nEdge case tests:")
                    print("Empty array:", solution.binary_search([], 5))
                    print("Single element (found):", solution.binary_search([5], 5))
                    print("Single element (not found):", solution.binary_search([5], 3))


                if __name__ == "__main__":
                    main()
                ''',
            # Step 1.4: Implementation for test_binary_search.py
            "implementation_test": '''
                    """
                    Test module for binary search implementation.
                    """
                    import unittest
                    from src.binary_search import BinarySearchSolution


                    class TestBinarySearch(unittest.TestCase):
                        """Test cases for binary search implementation."""
                        
                        def setUp(self):
                            """Set up test fixtures."""
                            self.solution = BinarySearchSolution()
                            self.sorted_array = [1, 3, 5, 7, 9, 11, 13, 15]
                        
                        def test_binary_search_found(self):
                            """Test binary search when target is found."""
                            result = self.solution.binary_search(self.sorted_array, 7)
                            self.assertEqual(result, 3)
                            
                            result = self.solution.binary_search(self.sorted_array, 1)
                            self.assertEqual(result, 0)
                            
                            result = self.solution.binary_search(self.sorted_array, 15)
                            self.assertEqual(result, 7)
                        
                        def test_binary_search_not_found(self):
                            """Test binary search when target is not found."""
                            result = self.solution.binary_search(self.sorted_array, 6)
                            self.assertEqual(result, -1)
                            
                            result = self.solution.binary_search(self.sorted_array, 0)
                            self.assertEqual(result, -1)
                            
                            result = self.solution.binary_search(self.sorted_array, 20)
                            self.assertEqual(result, -1)
                        
                        def test_empty_array(self):
                            """Test binary search with empty array."""
                            result = self.solution.binary_search([], 5)
                            self.assertEqual(result, -1)
                        
                        def test_single_element(self):
                            """Test binary search with single element array."""
                            result = self.solution.binary_search([5], 5)
                            self.assertEqual(result, 0)
                            
                            result = self.solution.binary_search([5], 3)
                            self.assertEqual(result, -1)
                        
                        def test_validate_input(self):
                            """Test input validation function."""
                            # Valid inputs
                            self.assertTrue(self.solution.validate_input([]))
                            self.assertTrue(self.solution.validate_input([1]))
                            self.assertTrue(self.solution.validate_input([1, 2, 3, 4, 5]))
                            
                            # Invalid inputs
                            self.assertFalse(self.solution.validate_input([5, 3, 1]))  # Not sorted
                            self.assertFalse(self.solution.validate_input("not a list"))  # Wrong type


                    if __name__ == "__main__":
                        unittest.main()
                ''',
        }

        # Track call count to return appropriate response
        call_count = 0

        async def mock_ainvoke(prompt):
            nonlocal call_count
            call_count += 1

            response = Mock()

            # Determine which response to return based on prompt content
            prompt_str = str(prompt).lower()

            print(f"\n🔍 LLM Call #{call_count}:")
            print(
                f"  Prompt contains: {[key for key in ['solution plan', 'architecture', 'file structure', 'directories', 'binary_search.py', 'test_binary_search.py', 'headers', 'no implementation'] if key in prompt_str]}"
            )

            # Use more specific matching based on the actual prompt content
            if "generate the complete header structure" in prompt_str.lower():
                if "binary_search.py" in prompt_str:
                    response.content = mock_responses["headers_binary_search"]
                    print(f"  → Returning: headers_binary_search")
                elif "test_binary_search.py" in prompt_str:
                    response.content = mock_responses["headers_test"]
                    print(f"  → Returning: headers_test")
                else:
                    response.content = mock_responses[
                        "headers_binary_search"
                    ]  # Default
                    print(f"  → Returning: headers_binary_search (default)")
            elif "generate the complete implementation" in prompt_str.lower():
                if "binary_search.py" in prompt_str:
                    response.content = mock_responses["implementation_binary_search"]
                    print(f"  → Returning: implementation_binary_search")
                elif "test_binary_search.py" in prompt_str:
                    response.content = mock_responses["implementation_test"]
                    print(f"  → Returning: implementation_test")
                else:
                    response.content = mock_responses[
                        "implementation_binary_search"
                    ]  # Default
                    print(f"  → Returning: implementation_binary_search (default)")
            elif (
                "file structure" in prompt_str or "directories" in prompt_str
            ) and "generate the complete" not in prompt_str.lower():
                response.content = mock_responses["file_structure"]
                print(f"  → Returning: file_structure")
                print(
                    f"  📄 File structure JSON: {mock_responses['file_structure'][:200]}..."
                )
            elif "solution plan" in prompt_str or "architecture" in prompt_str:
                response.content = mock_responses["solution_plan"]
                print(f"  → Returning: solution_plan")
            else:
                # Default response
                response.content = '{"default": "response"}'
                print(f"  → Returning: default response")

            return response

        model.ainvoke = AsyncMock(side_effect=mock_ainvoke)
        return model

    @pytest.fixture
    def mock_request(self):
        """Create a mock gRPC request."""
        # Create boundary conditions
        boundary_conditions = Mock()
        boundary_conditions.programming_language = 2  # PYTHON
        boundary_conditions.project_type = 0  # PLAIN
        boundary_conditions.difficulty = "Medium"
        boundary_conditions.points = 100
        boundary_conditions.bonus_points = 0
        boundary_conditions.constraints = []

        # Create problem statement
        problem_statement = Mock()
        problem_statement.title = "Binary Search Implementation"
        problem_statement.short_title = "Binary Search"
        problem_statement.description = "Implement a binary search algorithm that can efficiently find elements in a sorted array. The implementation should include proper input validation and handle edge cases like empty arrays and single-element arrays."

        # Create request
        request = Mock()
        request.boundary_conditions = boundary_conditions
        request.problem_statement = problem_statement

        return request

    @pytest.fixture
    def temp_workspace(self):
        """Create a temporary workspace directory."""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        # Cleanup after test
        shutil.rmtree(temp_dir, ignore_errors=True)

    @pytest.mark.asyncio
    async def test_complete_solution_repository_creation(
        self, mock_model, mock_request, temp_workspace
    ):
        """Test the complete integration flow from request to response."""

        # Mock the workspace manager instance that will be used
        mock_workspace_instance = Mock()
        mock_workspace_instance.create_workspace.return_value = temp_workspace
        mock_workspace_instance.cleanup_workspace.return_value = None

        # Mock the language registry to support Python
        with patch(
            "hyperion.app.creation_steps.step3_create_solution_repository.servicer.language_registry"
        ) as mock_registry:
            mock_registry.is_supported.return_value = True

            # Mock the config
            with patch(
                "hyperion.app.creation_steps.step3_create_solution_repository.servicer.config"
            ) as mock_config:
                mock_config.solution_creator_max_iterations = 5
                mock_config.cleanup_on_success = True
                mock_config.cleanup_on_failure = False

                # Create servicer with the real CodeGenerator and mocked model
                servicer = SolutionRepositoryCreatorServicer(model=mock_model)

                # Now, after instantiation, we patch the instance's manager
                servicer.workspace_manager = mock_workspace_instance

                # Mock gRPC context
                grpc_context = Mock()

                # Execute the service
                response: hyperion_pb2.SolutionRepositoryCreatorResponse = (
                    await servicer.CreateSolutionRepository(mock_request, grpc_context)
                )

                # Verify the response structure
                assert response is not None
                assert response.solution_repository is not None

                print(f"\nWorkspace path: {temp_workspace}")

                for repository in response.solution_repository.files:
                    print(f"\nRepository file: {repository.path}")
                    print(f"Content: {repository.content}\n")

                # Verify that files were created in the workspace
                workspace_path = Path(temp_workspace)
                assert (workspace_path / "src").is_dir()
                assert (workspace_path / "tests").is_dir()
                assert (workspace_path / "src" / "binary_search.py").exists()
                assert (workspace_path / "tests" / "test_binary_search.py").exists()
                assert (workspace_path / "requirements.txt").exists()

                # Verify file contents are not empty
                binary_search_content = (
                    workspace_path / "src" / "binary_search.py"
                ).read_text()
                assert len(binary_search_content) > 50
                test_content = (
                    workspace_path / "tests" / "test_binary_search.py"
                ).read_text()
                assert len(test_content) > 50

                # Verify that the model was called the expected number of times
                assert (
                    mock_model.ainvoke.call_count >= 4
                )  # Plan, Structure, Headers, Implementation

    @pytest.mark.asyncio
    async def test_error_handling_invalid_language(
        self, mock_model, mock_request, temp_workspace
    ):
        """Test error handling when an unsupported language is specified."""

        # Modify request to use unsupported language
        mock_request.boundary_conditions.programming_language = 999  # Invalid language

        with patch(
            "hyperion.app.creation_steps.step3_create_solution_repository.servicer.TempWorkspaceManager"
        ) as mock_workspace_manager:
            mock_workspace_instance = Mock()
            mock_workspace_instance.create_workspace.return_value = temp_workspace
            mock_workspace_manager.return_value = mock_workspace_instance

            # Mock language registry to reject the language
            with patch(
                "hyperion.app.creation_steps.step3_create_solution_repository.servicer.language_registry"
            ) as mock_registry:
                mock_registry.is_supported.return_value = False
                mock_registry.get_supported_languages.return_value = ["PYTHON", "JAVA"]

                servicer = SolutionRepositoryCreatorServicer(model=mock_model)
                grpc_context = Mock()

                # Should raise an exception
                with pytest.raises(Exception):
                    await servicer.CreateSolutionRepository(mock_request, grpc_context)

                # Verify gRPC context was set with error
                grpc_context.set_code.assert_called()
                grpc_context.set_details.assert_called()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
