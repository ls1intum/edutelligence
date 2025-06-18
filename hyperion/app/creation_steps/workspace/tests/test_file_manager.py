"""Unit tests for FileManager class."""

# python -m pytest test_file_manager.py

import os
import tempfile
import shutil
import pytest
from pathlib import Path
from unittest.mock import Mock, patch, mock_open
import stat

import sys
from pathlib import Path

# Add project root to path for imports
project_root = Path(__file__).parent.parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from app.creation_steps.workspace.file_manager import FileManager
from app.creation_steps.step3_create_solution_repository.models import (
    SolutionCreationContext,
    FileStructure,
)
from app.creation_steps.exceptions import FileSystemException


class TestFileManager:
    """Test suite for FileManager class."""

    @pytest.fixture
    def file_manager(self):
        """Create a FileManager instance for testing."""
        return FileManager()

    @pytest.fixture
    def temp_workspace(self):
        """Create a temporary workspace directory for testing."""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        # Cleanup after test
        shutil.rmtree(temp_dir, ignore_errors=True)

    @pytest.fixture
    def mock_context(self, temp_workspace):
        """Create a mock SolutionCreationContext with temporary workspace."""
        context = Mock(spec=SolutionCreationContext)
        context.workspace_path = temp_workspace
        return context

    def test_init(self, file_manager):
        """Test FileManager initialization."""
        assert file_manager.encoding == "utf-8"

    def test_write_file_success(self, file_manager, mock_context):
        """Test successful file writing."""
        content = "Hello, World!"
        file_path = "test.txt"

        file_manager.write_file(mock_context, file_path, content)

        # Verify file was created with correct content
        full_path = Path(mock_context.workspace_path) / file_path
        assert full_path.exists()
        assert full_path.read_text(encoding="utf-8") == content

    def test_write_file_with_subdirectory(self, file_manager, mock_context):
        """Test writing file in subdirectory (should create parent dirs)."""
        content = "Test content"
        file_path = "subdir/nested/test.txt"

        file_manager.write_file(mock_context, file_path, content)

        full_path = Path(mock_context.workspace_path) / file_path
        assert full_path.exists()
        assert full_path.read_text(encoding="utf-8") == content
        assert full_path.parent.exists()

    def test_write_file_empty_path(self, file_manager, mock_context):
        """Test writing file with empty path raises exception."""
        with pytest.raises(FileSystemException, match="File path cannot be empty"):
            file_manager.write_file(mock_context, "", "content")

    def test_write_file_invalid_workspace(self, file_manager):
        """Test writing file with invalid workspace path."""
        context = Mock()
        context.workspace_path = "/nonexistent/path"

        with pytest.raises(FileSystemException):
            file_manager.write_file(context, "test.txt", "content")

    def test_read_file_success(self, file_manager, mock_context):
        """Test successful file reading."""
        content = "Test file content"
        file_path = "test.txt"

        # Create file first
        full_path = Path(mock_context.workspace_path) / file_path
        full_path.write_text(content, encoding="utf-8")

        # Read file
        result = file_manager.read_file(mock_context, file_path)
        assert result == content

    def test_read_file_not_exists(self, file_manager, mock_context):
        """Test reading non-existent file raises exception."""
        with pytest.raises(FileSystemException, match="File does not exist"):
            file_manager.read_file(mock_context, "nonexistent.txt")

    def test_read_file_is_directory(self, file_manager, mock_context):
        """Test reading directory instead of file raises exception."""
        dir_path = "testdir"
        full_path = Path(mock_context.workspace_path) / dir_path
        full_path.mkdir()

        with pytest.raises(FileSystemException, match="Path is not a file"):
            file_manager.read_file(mock_context, dir_path)

    def test_read_file_empty_path(self, file_manager, mock_context):
        """Test reading file with empty path raises exception."""
        with pytest.raises(FileSystemException, match="File path cannot be empty"):
            file_manager.read_file(mock_context, "")

    def test_copy_file_success(self, file_manager, mock_context):
        """Test successful file copying."""
        content = "Original content"
        source_path = "source.txt"
        dest_path = "destination.txt"

        # Create source file
        source_full = Path(mock_context.workspace_path) / source_path
        source_full.write_text(content, encoding="utf-8")

        # Copy file
        file_manager.copy_file(mock_context, source_path, dest_path)

        # Verify both files exist with same content
        dest_full = Path(mock_context.workspace_path) / dest_path
        assert source_full.exists()
        assert dest_full.exists()
        assert dest_full.read_text(encoding="utf-8") == content

    def test_copy_file_with_subdirectory(self, file_manager, mock_context):
        """Test copying file to subdirectory (should create parent dirs)."""
        content = "Test content"
        source_path = "source.txt"
        dest_path = "subdir/destination.txt"

        # Create source file
        source_full = Path(mock_context.workspace_path) / source_path
        source_full.write_text(content, encoding="utf-8")

        # Copy file
        file_manager.copy_file(mock_context, source_path, dest_path)

        dest_full = Path(mock_context.workspace_path) / dest_path
        assert dest_full.exists()
        assert dest_full.read_text(encoding="utf-8") == content

    def test_copy_file_source_not_exists(self, file_manager, mock_context):
        """Test copying non-existent source file raises exception."""
        with pytest.raises(FileSystemException, match="Source file does not exist"):
            file_manager.copy_file(mock_context, "nonexistent.txt", "dest.txt")

    def test_copy_file_source_is_directory(self, file_manager, mock_context):
        """Test copying directory instead of file raises exception."""
        dir_path = "testdir"
        full_path = Path(mock_context.workspace_path) / dir_path
        full_path.mkdir()

        with pytest.raises(FileSystemException, match="Source path is not a file"):
            file_manager.copy_file(mock_context, dir_path, "dest.txt")

    def test_copy_file_empty_paths(self, file_manager, mock_context):
        """Test copying with empty paths raises exception."""
        with pytest.raises(
            FileSystemException, match="Source and destination paths cannot be empty"
        ):
            file_manager.copy_file(mock_context, "", "dest.txt")

        with pytest.raises(
            FileSystemException, match="Source and destination paths cannot be empty"
        ):
            file_manager.copy_file(mock_context, "source.txt", "")

    def test_move_file_success(self, file_manager, mock_context):
        """Test successful file moving."""
        content = "Original content"
        source_path = "source.txt"
        dest_path = "destination.txt"

        # Create source file
        source_full = Path(mock_context.workspace_path) / source_path
        source_full.write_text(content, encoding="utf-8")

        # Move file
        file_manager.move_file(mock_context, source_path, dest_path)

        # Verify source is gone and destination exists
        dest_full = Path(mock_context.workspace_path) / dest_path
        assert not source_full.exists()
        assert dest_full.exists()
        assert dest_full.read_text(encoding="utf-8") == content

    def test_move_file_source_not_exists(self, file_manager, mock_context):
        """Test moving non-existent source file raises exception."""
        with pytest.raises(FileSystemException, match="Source file does not exist"):
            file_manager.move_file(mock_context, "nonexistent.txt", "dest.txt")

    def test_delete_file_success(self, file_manager, mock_context):
        """Test successful file deletion."""
        file_path = "test.txt"
        full_path = Path(mock_context.workspace_path) / file_path
        full_path.write_text("content", encoding="utf-8")

        assert full_path.exists()
        file_manager.delete_file(mock_context, file_path)
        assert not full_path.exists()

    def test_delete_file_not_exists(self, file_manager, mock_context):
        """Test deleting non-existent file (should not raise exception)."""
        # Should not raise exception, just log warning
        file_manager.delete_file(mock_context, "nonexistent.txt")

    def test_delete_file_is_directory(self, file_manager, mock_context):
        """Test deleting directory instead of file raises exception."""
        dir_path = "testdir"
        full_path = Path(mock_context.workspace_path) / dir_path
        full_path.mkdir()

        with pytest.raises(
            FileSystemException, match="Path is a directory, not a file"
        ):
            file_manager.delete_file(mock_context, dir_path)

    def test_delete_file_empty_path(self, file_manager, mock_context):
        """Test deleting file with empty path raises exception."""
        with pytest.raises(FileSystemException, match="File path cannot be empty"):
            file_manager.delete_file(mock_context, "")

    def test_create_directory_success(self, file_manager, mock_context):
        """Test successful directory creation."""
        dir_path = "testdir"
        file_manager.create_directory(mock_context, dir_path)

        full_path = Path(mock_context.workspace_path) / dir_path
        assert full_path.exists()
        assert full_path.is_dir()

    def test_create_directory_nested(self, file_manager, mock_context):
        """Test creating nested directory structure."""
        dir_path = "parent/child/grandchild"
        file_manager.create_directory(mock_context, dir_path)

        full_path = Path(mock_context.workspace_path) / dir_path
        assert full_path.exists()
        assert full_path.is_dir()

    def test_create_directory_already_exists(self, file_manager, mock_context):
        """Test creating directory that already exists (should not fail)."""
        dir_path = "testdir"
        full_path = Path(mock_context.workspace_path) / dir_path
        full_path.mkdir()

        # Should not raise exception
        file_manager.create_directory(mock_context, dir_path)
        assert full_path.exists()

    def test_create_directory_empty_path(self, file_manager, mock_context):
        """Test creating directory with empty path raises exception."""
        with pytest.raises(FileSystemException, match="Directory path cannot be empty"):
            file_manager.create_directory(mock_context, "")

    def test_list_files_success(self, file_manager, mock_context):
        """Test successful file listing."""
        # Create some files and directories
        workspace = Path(mock_context.workspace_path)
        (workspace / "file1.txt").write_text("content1")
        (workspace / "file2.txt").write_text("content2")
        (workspace / "subdir").mkdir()

        files = file_manager.list_files(mock_context, "")

        assert len(files) == 3
        assert "file1.txt" in files
        assert "file2.txt" in files
        assert "subdir" in files
        assert files == sorted(files)  # Should be sorted

    def test_list_files_subdirectory(self, file_manager, mock_context):
        """Test listing files in subdirectory."""
        # Create subdirectory with files
        workspace = Path(mock_context.workspace_path)
        subdir = workspace / "subdir"
        subdir.mkdir()
        (subdir / "file1.txt").write_text("content1")
        (subdir / "file2.txt").write_text("content2")

        files = file_manager.list_files(mock_context, "subdir")

        assert len(files) == 2
        assert "file1.txt" in files
        assert "file2.txt" in files

    def test_list_files_empty_directory(self, file_manager, mock_context):
        """Test listing files in empty directory."""
        files = file_manager.list_files(mock_context, "")
        assert files == []

    def test_list_files_directory_not_exists(self, file_manager, mock_context):
        """Test listing files in non-existent directory raises exception."""
        with pytest.raises(FileSystemException, match="Directory does not exist"):
            file_manager.list_files(mock_context, "nonexistent")

    def test_list_files_path_is_file(self, file_manager, mock_context):
        """Test listing files on a file path raises exception."""
        file_path = "test.txt"
        full_path = Path(mock_context.workspace_path) / file_path
        full_path.write_text("content")

        with pytest.raises(FileSystemException, match="Path is not a directory"):
            file_manager.list_files(mock_context, file_path)

    def test_file_exists_true(self, file_manager, mock_context):
        """Test file_exists returns True for existing file."""
        file_path = "test.txt"
        full_path = Path(mock_context.workspace_path) / file_path
        full_path.write_text("content")

        assert file_manager.file_exists(mock_context, file_path) is True

    def test_file_exists_false(self, file_manager, mock_context):
        """Test file_exists returns False for non-existent file."""
        assert file_manager.file_exists(mock_context, "nonexistent.txt") is False

    def test_file_exists_directory(self, file_manager, mock_context):
        """Test file_exists returns False for directory."""
        dir_path = "testdir"
        full_path = Path(mock_context.workspace_path) / dir_path
        full_path.mkdir()

        assert file_manager.file_exists(mock_context, dir_path) is False

    def test_file_exists_empty_path(self, file_manager, mock_context):
        """Test file_exists returns False for empty path."""
        assert file_manager.file_exists(mock_context, "") is False

    def test_get_file_size_success(self, file_manager, mock_context):
        """Test successful file size retrieval."""
        content = "Hello, World!"
        file_path = "test.txt"
        full_path = Path(mock_context.workspace_path) / file_path
        full_path.write_text(content, encoding="utf-8")

        size = file_manager.get_file_size(mock_context, file_path)
        assert size == len(content.encode("utf-8"))

    def test_get_file_size_not_exists(self, file_manager, mock_context):
        """Test getting size of non-existent file raises exception."""
        with pytest.raises(FileSystemException, match="File does not exist"):
            file_manager.get_file_size(mock_context, "nonexistent.txt")

    def test_get_file_size_directory(self, file_manager, mock_context):
        """Test getting size of directory raises exception."""
        dir_path = "testdir"
        full_path = Path(mock_context.workspace_path) / dir_path
        full_path.mkdir()

        with pytest.raises(FileSystemException, match="Path is not a file"):
            file_manager.get_file_size(mock_context, dir_path)

    def test_get_file_size_empty_path(self, file_manager, mock_context):
        """Test getting size with empty path raises exception."""
        with pytest.raises(FileSystemException, match="File path cannot be empty"):
            file_manager.get_file_size(mock_context, "")

    @pytest.mark.skipif(os.name == "nt", reason="Permissions not supported on Windows")
    def test_set_file_permissions_success(self, file_manager, mock_context):
        """Test successful file permission setting (Unix only)."""
        file_path = "test.txt"
        full_path = Path(mock_context.workspace_path) / file_path
        full_path.write_text("content")

        file_manager.set_file_permissions(mock_context, file_path, 0o644)

        # Check permissions were set
        stat_info = full_path.stat()
        assert stat_info.st_mode & 0o777 == 0o644

    @pytest.mark.skipif(os.name != "nt", reason="Windows-specific test")
    def test_set_file_permissions_windows_skip(self, file_manager, mock_context):
        """Test file permission setting is skipped on Windows."""
        file_path = "test.txt"
        full_path = Path(mock_context.workspace_path) / file_path
        full_path.write_text("content")

        # Should not raise exception on Windows
        file_manager.set_file_permissions(mock_context, file_path, 0o644)

    def test_set_file_permissions_not_exists(self, file_manager, mock_context):
        """Test setting permissions on non-existent file raises exception."""
        with pytest.raises(FileSystemException, match="File does not exist"):
            file_manager.set_file_permissions(mock_context, "nonexistent.txt", 0o644)

    def test_set_file_permissions_empty_path(self, file_manager, mock_context):
        """Test setting permissions with empty path raises exception."""
        with pytest.raises(FileSystemException, match="File path cannot be empty"):
            file_manager.set_file_permissions(mock_context, "", 0o644)

    def test_create_file_structure_success(self, file_manager, mock_context):
        """Test successful file structure creation."""
        structure = Mock(spec=FileStructure)
        structure.directories = ["src", "tests", "docs"]
        structure.files = [
            {"path": "src/main.py", "content": "print('Hello')"},
            {"path": "tests/test_main.py", "content": "import unittest"},
            "README.md",  # File without content
        ]
        structure.build_files = [
            {"path": "requirements.txt", "content": "pytest==7.0.0"},
            "setup.py",  # Build file without content
        ]

        file_manager.create_file_structure(mock_context, structure)

        workspace = Path(mock_context.workspace_path)

        # Check directories
        assert (workspace / "src").is_dir()
        assert (workspace / "tests").is_dir()
        assert (workspace / "docs").is_dir()

        # Check files with content
        assert (workspace / "src/main.py").read_text() == "print('Hello')"
        assert (workspace / "tests/test_main.py").read_text() == "import unittest"
        assert (workspace / "README.md").exists()

        # Check build files
        assert (workspace / "requirements.txt").read_text() == "pytest==7.0.0"
        assert (workspace / "setup.py").exists()

    def test_create_file_structure_empty(self, file_manager, mock_context):
        """Test creating empty file structure."""
        structure = Mock(spec=FileStructure)
        structure.directories = None
        structure.files = None
        structure.build_files = None

        # Should not raise exception
        file_manager.create_file_structure(mock_context, structure)

    def test_resolve_workspace_path_success(self, file_manager, mock_context):
        """Test successful workspace path resolution."""
        relative_path = "subdir/file.txt"
        result = file_manager._resolve_workspace_path(mock_context, relative_path)

        expected = Path(mock_context.workspace_path).resolve() / relative_path
        assert result == expected.resolve()

    def test_resolve_workspace_path_empty_relative(self, file_manager, mock_context):
        """Test resolving empty relative path returns workspace root."""
        result = file_manager._resolve_workspace_path(mock_context, "")
        expected = Path(mock_context.workspace_path).resolve()
        assert result == expected

    def test_resolve_workspace_path_dot_relative(self, file_manager, mock_context):
        """Test resolving '.' relative path returns workspace root."""
        result = file_manager._resolve_workspace_path(mock_context, ".")
        expected = Path(mock_context.workspace_path).resolve()
        assert result == expected

    def test_resolve_workspace_path_no_workspace(self, file_manager):
        """Test resolving path with no workspace set raises exception."""
        context = Mock()
        context.workspace_path = None

        with pytest.raises(FileSystemException, match="Workspace path is not set"):
            file_manager._resolve_workspace_path(context, "file.txt")

    def test_validate_path_in_workspace_success(self, file_manager, mock_context):
        """Test successful path validation within workspace."""
        workspace_path = Path(mock_context.workspace_path)
        valid_path = workspace_path / "subdir" / "file.txt"

        # Should not raise exception
        file_manager._validate_path_in_workspace(mock_context, valid_path)

    def test_validate_path_outside_workspace(self, file_manager, mock_context):
        """Test path validation fails for path outside workspace."""
        outside_path = "/tmp/outside.txt"

        with pytest.raises(
            FileSystemException, match="Path is outside workspace boundaries"
        ):
            file_manager._validate_path_in_workspace(mock_context, outside_path)

    def test_validate_path_traversal_attack(self, file_manager, mock_context):
        """Test path validation detects directory traversal attempts."""
        workspace_path = Path(mock_context.workspace_path)
        # This would resolve to outside the workspace
        traversal_path = workspace_path / ".." / ".." / "etc" / "passwd"

        with pytest.raises(
            FileSystemException, match="Path is outside workspace boundaries"
        ):
            file_manager._validate_path_in_workspace(mock_context, traversal_path)

    def test_validate_path_no_workspace(self, file_manager):
        """Test path validation with no workspace set raises exception."""
        context = Mock()
        context.workspace_path = None

        with pytest.raises(FileSystemException, match="Workspace path is not set"):
            file_manager._validate_path_in_workspace(context, "/some/path")

    def test_validate_path_suspicious_components(
        self, file_manager, mock_context, caplog
    ):
        """Test path validation warns about suspicious components."""
        workspace_path = Path(mock_context.workspace_path)
        suspicious_path = workspace_path / ".git" / "config"

        # Should not raise exception but should log warning
        file_manager._validate_path_in_workspace(mock_context, suspicious_path)
        assert "Suspicious path component detected" in caplog.text


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
