"""File manager for workspace operations."""

import os
import shutil
import logging
import stat
from typing import List, Optional, Dict, Any, Union
from pathlib import Path

from ..step3_create_solution_repository.models import SolutionCreationContext, FileStructure
from ..exceptions import FileSystemException

logger = logging.getLogger(__name__)


class FileManager:
    """Manager for file operations in the workspace.
    
    Provides secure file operations within the workspace boundaries,
    preventing directory traversal attacks and ensuring proper error handling.
    """

    def __init__(self) -> None:
        """Initialize the FileManager."""
        self.encoding = 'utf-8'
        logger.debug("FileManager initialized")

    def create_file_structure(self, context: SolutionCreationContext, file_structure: FileStructure) -> None:
        """Create directories and empty files based on the FileStructure."""
        logger.info(f"Creating file structure in workspace: {context.workspace_path}")
        workspace_path = Path(context.workspace_path)
        
        if not workspace_path.exists():
            logger.debug(f"Workspace path does not exist. Creating: {workspace_path}")
            workspace_path.mkdir(parents=True, exist_ok=True)

        # Create directories
        for directory in file_structure.directories:
            dir_path = workspace_path / directory
            try:
                dir_path.mkdir(parents=True, exist_ok=True)
                logger.debug(f"Created directory: {dir_path}")
            except OSError as e:
                logger.error(f"Error creating directory {dir_path}: {e}")
                raise
        
        # Create source files
        for file_path in file_structure.files:
            full_path = workspace_path / file_path
            try:
                full_path.parent.mkdir(parents=True, exist_ok=True)
                full_path.touch()
                logger.debug(f"Created source file: {full_path}")
            except OSError as e:
                logger.error(f"Error creating file {full_path}: {e}")
                raise
        
        # Create build files
        for build_file in file_structure.build_files:
            full_path = workspace_path / build_file
            try:
                full_path.parent.mkdir(parents=True, exist_ok=True)
                full_path.touch()
                logger.debug(f"Created build file: {full_path}")
            except OSError as e:
                logger.error(f"Error creating file {full_path}: {e}")
                raise

    def write_file(self, context: SolutionCreationContext, file_path: str, content: str) -> None:
        """Write content to a file in the workspace."""
        if not context.workspace_path:
            raise FileSystemException("Workspace path is not set in the context.", file_path=file_path)
        full_path = Path(context.workspace_path) / file_path
        logger.debug(f"Writing to file: {full_path}")
        try:
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(content, encoding='utf-8')
            logger.debug(f"Wrote {len(content)} chars to {full_path}")
        except OSError as e:
            logger.error(f"Error writing to file {full_path}: {e}")
            raise

    def read_file(self, context: SolutionCreationContext, file_path: str) -> str:
        """Read content from a file in the workspace."""
        if not context.workspace_path:
            raise FileSystemException("Workspace path is not set in the context.", file_path=file_path)
        full_path = Path(context.workspace_path) / file_path
        logger.debug(f"Reading from file: {full_path}")
        try:
            content = full_path.read_text(encoding='utf-8')
            logger.debug(f"Read {len(content)} chars from {full_path}")
            return content
        except FileNotFoundError:
            logger.warning(f"File not found during read: {full_path}")
            return ""
        except OSError as e:
            logger.error(f"Error reading file {full_path}: {e}")
            raise

    def copy_file(self, context: SolutionCreationContext, source_path: str, dest_path: str) -> None:
        """Copy a file within the workspace.
        
        Args:
            context: The solution creation context
            source_path: Source file path relative to workspace
            dest_path: Destination file path relative to workspace
            
        Raises:
            FileSystemException: If file copying fails
        """
        if not source_path or not dest_path:
            raise FileSystemException("Source and destination paths cannot be empty", file_path=source_path)
        
        try:
            source_full = self._resolve_workspace_path(context, source_path)
            dest_full = self._resolve_workspace_path(context, dest_path)
            
            self._validate_path_in_workspace(context, source_full)
            self._validate_path_in_workspace(context, dest_full)
            
            if not source_full.exists():
                raise FileSystemException(f"Source file does not exist: {source_path}", file_path=source_path)
            
            if not source_full.is_file():
                raise FileSystemException(f"Source path is not a file: {source_path}", file_path=source_path)
            
            dest_full.parent.mkdir(parents=True, exist_ok=True)
            
            shutil.copy2(source_full, dest_full)
            
            logger.debug(f"Copied file from {source_path} to {dest_path}")
            
        except FileSystemException:
            raise
        except Exception as e:
            logger.error(f"Error copying file from {source_path} to {dest_path}: {e}")
            raise FileSystemException(f"Failed to copy file: {str(e)}", file_path=source_path)

    def move_file(self, context: SolutionCreationContext, source_path: str, dest_path: str) -> None:
        """Move a file within the workspace.
        
        Args:
            context: The solution creation context
            source_path: Source file path relative to workspace
            dest_path: Destination file path relative to workspace
            
        Raises:
            FileSystemException: If file moving fails
        """
        if not source_path or not dest_path:
            raise FileSystemException("Source and destination paths cannot be empty", file_path=source_path)
        
        try:
            source_full = self._resolve_workspace_path(context, source_path)
            dest_full = self._resolve_workspace_path(context, dest_path)
            
            self._validate_path_in_workspace(context, source_full)
            self._validate_path_in_workspace(context, dest_full)
            
            if not source_full.exists():
                raise FileSystemException(f"Source file does not exist: {source_path}", file_path=source_path)
            
            dest_full.parent.mkdir(parents=True, exist_ok=True)
            
            shutil.move(str(source_full), str(dest_full))
            
            logger.debug(f"Moved file from {source_path} to {dest_path}")
            
        except FileSystemException:
            raise
        except Exception as e:
            logger.error(f"Error moving file from {source_path} to {dest_path}: {e}")
            raise FileSystemException(f"Failed to move file: {str(e)}", file_path=source_path)

    def delete_file(self, context: SolutionCreationContext, file_path: str) -> None:
        """Delete a file from the workspace.
        
        Args:
            context: The solution creation context
            file_path: File path relative to workspace
            
        Raises:
            FileSystemException: If file deletion fails
        """
        if not file_path:
            raise FileSystemException("File path cannot be empty", file_path=file_path)
        
        try:
            full_path = self._resolve_workspace_path(context, file_path)
            self._validate_path_in_workspace(context, full_path)
            
            if not full_path.exists():
                logger.warning(f"File does not exist, skipping deletion: {file_path}")
                return
            
            if full_path.is_file():
                full_path.unlink()
                logger.debug(f"Deleted file: {file_path}")
            elif full_path.is_dir():
                raise FileSystemException(f"Path is a directory, not a file: {file_path}", file_path=file_path)
            else:
                raise FileSystemException(f"Path is neither file nor directory: {file_path}", file_path=file_path)
            
        except FileSystemException:
            raise
        except Exception as e:
            logger.error(f"Error deleting file {file_path}: {e}")
            raise FileSystemException(f"Failed to delete file: {str(e)}", file_path=file_path)

    def create_directory(self, context: SolutionCreationContext, dir_path: str) -> None:
        """Create a directory in the workspace.
        
        Args:
            context: The solution creation context
            dir_path: Directory path relative to workspace
            
        Raises:
            FileSystemException: If directory creation fails
        """
        if not dir_path:
            raise FileSystemException("Directory path cannot be empty", file_path=dir_path)
        
        try:
            full_path = self._resolve_workspace_path(context, dir_path)
            self._validate_path_in_workspace(context, full_path)
            
            full_path.mkdir(parents=True, exist_ok=True)
            
            if not os.name == 'nt':  # Not Windows
                full_path.chmod(0o755)
            
            logger.debug(f"Created directory: {dir_path}")
            
        except Exception as e:
            logger.error(f"Error creating directory {dir_path}: {e}")
            raise FileSystemException(f"Failed to create directory: {str(e)}", file_path=dir_path)

    def list_files(self, context: SolutionCreationContext, dir_path: str = "") -> List[str]:
        """List files in a directory within the workspace.
        
        Args:
            context: The solution creation context
            dir_path: Directory path relative to workspace (empty for root)
            
        Returns:
            List of file paths relative to the specified directory
            
        Raises:
            FileSystemException: If directory listing fails
        """
        try:
            full_path = self._resolve_workspace_path(context, dir_path)
            self._validate_path_in_workspace(context, full_path)
            
            if not full_path.exists():
                raise FileSystemException(f"Directory does not exist: {dir_path}", file_path=dir_path)
            
            if not full_path.is_dir():
                raise FileSystemException(f"Path is not a directory: {dir_path}", file_path=dir_path)
            
            items = []
            for item in full_path.iterdir():
                relative_path = item.name
                items.append(relative_path)
            
            items.sort()
            logger.debug(f"Listed {len(items)} items in directory: {dir_path or 'root'}")
            return items
            
        except FileSystemException:
            raise
        except Exception as e:
            logger.error(f"Error listing files in directory {dir_path}: {e}")
            raise FileSystemException(f"Failed to list files: {str(e)}", file_path=dir_path)

    def file_exists(self, context: SolutionCreationContext, file_path: str) -> bool:
        """Check if a file exists in the workspace.
        
        Args:
            context: The solution creation context
            file_path: File path relative to workspace
            
        Returns:
            True if file exists, False otherwise
        """
        if not file_path:
            return False
        
        try:
            full_path = self._resolve_workspace_path(context, file_path)
            self._validate_path_in_workspace(context, full_path)
            return full_path.exists() and full_path.is_file()
        except Exception as e:
            logger.error(f"Error checking file existence for {file_path}: {e}")
            return False

    def get_file_size(self, context: SolutionCreationContext, file_path: str) -> int:
        """Get the size of a file in bytes.
        
        Args:
            context: The solution creation context
            file_path: File path relative to workspace
            
        Returns:
            File size in bytes
            
        Raises:
            FileSystemException: If getting file size fails
        """
        if not file_path:
            raise FileSystemException("File path cannot be empty", file_path=file_path)
        
        try:
            full_path = self._resolve_workspace_path(context, file_path)
            self._validate_path_in_workspace(context, full_path)
            
            if not full_path.exists():
                raise FileSystemException(f"File does not exist: {file_path}", file_path=file_path)
            
            if not full_path.is_file():
                raise FileSystemException(f"Path is not a file: {file_path}", file_path=file_path)
            
            size = full_path.stat().st_size
            logger.debug(f"File {file_path} size: {size} bytes")
            return size
            
        except FileSystemException:
            raise
        except Exception as e:
            logger.error(f"Error getting file size for {file_path}: {e}")
            raise FileSystemException(f"Failed to get file size: {str(e)}", file_path=file_path)

    def set_file_permissions(self, context: SolutionCreationContext, file_path: str, permissions: int) -> None:
        """Set file permissions.
        
        Args:
            context: The solution creation context
            file_path: File path relative to workspace
            permissions: Permissions in octal format (e.g., 0o755)
            
        Raises:
            FileSystemException: If setting permissions fails
        """
        if not file_path:
            raise FileSystemException("File path cannot be empty", file_path=file_path)
        
        if os.name == 'nt':
            logger.debug(f"Skipping permission setting on Windows for: {file_path}")
            return
        
        try:
            full_path = self._resolve_workspace_path(context, file_path)
            self._validate_path_in_workspace(context, full_path)
            
            if not full_path.exists():
                raise FileSystemException(f"File does not exist: {file_path}", file_path=file_path)
            
            if not isinstance(permissions, int) or permissions < 0 or permissions > 0o777:
                raise FileSystemException(f"Invalid permissions value: {permissions}", file_path=file_path)
            
            full_path.chmod(permissions)
            logger.debug(f"Set permissions {oct(permissions)} for file: {file_path}")
            
        except FileSystemException:
            raise
        except Exception as e:
            logger.error(f"Error setting permissions for {file_path}: {e}")
            raise FileSystemException(f"Failed to set file permissions: {str(e)}", file_path=file_path)

    def _resolve_workspace_path(self, context: SolutionCreationContext, relative_path: str) -> Path:
        """Resolve a relative path to an absolute path in the workspace.
        
        Args:
            context: The solution creation context
            relative_path: Relative path within workspace
            
        Returns:
            Absolute path in workspace
            
        Raises:
            FileSystemException: If path resolution fails
        """
        try:
            if not context.workspace_path:
                raise FileSystemException("Workspace path is not set in context", file_path=relative_path)
            
            workspace_path = Path(context.workspace_path).resolve()
            
            if not relative_path or relative_path == ".":
                return workspace_path
            
            full_path = (workspace_path / relative_path).resolve()
            
            return full_path
            
        except Exception as e:
            logger.error(f"Error resolving path {relative_path}: {e}")
            raise FileSystemException(f"Failed to resolve path: {str(e)}", file_path=relative_path)

    def _validate_path_in_workspace(self, context: SolutionCreationContext, path: Union[str, Path]) -> None:
        """Validate that a path is within the workspace.
        
        Args:
            context: The solution creation context
            path: Path to validate
            
        Raises:
            FileSystemException: If path is outside workspace
        """
        try:
            if not context.workspace_path:
                raise FileSystemException("Workspace path is not set in context", file_path=str(path))
            
            workspace_path = Path(context.workspace_path).resolve()
            target_path = Path(path).resolve()
            
            try:
                target_path.relative_to(workspace_path)
            except ValueError:
                raise FileSystemException(
                    f"Path is outside workspace boundaries: {path}",
                    file_path=str(path)
                )
            
            path_str = str(target_path)
            
            suspicious_components = ['..', '.git', '.ssh', '/etc', '/root', '/home']
            for component in suspicious_components:
                if component in path_str:
                    logger.warning(f"Suspicious path component detected: {component} in {path}")
            
        except FileSystemException:
            raise
        except Exception as e:
            logger.error(f"Error validating path {path}: {e}")
            raise FileSystemException(f"Failed to validate path: {str(e)}", file_path=str(path))

    def get_file_tree(self, context: SolutionCreationContext) -> str:
        """Return a string representing the file tree of the workspace."""
        if not context.workspace_path:
            return "Workspace path is not set in the context."
        workspace_path = Path(context.workspace_path)
        if not workspace_path.exists():
            return "Workspace directory does not exist."
            
        tree = []
        for item in sorted(workspace_path.rglob('*')):
            depth = len(item.relative_to(workspace_path).parts) - 1
            indent = '    ' * depth
            prefix = '└── ' if item.is_dir() else '├── '
            tree.append(f"{indent}{prefix}{item.name}")
        
        return "\n".join(tree) 