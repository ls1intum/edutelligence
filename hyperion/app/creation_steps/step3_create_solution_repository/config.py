"""Configuration settings for Step 3: Create Solution Repository."""

from typing import Dict, Any
from pydantic import BaseSettings, Field


class SolutionCreatorConfig(BaseSettings):
    """Configuration for solution repository creator."""
    
    # Iteration limits
    max_iterations: int = Field(default=10, description="Maximum number of fix attempts")
    max_compilation_retries: int = Field(default=3, description="Maximum compilation retry attempts")
    
    # Timeouts
    timeout_seconds: int = Field(default=30, description="Maximum execution time per test run")
    compilation_timeout: int = Field(default=60, description="Maximum compilation time")
    
    # Quality thresholds
    coverage_threshold: float = Field(default=0.9, description="Minimum test coverage required")
    
    # Workspace settings
    temp_workspace_prefix: str = Field(default="/tmp/hyperion_solution_", description="Prefix for temporary workspace")
    cleanup_on_success: bool = Field(default=True, description="Whether to cleanup workspace on success")
    cleanup_on_failure: bool = Field(default=False, description="Whether to cleanup workspace on failure")
    
    # Git settings
    git_author_name: str = Field(default="Hyperion Solution Creator", description="Git author name")
    git_author_email: str = Field(default="hyperion@example.com", description="Git author email")
    
    # Language-specific settings
    python_version: str = Field(default="3.11", description="Python version to use")
    
    # AI model settings
    model_temperature: float = Field(default=0.1, description="Temperature for AI model")
    max_tokens: int = Field(default=80000, description="Maximum tokens for AI responses")
    
    class Config:
        env_prefix = "SOLUTION_CREATOR_"
        case_sensitive = False


config = SolutionCreatorConfig()


LANGUAGE_CONFIGS: Dict[str, Dict[str, Any]] = {
    "PYTHON": {
        "file_extensions": [".py"],
        "test_frameworks": ["pytest", "unittest"],
        "build_tools": ["pip", "poetry", "setuptools"],
        "style_guides": ["pep8", "black"],
        "common_dependencies": ["pytest", "mock", "requests"]
    }
}


PROJECT_TYPE_CONFIGS: Dict[str, Dict[str, Any]] = {
    "PLAIN": {
        "build_file": None,
        "source_dir": "src",
        "test_dir": "tests",
        "resources_dir": "resources",
        "build_command": None,
        "test_command": "python -m pytest"
    }
} 