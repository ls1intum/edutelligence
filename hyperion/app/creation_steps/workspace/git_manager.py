"""Git manager for workspace operations."""

import os
import subprocess
import logging
import re
from typing import List, Dict, Any, Optional
from pathlib import Path

from ..step3_create_solution_repository.models import SolutionCreationContext
from ..exceptions import GitException
from ..config import config

logger = logging.getLogger(__name__)


class GitManager:
    """Manager for Git operations in the workspace.

    Provides secure Git operations within the workspace boundaries,
    with proper error handling and validation.
    """

    def __init__(self) -> None:
        """Initialize the GitManager."""
        self.git_executable = self._find_git_executable()
        logger.debug("GitManager initialized")

    def initialize_repository(self, context: SolutionCreationContext) -> None:
        """Initialize a Git repository in the workspace.

        Args:
            context: The solution creation context

        Raises:
            GitException: If repository initialization fails
        """
        logger.info(
            f"Initializing Git repository in workspace: {context.workspace_path}"
        )

        try:
            self._validate_workspace(context)

            # Check if repository already exists
            if self.is_repository_initialized(context):
                logger.warning("Git repository already initialized")
                return

            # Initialize repository
            result = self._run_git_command(context, ["init"])
            if result.returncode != 0:
                raise GitException(f"Git init failed: {result.stderr}")

            # Set up initial configuration
            self._setup_initial_config(context)

            logger.info("Git repository initialized successfully")

        except Exception as e:
            logger.error(f"Failed to initialize Git repository: {e}")
            raise GitException(f"Failed to initialize Git repository: {str(e)}")

    def add_files(
        self, context: SolutionCreationContext, file_patterns: List[str]
    ) -> None:
        """Add files to the Git staging area.

        Args:
            context: The solution creation context
            file_patterns: List of file patterns to add

        Raises:
            GitException: If adding files fails
        """
        if not file_patterns:
            raise GitException("No file patterns provided")

        logger.info(f"Adding files to Git staging area: {file_patterns}")

        try:
            self._validate_workspace(context)
            self._ensure_repository_exists(context)

            # Validate and sanitize file patterns
            validated_patterns = self._validate_file_patterns(context, file_patterns)

            # Add files to staging area
            for pattern in validated_patterns:
                result = self._run_git_command(context, ["add", pattern])
                if result.returncode != 0:
                    logger.warning(
                        f"Failed to add pattern '{pattern}': {result.stderr}"
                    )
                else:
                    logger.debug(f"Added pattern '{pattern}' to staging area")

            logger.info("Files added to Git staging area successfully")

        except Exception as e:
            logger.error(f"Failed to add files to Git: {e}")
            raise GitException(f"Failed to add files to Git: {str(e)}")

    def commit_changes(self, context: SolutionCreationContext, message: str) -> str:
        """Commit changes to the Git repository.

        Args:
            context: The solution creation context
            message: Commit message

        Returns:
            Commit hash

        Raises:
            GitException: If commit fails
        """
        if not message or not message.strip():
            raise GitException("Commit message cannot be empty")

        logger.info(f"Committing changes with message: {message[:50]}...")

        try:
            self._validate_workspace(context)
            self._ensure_repository_exists(context)

            # Sanitize commit message
            sanitized_message = self._sanitize_commit_message(message)

            # Commit changes
            result = self._run_git_command(context, ["commit", "-m", sanitized_message])
            if result.returncode != 0:
                if "nothing to commit" in result.stdout.lower():
                    logger.warning("No changes to commit")
                    return ""
                raise GitException(f"Git commit failed: {result.stderr}")

            # Get commit hash
            hash_result = self._run_git_command(context, ["rev-parse", "HEAD"])
            if hash_result.returncode != 0:
                logger.warning("Failed to get commit hash")
                return ""

            commit_hash = hash_result.stdout.strip()
            logger.info(f"Changes committed successfully with hash: {commit_hash[:8]}")
            return commit_hash

        except Exception as e:
            logger.error(f"Failed to commit changes: {e}")
            raise GitException(f"Failed to commit changes: {str(e)}")

    def create_branch(self, context: SolutionCreationContext, branch_name: str) -> None:
        """Create a new Git branch.

        Args:
            context: The solution creation context
            branch_name: Name of the branch to create

        Raises:
            GitException: If branch creation fails
        """
        if not branch_name or not branch_name.strip():
            raise GitException("Branch name cannot be empty")

        # Validate branch name first, before other validations
        validated_name = self._validate_branch_name(branch_name)

        logger.info(f"Creating Git branch: {branch_name}")

        try:
            self._validate_workspace(context)
            self._ensure_repository_exists(context)

            # Check if branch already exists
            if self._branch_exists(context, validated_name):
                logger.warning(f"Branch '{validated_name}' already exists")
                return

            # Create and switch to new branch
            result = self._run_git_command(context, ["checkout", "-b", validated_name])
            if result.returncode != 0:
                raise GitException(f"Failed to create branch: {result.stderr}")

            logger.info(f"Branch '{validated_name}' created successfully")

        except Exception as e:
            logger.error(f"Failed to create branch '{branch_name}': {e}")
            raise GitException(f"Failed to create branch '{branch_name}': {str(e)}")

    def get_status(self, context: SolutionCreationContext) -> Dict[str, List[str]]:
        """Get the Git status of the repository.

        Args:
            context: The solution creation context

        Returns:
            Dictionary with status information (modified, added, deleted files)

        Raises:
            GitException: If getting status fails
        """
        logger.debug("Getting Git repository status")

        try:
            self._validate_workspace(context)
            self._ensure_repository_exists(context)

            # Get status in porcelain format for easier parsing
            result = self._run_git_command(context, ["status", "--porcelain"])
            if result.returncode != 0:
                raise GitException(f"Failed to get Git status: {result.stderr}")

            # Parse status output
            status = self._parse_status_output(result.stdout)

            logger.debug(
                f"Git status: {len(status['modified'])} modified, "
                f"{len(status['added'])} added, {len(status['deleted'])} deleted"
            )

            return status

        except Exception as e:
            logger.error(f"Failed to get Git status: {e}")
            raise GitException(f"Failed to get Git status: {str(e)}")

    def get_commit_history(
        self, context: SolutionCreationContext, limit: int = 10
    ) -> List[Dict[str, str]]:
        """Get the commit history of the repository.

        Args:
            context: The solution creation context
            limit: Maximum number of commits to retrieve

        Returns:
            List of commit information dictionaries

        Raises:
            GitException: If getting commit history fails
        """
        if limit <= 0:
            raise GitException("Limit must be positive")

        logger.debug(f"Getting Git commit history (limit: {limit})")

        try:
            self._validate_workspace(context)
            self._ensure_repository_exists(context)

            # Get commit log with custom format
            format_str = "--pretty=format:%H|%an|%ae|%ad|%s"
            result = self._run_git_command(
                context, ["log", format_str, f"--max-count={limit}", "--date=iso"]
            )

            if result.returncode != 0:
                if "does not have any commits yet" in result.stderr:
                    logger.debug("Repository has no commits yet")
                    return []
                raise GitException(f"Failed to get commit history: {result.stderr}")

            # Parse commit history
            commits = self._parse_commit_history(result.stdout)

            logger.debug(f"Retrieved {len(commits)} commits from history")
            return commits

        except Exception as e:
            logger.error(f"Failed to get commit history: {e}")
            raise GitException(f"Failed to get commit history: {str(e)}")

    def create_tag(
        self,
        context: SolutionCreationContext,
        tag_name: str,
        message: Optional[str] = None,
    ) -> None:
        """Create a Git tag.

        Args:
            context: The solution creation context
            tag_name: Name of the tag to create
            message: Optional tag message

        Raises:
            GitException: If tag creation fails
        """
        if not tag_name or not tag_name.strip():
            raise GitException("Tag name cannot be empty")

        logger.info(f"Creating Git tag: {tag_name}")

        try:
            self._validate_workspace(context)
            self._ensure_repository_exists(context)

            # Validate tag name
            validated_name = self._validate_tag_name(tag_name)

            # Check if tag already exists
            if self._tag_exists(context, validated_name):
                logger.warning(f"Tag '{validated_name}' already exists")
                return

            # Create tag
            cmd = ["tag"]
            if message:
                sanitized_message = self._sanitize_commit_message(message)
                cmd.extend(["-a", validated_name, "-m", sanitized_message])
            else:
                cmd.append(validated_name)

            result = self._run_git_command(context, cmd)
            if result.returncode != 0:
                raise GitException(f"Failed to create tag: {result.stderr}")

            logger.info(f"Tag '{validated_name}' created successfully")

        except Exception as e:
            logger.error(f"Failed to create tag '{tag_name}': {e}")
            raise GitException(f"Failed to create tag '{tag_name}': {str(e)}")

    def is_repository_initialized(self, context: SolutionCreationContext) -> bool:
        """Check if a Git repository is initialized in the workspace.

        Args:
            context: The solution creation context

        Returns:
            True if repository is initialized, False otherwise
        """
        try:
            if not context.workspace_path:
                return False

            git_dir = Path(context.workspace_path) / ".git"
            return git_dir.exists() and (git_dir.is_dir() or git_dir.is_file())

        except Exception as e:
            logger.debug(f"Error checking repository status: {e}")
            return False

    def _run_git_command(
        self, context: SolutionCreationContext, command: List[str]
    ) -> subprocess.CompletedProcess:
        """Run a Git command in the workspace directory.

        Args:
            context: The solution creation context
            command: Git command and arguments

        Returns:
            Subprocess result

        Raises:
            GitException: If command execution fails
        """
        try:
            if not self.git_executable:
                raise GitException("Git executable not found")

            # Prepare full command
            full_command = [self.git_executable] + command

            # Validate command for security
            self._validate_git_command(command)

            # Run command in workspace directory
            result = subprocess.run(
                full_command,
                cwd=context.workspace_path,
                capture_output=True,
                text=True,
                timeout=30,  # 30 second timeout
            )

            logger.debug(
                f"Git command executed: {' '.join(command)} (exit code: {result.returncode})"
            )

            return result

        except subprocess.TimeoutExpired:
            raise GitException("Git command timed out")
        except Exception as e:
            logger.error(f"Git command execution failed: {e}")
            raise GitException(f"Git command failed: {str(e)}")

    def _validate_workspace(self, context: SolutionCreationContext) -> None:
        """Validate that the workspace exists and is accessible.

        Args:
            context: The solution creation context

        Raises:
            GitException: If workspace validation fails
        """
        if not context.workspace_path:
            raise GitException("Workspace path is not set")

        workspace_path = Path(context.workspace_path)

        if not workspace_path.exists():
            raise GitException(
                f"Workspace directory does not exist: {context.workspace_path}"
            )

        if not workspace_path.is_dir():
            raise GitException(
                f"Workspace path is not a directory: {context.workspace_path}"
            )

        if not os.access(workspace_path, os.W_OK):
            raise GitException(
                f"Workspace directory is not writable: {context.workspace_path}"
            )

    def _ensure_repository_exists(self, context: SolutionCreationContext) -> None:
        """Ensure that a Git repository exists in the workspace.

        Args:
            context: The solution creation context

        Raises:
            GitException: If repository does not exist
        """
        if not self.is_repository_initialized(context):
            raise GitException("Git repository is not initialized in workspace")

    def _find_git_executable(self) -> Optional[str]:
        """Find the Git executable on the system.

        Returns:
            Path to Git executable or None if not found
        """
        try:
            result = subprocess.run(
                ["which", "git"] if os.name != "nt" else ["where", "git"],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                git_path = result.stdout.strip().split("\n")[0]
                logger.debug(f"Found Git executable: {git_path}")
                return git_path
        except Exception as e:
            logger.debug(f"Error finding Git executable: {e}")

        # Fallback to common paths
        common_paths = ["git", "/usr/bin/git", "/usr/local/bin/git"]
        for path in common_paths:
            try:
                result = subprocess.run([path, "--version"], capture_output=True)
                if result.returncode == 0:
                    logger.debug(f"Found Git executable at: {path}")
                    return path
            except Exception:
                continue

        logger.warning("Git executable not found")
        return None

    def _setup_initial_config(self, context: SolutionCreationContext) -> None:
        """Set up initial Git configuration.

        Args:
            context: The solution creation context
        """
        try:
            # Set user name and email from config
            user_name = getattr(config, "git_user_name", "Solution Creator")
            user_email = getattr(config, "git_user_email", "solution@creator.local")

            self._run_git_command(context, ["config", "user.name", user_name])
            self._run_git_command(context, ["config", "user.email", user_email])

            logger.debug("Initial Git configuration set up")

        except Exception as e:
            logger.warning(f"Failed to set up initial Git config: {e}")

    def _validate_file_patterns(
        self, context: SolutionCreationContext, patterns: List[str]
    ) -> List[str]:
        """Validate and sanitize file patterns.

        Args:
            context: The solution creation context
            patterns: File patterns to validate

        Returns:
            List of validated patterns

        Raises:
            GitException: If patterns are invalid
        """
        validated = []
        workspace_path = Path(context.workspace_path)

        for pattern in patterns:
            # Basic sanitization
            pattern = pattern.strip()
            if not pattern:
                continue

            # Prevent directory traversal
            if ".." in pattern or pattern.startswith("/"):
                logger.warning(f"Suspicious file pattern rejected: {pattern}")
                continue

            # Check if pattern matches any files (for non-wildcard patterns)
            if "*" not in pattern and "?" not in pattern:
                file_path = workspace_path / pattern
                if not file_path.exists():
                    logger.warning(f"File does not exist: {pattern}")
                    continue

            validated.append(pattern)

        if not validated:
            raise GitException("No valid file patterns provided")

        return validated

    def _validate_branch_name(self, name: str) -> str:
        """Validate and sanitize branch name.

        Args:
            name: Branch name to validate

        Returns:
            Validated branch name

        Raises:
            GitException: If name is invalid
        """
        name = name.strip()

        # Git branch name rules
        if not re.match(r"^[a-zA-Z0-9._/-]+$", name):
            raise GitException(f"Invalid branch name: {name}")

        if name.startswith("-") or name.endswith(".") or ".." in name:
            raise GitException(f"Invalid branch name format: {name}")

        if len(name) > 250:  # Reasonable limit
            raise GitException("Branch name too long")

        return name

    def _validate_tag_name(self, name: str) -> str:
        """Validate and sanitize tag name.

        Args:
            name: Tag name to validate

        Returns:
            Validated tag name

        Raises:
            GitException: If name is invalid
        """
        name = name.strip()

        # Git tag name rules (similar to branch names)
        if not re.match(r"^[a-zA-Z0-9._/-]+$", name):
            raise GitException(f"Invalid tag name: {name}")

        if name.startswith("-") or name.endswith(".") or ".." in name:
            raise GitException(f"Invalid tag name format: {name}")

        if len(name) > 250:  # Reasonable limit
            raise GitException("Tag name too long")

        return name

    def _sanitize_commit_message(self, message: str) -> str:
        """Sanitize commit message.

        Args:
            message: Commit message to sanitize

        Returns:
            Sanitized commit message
        """
        # Remove potentially dangerous characters
        sanitized = re.sub(r"[`$\\]", "", message.strip())

        # Limit length
        if len(sanitized) > 500:
            sanitized = sanitized[:497] + "..."

        return sanitized

    def _validate_git_command(self, command: List[str]) -> None:
        """Validate Git command for security.

        Args:
            command: Git command to validate

        Raises:
            GitException: If command is potentially dangerous
        """
        if not command:
            raise GitException("Empty Git command")

        # Whitelist of allowed Git commands
        allowed_commands = {
            "init",
            "add",
            "commit",
            "status",
            "log",
            "tag",
            "branch",
            "checkout",
            "rev-parse",
            "config",
            "show-ref",
        }

        if command[0] not in allowed_commands:
            raise GitException(f"Git command not allowed: {command[0]}")

        # Check for dangerous arguments
        dangerous_args = ["--exec", "--upload-pack", "--receive-pack"]
        for arg in command:
            if any(dangerous in arg for dangerous in dangerous_args):
                raise GitException(f"Dangerous Git argument: {arg}")

    def _branch_exists(
        self, context: SolutionCreationContext, branch_name: str
    ) -> bool:
        """Check if a branch exists.

        Args:
            context: The solution creation context
            branch_name: Name of the branch to check

        Returns:
            True if branch exists, False otherwise
        """
        try:
            result = self._run_git_command(
                context, ["show-ref", "--verify", f"refs/heads/{branch_name}"]
            )
            return result.returncode == 0
        except Exception:
            return False

    def _tag_exists(self, context: SolutionCreationContext, tag_name: str) -> bool:
        """Check if a tag exists.

        Args:
            context: The solution creation context
            tag_name: Name of the tag to check

        Returns:
            True if tag exists, False otherwise
        """
        try:
            result = self._run_git_command(
                context, ["show-ref", "--verify", f"refs/tags/{tag_name}"]
            )
            return result.returncode == 0
        except Exception:
            return False

    def _parse_status_output(self, output: str) -> Dict[str, List[str]]:
        """Parse Git status output.

        Args:
            output: Git status output in porcelain format

        Returns:
            Dictionary with categorized file lists
        """
        status = {"modified": [], "added": [], "deleted": [], "untracked": []}

        for line in output.strip().split("\n"):
            if not line:
                continue

            status_code = line[:2]
            filename = line[3:]

            if status_code[0] == "A" or status_code[1] == "A":
                status["added"].append(filename)
            elif status_code[0] == "M" or status_code[1] == "M":
                status["modified"].append(filename)
            elif status_code[0] == "D" or status_code[1] == "D":
                status["deleted"].append(filename)
            elif status_code == "??":
                status["untracked"].append(filename)

        return status

    def _parse_commit_history(self, output: str) -> List[Dict[str, str]]:
        """Parse Git commit history output.

        Args:
            output: Git log output

        Returns:
            List of commit information dictionaries
        """
        commits = []

        for line in output.strip().split("\n"):
            if not line:
                continue

            parts = line.split("|", 4)
            if len(parts) == 5:
                commits.append(
                    {
                        "hash": parts[0],
                        "author_name": parts[1],
                        "author_email": parts[2],
                        "date": parts[3],
                        "message": parts[4],
                    }
                )

        return commits
