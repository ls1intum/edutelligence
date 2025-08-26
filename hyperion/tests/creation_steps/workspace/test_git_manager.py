"""Unit tests for GitManager class."""

# python -m pytest test_git_manager.py

import sys
import tempfile
import shutil
import pytest
import subprocess
from pathlib import Path
from unittest.mock import Mock, patch

# Add project root to path for imports
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from app.creation_steps.workspace.git_manager import GitManager  # noqa: E402
from app.creation_steps.step3_create_solution_repository.models import (  # noqa: E402
    SolutionCreationContext,
)
from app.creation_steps.exceptions import GitException  # noqa: E402


class TestGitManager:
    """Test suite for GitManager class."""

    @pytest.fixture
    def git_manager(self):
        """Create a GitManager instance for testing."""
        with patch.object(
            GitManager, "_find_git_executable", return_value="/usr/bin/git"
        ):
            return GitManager()

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

    @pytest.fixture
    def mock_subprocess_run(self):
        """Mock subprocess.run for testing."""
        with patch("subprocess.run") as mock_run:
            # Default successful result
            mock_result = Mock()
            mock_result.returncode = 0
            mock_result.stdout = ""
            mock_result.stderr = ""
            mock_run.return_value = mock_result
            yield mock_run

    def test_init_success(self):
        """Test GitManager initialization with Git found."""
        with patch.object(
            GitManager, "_find_git_executable", return_value="/usr/bin/git"
        ):
            manager = GitManager()
            assert manager.git_executable == "/usr/bin/git"

    def test_init_no_git(self):
        """Test GitManager initialization without Git."""
        with patch.object(GitManager, "_find_git_executable", return_value=None):
            manager = GitManager()
            assert manager.git_executable is None

    def test_initialize_repository_success(
        self, git_manager, mock_context, mock_subprocess_run
    ):
        """Test successful repository initialization."""
        # Mock repository not initialized
        with patch.object(git_manager, "is_repository_initialized", return_value=False):
            git_manager.initialize_repository(mock_context)

        # Verify git init was called
        mock_subprocess_run.assert_any_call(
            ["/usr/bin/git", "init"],
            cwd=mock_context.workspace_path,
            capture_output=True,
            text=True,
            timeout=30,
        )

    def test_initialize_repository_already_exists(
        self, git_manager, mock_context, mock_subprocess_run
    ):
        """Test repository initialization when already exists."""
        with patch.object(git_manager, "is_repository_initialized", return_value=True):
            git_manager.initialize_repository(mock_context)

        # Verify git init was not called
        assert not any(
            call[0][0][1] == "init" for call in mock_subprocess_run.call_args_list
        )

    def test_initialize_repository_git_init_fails(
        self, git_manager, mock_context, mock_subprocess_run
    ):
        """Test repository initialization when git init fails."""
        mock_subprocess_run.return_value.returncode = 1
        mock_subprocess_run.return_value.stderr = "Permission denied"

        with patch.object(git_manager, "is_repository_initialized", return_value=False):
            with pytest.raises(GitException, match="Git init failed"):
                git_manager.initialize_repository(mock_context)

    def test_initialize_repository_invalid_workspace(self, git_manager):
        """Test repository initialization with invalid workspace."""
        context = Mock()
        context.workspace_path = "/nonexistent/path"

        with pytest.raises(GitException, match="Workspace directory does not exist"):
            git_manager.initialize_repository(context)

    def test_add_files_success(self, git_manager, mock_context, mock_subprocess_run):
        """Test successful file addition."""
        file_patterns = ["*.py", "README.md"]

        # Create test files
        workspace = Path(mock_context.workspace_path)
        (workspace / "test.py").write_text("print('hello')")
        (workspace / "README.md").write_text("# Test")

        with patch.object(git_manager, "_ensure_repository_exists"):
            git_manager.add_files(mock_context, file_patterns)

        # Verify git add was called for each pattern
        assert mock_subprocess_run.call_count >= len(file_patterns)

    def test_add_files_empty_patterns(self, git_manager, mock_context):
        """Test adding files with empty patterns list."""
        with pytest.raises(GitException, match="No file patterns provided"):
            git_manager.add_files(mock_context, [])

    def test_add_files_no_valid_patterns(
        self, git_manager, mock_context, mock_subprocess_run
    ):
        """Test adding files with no valid patterns."""
        file_patterns = ["../../../etc/passwd", "/absolute/path"]

        with patch.object(git_manager, "_ensure_repository_exists"):
            with pytest.raises(GitException, match="No valid file patterns provided"):
                git_manager.add_files(mock_context, file_patterns)

    def test_commit_changes_success(
        self, git_manager, mock_context, mock_subprocess_run
    ):
        """Test successful commit."""
        message = "Initial commit"
        commit_hash = "abc123def456"

        # Mock git commit success
        mock_subprocess_run.return_value.returncode = 0

        # Mock git rev-parse to return commit hash
        def side_effect(*args, **kwargs):
            result = Mock()
            result.returncode = 0
            if "rev-parse" in args[0]:
                result.stdout = commit_hash
            else:
                result.stdout = ""
            result.stderr = ""
            return result

        mock_subprocess_run.side_effect = side_effect

        with patch.object(git_manager, "_ensure_repository_exists"):
            result = git_manager.commit_changes(mock_context, message)

        assert result == commit_hash

    def test_commit_changes_empty_message(self, git_manager, mock_context):
        """Test commit with empty message."""
        with pytest.raises(GitException, match="Commit message cannot be empty"):
            git_manager.commit_changes(mock_context, "")

    def test_commit_changes_nothing_to_commit(
        self, git_manager, mock_context, mock_subprocess_run
    ):
        """Test commit when nothing to commit."""
        mock_subprocess_run.return_value.returncode = 1
        mock_subprocess_run.return_value.stdout = (
            "nothing to commit, working tree clean"
        )

        with patch.object(git_manager, "_ensure_repository_exists"):
            result = git_manager.commit_changes(mock_context, "Test commit")

        assert result == ""

    def test_commit_changes_fails(self, git_manager, mock_context, mock_subprocess_run):
        """Test commit failure."""
        mock_subprocess_run.return_value.returncode = 1
        mock_subprocess_run.return_value.stderr = "Author identity unknown"

        with patch.object(git_manager, "_ensure_repository_exists"):
            with pytest.raises(GitException, match="Git commit failed"):
                git_manager.commit_changes(mock_context, "Test commit")

    def test_create_branch_success(
        self, git_manager, mock_context, mock_subprocess_run
    ):
        """Test successful branch creation."""
        branch_name = "feature/new-feature"

        with patch.object(git_manager, "_ensure_repository_exists"):
            with patch.object(git_manager, "_branch_exists", return_value=False):
                git_manager.create_branch(mock_context, branch_name)

        # Verify git checkout -b was called
        mock_subprocess_run.assert_called_with(
            ["/usr/bin/git", "checkout", "-b", branch_name],
            cwd=mock_context.workspace_path,
            capture_output=True,
            text=True,
            timeout=30,
        )

    def test_create_branch_empty_name(self, git_manager, mock_context):
        """Test branch creation with empty name."""
        with pytest.raises(GitException, match="Branch name cannot be empty"):
            git_manager.create_branch(mock_context, "")

    def test_create_branch_invalid_name(self, git_manager, mock_context):
        """Test branch creation with invalid name."""
        with pytest.raises(GitException, match="Invalid branch name"):
            git_manager.create_branch(mock_context, "invalid@branch#name")

    def test_create_branch_already_exists(
        self, git_manager, mock_context, mock_subprocess_run
    ):
        """Test branch creation when branch already exists."""
        branch_name = "existing-branch"

        with patch.object(git_manager, "_ensure_repository_exists"):
            with patch.object(git_manager, "_branch_exists", return_value=True):
                git_manager.create_branch(mock_context, branch_name)

        # Verify git checkout was not called
        assert not any(
            "checkout" in str(call) for call in mock_subprocess_run.call_args_list
        )

    def test_get_status_success(self, git_manager, mock_context, mock_subprocess_run):
        """Test successful status retrieval."""
        status_output = "M  modified.py\nA  added.py\nD  deleted.py\n?? untracked.py"
        mock_subprocess_run.return_value.stdout = status_output

        with patch.object(git_manager, "_ensure_repository_exists"):
            status = git_manager.get_status(mock_context)

        assert "modified.py" in status["modified"]
        assert "added.py" in status["added"]
        assert "deleted.py" in status["deleted"]
        assert "untracked.py" in status["untracked"]

    def test_get_status_empty(self, git_manager, mock_context, mock_subprocess_run):
        """Test status retrieval with clean repository."""
        mock_subprocess_run.return_value.stdout = ""

        with patch.object(git_manager, "_ensure_repository_exists"):
            status = git_manager.get_status(mock_context)

        assert status == {"modified": [], "added": [], "deleted": [], "untracked": []}

    def test_get_commit_history_success(
        self, git_manager, mock_context, mock_subprocess_run
    ):
        """Test successful commit history retrieval."""
        history_output = (
            "abc123|John Doe|john@example.com|2023-01-01 12:00:00|Initial commit\n"
            "def456|Jane Doe|jane@example.com|2023-01-02 13:00:00|Second commit"
        )
        mock_subprocess_run.return_value.stdout = history_output

        with patch.object(git_manager, "_ensure_repository_exists"):
            commits = git_manager.get_commit_history(mock_context, 2)

        assert len(commits) == 2
        assert commits[0]["hash"] == "abc123"
        assert commits[0]["author_name"] == "John Doe"
        assert commits[0]["message"] == "Initial commit"

    def test_get_commit_history_no_commits(
        self, git_manager, mock_context, mock_subprocess_run
    ):
        """Test commit history retrieval with no commits."""
        mock_subprocess_run.return_value.returncode = 128
        mock_subprocess_run.return_value.stderr = "does not have any commits yet"

        with patch.object(git_manager, "_ensure_repository_exists"):
            commits = git_manager.get_commit_history(mock_context)

        assert commits == []

    def test_get_commit_history_invalid_limit(self, git_manager, mock_context):
        """Test commit history with invalid limit."""
        with pytest.raises(GitException, match="Limit must be positive"):
            git_manager.get_commit_history(mock_context, 0)

    def test_create_tag_success(self, git_manager, mock_context, mock_subprocess_run):
        """Test successful tag creation."""
        tag_name = "v1.0.0"
        message = "Version 1.0.0 release"

        with patch.object(git_manager, "_ensure_repository_exists"):
            with patch.object(git_manager, "_tag_exists", return_value=False):
                git_manager.create_tag(mock_context, tag_name, message)

        # Verify git tag was called with annotated tag
        mock_subprocess_run.assert_called_with(
            ["/usr/bin/git", "tag", "-a", tag_name, "-m", message],
            cwd=mock_context.workspace_path,
            capture_output=True,
            text=True,
            timeout=30,
        )

    def test_create_tag_lightweight(
        self, git_manager, mock_context, mock_subprocess_run
    ):
        """Test lightweight tag creation."""
        tag_name = "v1.0.0"

        with patch.object(git_manager, "_ensure_repository_exists"):
            with patch.object(git_manager, "_tag_exists", return_value=False):
                git_manager.create_tag(mock_context, tag_name)

        # Verify git tag was called without annotation
        mock_subprocess_run.assert_called_with(
            ["/usr/bin/git", "tag", tag_name],
            cwd=mock_context.workspace_path,
            capture_output=True,
            text=True,
            timeout=30,
        )

    def test_create_tag_empty_name(self, git_manager, mock_context):
        """Test tag creation with empty name."""
        with pytest.raises(GitException, match="Tag name cannot be empty"):
            git_manager.create_tag(mock_context, "")

    def test_create_tag_already_exists(
        self, git_manager, mock_context, mock_subprocess_run
    ):
        """Test tag creation when tag already exists."""
        tag_name = "existing-tag"

        with patch.object(git_manager, "_ensure_repository_exists"):
            with patch.object(git_manager, "_tag_exists", return_value=True):
                git_manager.create_tag(mock_context, tag_name)

        # Verify git tag was not called
        assert not any(
            "tag" in str(call) for call in mock_subprocess_run.call_args_list
        )

    def test_is_repository_initialized_true(self, git_manager, mock_context):
        """Test repository initialization check when initialized."""
        git_dir = Path(mock_context.workspace_path) / ".git"
        git_dir.mkdir()

        result = git_manager.is_repository_initialized(mock_context)
        assert result is True

    def test_is_repository_initialized_false(self, git_manager, mock_context):
        """Test repository initialization check when not initialized."""
        result = git_manager.is_repository_initialized(mock_context)
        assert result is False

    def test_is_repository_initialized_no_workspace(self, git_manager):
        """Test repository initialization check with no workspace."""
        context = Mock()
        context.workspace_path = None

        result = git_manager.is_repository_initialized(context)
        assert result is False

    def test_run_git_command_success(
        self, git_manager, mock_context, mock_subprocess_run
    ):
        """Test successful Git command execution."""
        command = ["status"]

        result = git_manager._run_git_command(mock_context, command)

        assert result.returncode == 0
        mock_subprocess_run.assert_called_with(
            ["/usr/bin/git", "status"],
            cwd=mock_context.workspace_path,
            capture_output=True,
            text=True,
            timeout=30,
        )

    def test_run_git_command_no_executable(self, mock_context):
        """Test Git command execution without executable."""
        manager = GitManager.__new__(GitManager)
        manager.git_executable = None

        with pytest.raises(GitException, match="Git executable not found"):
            manager._run_git_command(mock_context, ["status"])

    def test_run_git_command_timeout(self, git_manager, mock_context):
        """Test Git command timeout."""
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("git", 30)):
            with pytest.raises(GitException, match="Git command timed out"):
                git_manager._run_git_command(mock_context, ["status"])

    def test_run_git_command_invalid_command(self, git_manager, mock_context):
        """Test Git command validation."""
        with pytest.raises(GitException, match="Git command not allowed"):
            git_manager._run_git_command(mock_context, ["rm", "-rf", "/"])

    def test_validate_workspace_success(self, git_manager, mock_context):
        """Test successful workspace validation."""
        # Should not raise exception
        git_manager._validate_workspace(mock_context)

    def test_validate_workspace_no_path(self, git_manager):
        """Test workspace validation with no path."""
        context = Mock()
        context.workspace_path = None

        with pytest.raises(GitException, match="Workspace path is not set"):
            git_manager._validate_workspace(context)

    def test_validate_workspace_not_exists(self, git_manager):
        """Test workspace validation with non-existent path."""
        context = Mock()
        context.workspace_path = "/nonexistent/path"

        with pytest.raises(GitException, match="Workspace directory does not exist"):
            git_manager._validate_workspace(context)

    def test_validate_workspace_not_directory(self, git_manager, temp_workspace):
        """Test workspace validation with file instead of directory."""
        file_path = Path(temp_workspace) / "file.txt"
        file_path.write_text("content")

        context = Mock()
        context.workspace_path = str(file_path)

        with pytest.raises(GitException, match="Workspace path is not a directory"):
            git_manager._validate_workspace(context)

    def test_find_git_executable_which_success(self):
        """Test finding Git executable using which."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = "/usr/bin/git\n"

            manager = GitManager()
            assert manager.git_executable == "/usr/bin/git"

    def test_find_git_executable_fallback(self):
        """Test finding Git executable using fallback paths."""
        with patch("subprocess.run") as mock_run:
            # First call (which/where) fails
            mock_run.return_value.returncode = 1

            # Second call (git --version) succeeds
            def side_effect(*args, **kwargs):
                if args[0][0] == "git" and args[0][1] == "--version":
                    result = Mock()
                    result.returncode = 0
                    return result
                else:
                    result = Mock()
                    result.returncode = 1
                    return result

            mock_run.side_effect = side_effect

            manager = GitManager()
            assert manager.git_executable == "git"

    def test_find_git_executable_not_found(self):
        """Test Git executable not found."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 1

            manager = GitManager()
            assert manager.git_executable is None

    def test_validate_branch_name_valid(self, git_manager):
        """Test valid branch name validation."""
        valid_names = ["main", "feature/new-feature", "bugfix_123", "release-1.0"]

        for name in valid_names:
            result = git_manager._validate_branch_name(name)
            assert result == name

    def test_validate_branch_name_invalid(self, git_manager):
        """Test invalid branch name validation."""
        invalid_names = [
            "",
            "branch@name",
            "branch#name",
            "-invalid",
            "invalid.",
            "branch..name",
        ]

        for name in invalid_names:
            with pytest.raises(GitException):
                git_manager._validate_branch_name(name)

    def test_validate_tag_name_valid(self, git_manager):
        """Test valid tag name validation."""
        valid_names = ["v1.0.0", "release/1.0", "tag_123"]

        for name in valid_names:
            result = git_manager._validate_tag_name(name)
            assert result == name

    def test_validate_tag_name_invalid(self, git_manager):
        """Test invalid tag name validation."""
        invalid_names = [
            "",
            "tag@name",
            "tag#name",
            "-invalid",
            "invalid.",
            "tag..name",
        ]

        for name in invalid_names:
            with pytest.raises(GitException):
                git_manager._validate_tag_name(name)

    def test_sanitize_commit_message(self, git_manager):
        """Test commit message sanitization."""
        # Test dangerous characters removal
        message = "Test `command` with $variable and \\backslash"
        result = git_manager._sanitize_commit_message(message)
        assert "`" not in result
        assert "$" not in result
        assert "\\" not in result

        # Test length limiting
        long_message = "a" * 600
        result = git_manager._sanitize_commit_message(long_message)
        assert len(result) <= 500
        assert result.endswith("...")

    def test_validate_file_patterns_valid(self, git_manager, mock_context):
        """Test valid file pattern validation."""
        # Create test files
        workspace = Path(mock_context.workspace_path)
        (workspace / "test.py").write_text("content")
        (workspace / "README.md").write_text("content")

        patterns = ["test.py", "*.md", "src/**/*.py"]
        result = git_manager._validate_file_patterns(mock_context, patterns)

        assert "test.py" in result
        assert "*.md" in result
        assert "src/**/*.py" in result

    def test_validate_file_patterns_suspicious(self, git_manager, mock_context):
        """Test suspicious file pattern rejection."""
        patterns = ["../../../etc/passwd", "/absolute/path", ""]

        with pytest.raises(GitException, match="No valid file patterns provided"):
            git_manager._validate_file_patterns(mock_context, patterns)

    def test_branch_exists_true(self, git_manager, mock_context, mock_subprocess_run):
        """Test branch existence check when branch exists."""
        mock_subprocess_run.return_value.returncode = 0

        result = git_manager._branch_exists(mock_context, "main")
        assert result is True

    def test_branch_exists_false(self, git_manager, mock_context, mock_subprocess_run):
        """Test branch existence check when branch doesn't exist."""
        mock_subprocess_run.return_value.returncode = 1

        result = git_manager._branch_exists(mock_context, "nonexistent")
        assert result is False

    def test_tag_exists_true(self, git_manager, mock_context, mock_subprocess_run):
        """Test tag existence check when tag exists."""
        mock_subprocess_run.return_value.returncode = 0

        result = git_manager._tag_exists(mock_context, "v1.0.0")
        assert result is True

    def test_tag_exists_false(self, git_manager, mock_context, mock_subprocess_run):
        """Test tag existence check when tag doesn't exist."""
        mock_subprocess_run.return_value.returncode = 1

        result = git_manager._tag_exists(mock_context, "nonexistent")
        assert result is False

    def test_parse_status_output(self, git_manager):
        """Test Git status output parsing."""
        output = "M  modified.py\nA  added.py\nD  deleted.py\n?? untracked.py\nAM staged_and_modified.py"

        result = git_manager._parse_status_output(output)

        assert "modified.py" in result["modified"]
        assert "added.py" in result["added"]
        assert "deleted.py" in result["deleted"]
        assert "untracked.py" in result["untracked"]
        assert "staged_and_modified.py" in result["added"]  # A flag takes precedence

    def test_parse_commit_history(self, git_manager):
        """Test commit history parsing."""
        output = (
            "abc123|John Doe|john@example.com|2023-01-01 12:00:00|Initial commit\n"
            "def456|Jane Doe|jane@example.com|2023-01-02 13:00:00|Second commit"
        )

        result = git_manager._parse_commit_history(output)

        assert len(result) == 2
        assert result[0]["hash"] == "abc123"
        assert result[0]["author_name"] == "John Doe"
        assert result[0]["author_email"] == "john@example.com"
        assert result[0]["date"] == "2023-01-01 12:00:00"
        assert result[0]["message"] == "Initial commit"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
