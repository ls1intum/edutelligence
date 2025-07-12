"""Workspace manager for managing temporary directories and cleanup."""

import logging
import shutil
import tempfile
from pathlib import Path
from typing import Optional, Dict, Any
from contextlib import contextmanager

from ..config import config

logger = logging.getLogger(__name__)


class WorkspaceManager:
    """Manager for creating and cleaning up temporary workspaces.

    Provides proper resource management for temporary directories used
    during solution creation, with automatic cleanup and lifecycle management.
    """

    def __init__(self) -> None:
        """Initialize the WorkspaceManager."""
        self._active_workspaces: Dict[str, Path] = {}
        logger.debug("WorkspaceManager initialized")

    def create_workspace(self, prefix: str = "hyperion_workspace_") -> str:
        """Create a new temporary workspace directory.

        Args:
            prefix: Prefix for the temporary directory name

        Returns:
            Path to the created workspace directory

        Raises:
            OSError: If workspace creation fails
        """
        try:
            workspace_path = Path(tempfile.mkdtemp(prefix=prefix))
            workspace_id = workspace_path.name

            self._active_workspaces[workspace_id] = workspace_path

            logger.info(f"Created workspace: {workspace_path}")
            return str(workspace_path)

        except Exception as e:
            logger.error(f"Failed to create workspace: {e}")
            raise OSError(f"Failed to create workspace: {str(e)}") from e

    def cleanup_workspace(self, workspace_path: str, force: bool = False) -> bool:
        """Clean up a workspace directory.

        Args:
            workspace_path: Path to the workspace to clean up
            force: Force cleanup even if configured not to cleanup

        Returns:
            True if cleanup was performed, False otherwise
        """
        try:
            workspace_path_obj = Path(workspace_path)
            workspace_id = workspace_path_obj.name

            # Determine if we should cleanup based on configuration
            should_cleanup = force or self._should_cleanup_workspace(workspace_path)

            if should_cleanup and workspace_path_obj.exists():
                shutil.rmtree(workspace_path_obj, ignore_errors=True)
                logger.info(f"Workspace cleaned up: {workspace_path}")

                # Remove from active workspaces
                if workspace_id in self._active_workspaces:
                    del self._active_workspaces[workspace_id]

                return True
            else:
                logger.info(f"Workspace preserved: {workspace_path}")
                return False

        except Exception as e:
            logger.warning(f"Failed to cleanup workspace {workspace_path}: {e}")
            return False

    def cleanup_all_workspaces(self, force: bool = False) -> int:
        """Clean up all active workspaces.

        Args:
            force: Force cleanup even if configured not to cleanup

        Returns:
            Number of workspaces cleaned up
        """
        cleaned_count = 0
        workspace_ids = list(self._active_workspaces.keys())

        for workspace_id in workspace_ids:
            workspace_path = self._active_workspaces[workspace_id]
            if self.cleanup_workspace(str(workspace_path), force=force):
                cleaned_count += 1

        return cleaned_count

    def get_active_workspaces(self) -> Dict[str, str]:
        """Get all active workspaces.

        Returns:
            Dictionary mapping workspace IDs to their paths
        """
        return {wid: str(path) for wid, path in self._active_workspaces.items()}

    def workspace_exists(self, workspace_path: str) -> bool:
        """Check if a workspace exists and is accessible.

        Args:
            workspace_path: Path to check

        Returns:
            True if workspace exists and is accessible
        """
        try:
            path = Path(workspace_path)
            return path.exists() and path.is_dir()
        except Exception:
            return False

    @contextmanager
    def managed_workspace(
        self, prefix: str = "hyperion_workspace_", cleanup: bool = True
    ):
        """Context manager for automatic workspace creation and cleanup.

        Args:
            prefix: Prefix for the temporary directory name
            cleanup: Whether to cleanup the workspace on exit

        Yields:
            Path to the created workspace directory

        Example:
            with workspace_manager.managed_workspace() as workspace_path:
                # Use workspace_path for operations
                pass
            # Workspace is automatically cleaned up
        """
        workspace_path = None
        try:
            workspace_path = self.create_workspace(prefix=prefix)
            yield workspace_path
        finally:
            if workspace_path and cleanup:
                self.cleanup_workspace(workspace_path, force=True)

    def _should_cleanup_workspace(self, workspace_path: str) -> bool:
        """Determine if a workspace should be cleaned up based on configuration.

        Args:
            workspace_path: Path to the workspace

        Returns:
            True if workspace should be cleaned up
        """
        # Check if workspace contains successful results
        workspace_path_obj = Path(workspace_path)

        # Look for indicators of successful completion
        has_solution_files = any(
            file.suffix in [".java", ".py", ".cpp", ".c", ".js", ".ts"]
            for file in workspace_path_obj.rglob("*")
            if file.is_file()
        )

        if has_solution_files:
            return getattr(config, "cleanup_on_success", True)
        else:
            return getattr(config, "cleanup_on_failure", False)

    def get_workspace_info(self, workspace_path: str) -> Dict[str, Any]:
        """Get information about a workspace.

        Args:
            workspace_path: Path to the workspace

        Returns:
            Dictionary with workspace information
        """
        try:
            path = Path(workspace_path)

            if not path.exists():
                return {"exists": False}

            info = {
                "exists": True,
                "path": str(path),
                "size_bytes": sum(
                    f.stat().st_size for f in path.rglob("*") if f.is_file()
                ),
                "file_count": len([f for f in path.rglob("*") if f.is_file()]),
                "directory_count": len([d for d in path.rglob("*") if d.is_dir()]),
            }

            return info

        except Exception as e:
            logger.error(f"Error getting workspace info for {workspace_path}: {e}")
            return {"exists": False, "error": str(e)}
