"""Shared configuration settings for all creation steps."""

from typing import Dict, Any
from pydantic import Field
from pydantic_settings import BaseSettings


class WorkspaceConfig(BaseSettings):
    """Configuration for workspace management across all creation steps."""

    # Workspace settings
    temp_workspace_prefix: str = Field(
        default="/tmp/hyperion_workspace_", description="Prefix for temporary workspace"
    )
    cleanup_on_success: bool = Field(
        default=True, description="Whether to cleanup workspace on success"
    )
    cleanup_on_failure: bool = Field(
        default=False, description="Whether to cleanup workspace on failure"
    )

    # Git settings
    git_author_name: str = Field(
        default="Hyperion Creator", description="Git author name"
    )
    git_author_email: str = Field(
        default="hyperion@example.com", description="Git author email"
    )

    # File system settings
    max_file_size_mb: int = Field(default=10, description="Maximum file size in MB")
    max_files_per_directory: int = Field(
        default=1000, description="Maximum files per directory"
    )

    # Solution creator settings
    solution_creator_max_iterations: int = Field(
        default=10, description="Maximum number of fix attempts"
    )
    solution_creator_max_compilation_retries: int = Field(
        default=3, description="Maximum compilation retry attempts"
    )
    solution_creator_timeout_seconds: int = Field(
        default=30, description="Maximum execution time per test run"
    )
    solution_creator_compilation_timeout: int = Field(
        default=60, description="Maximum compilation time"
    )
    solution_creator_coverage_threshold: float = Field(
        default=0.9, description="Minimum test coverage required"
    )
    solution_creator_temp_workspace_prefix: str = Field(
        default="/tmp/hyperion_solution_", description="Prefix for temporary workspace"
    )

    class Config:
        env_prefix = "HYPERION_WORKSPACE_"
        case_sensitive = False


config = WorkspaceConfig()

LANGUAGE_CONFIGS: Dict[str, Dict[str, Any]] = {
    "PYTHON": {
        "file_extensions": [".py"],
        "test_frameworks": ["pytest", "unittest"],
        "build_tools": ["pip", "poetry", "setuptools"],
        "style_guides": ["pep8", "black"],
        "common_dependencies": ["pytest", "mock", "requests"],
    }
}


PROJECT_TYPE_CONFIGS: Dict[str, Dict[str, Any]] = {
    "PLAIN": {
        "build_file": None,
        "source_dir": "src",
        "test_dir": "tests",
        "resources_dir": "resources",
        "build_command": None,
        "test_command": "python -m pytest",
    }
}
