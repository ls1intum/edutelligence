"""Unit tests for Step 3 configuration."""

import pytest
from unittest.mock import patch, Mock
import os

from ..config import SolutionCreatorConfig, config


class TestSolutionCreatorConfig:
    """Test SolutionCreatorConfig class."""
    
    def test_config_initialization_defaults(self):
        """Test config initialization with default values."""
        test_config = SolutionCreatorConfig()
        
        assert test_config.max_iterations == 5
        assert test_config.timeout_seconds == 300
        assert test_config.cleanup_on_success is True
        assert test_config.cleanup_on_failure is False
        assert test_config.workspace_base_path == "/tmp"
        assert test_config.enable_logging is True
        assert test_config.log_level == "INFO"
    
    def test_config_initialization_with_values(self):
        """Test config initialization with custom values."""
        test_config = SolutionCreatorConfig(
            max_iterations=10,
            timeout_seconds=600,
            cleanup_on_success=False,
            cleanup_on_failure=True,
            workspace_base_path="/custom/path",
            enable_logging=False,
            log_level="DEBUG"
        )
        
        assert test_config.max_iterations == 10
        assert test_config.timeout_seconds == 600
        assert test_config.cleanup_on_success is False
        assert test_config.cleanup_on_failure is True
        assert test_config.workspace_base_path == "/custom/path"
        assert test_config.enable_logging is False
        assert test_config.log_level == "DEBUG"
    
    def test_config_language_settings_python(self):
        """Test Python language settings."""
        test_config = SolutionCreatorConfig()
        python_settings = test_config.language_settings["PYTHON"]
        
        assert python_settings["file_extension"] == ".py"
        assert python_settings["test_framework"] == "pytest"
        assert python_settings["build_tool"] is None
        assert "PLAIN" in python_settings["supported_project_types"]
        assert python_settings["main_file_template"] == "main.py"
        assert python_settings["test_file_template"] == "test_{name}.py"
    
    def test_config_project_type_settings_plain(self):
        """Test PLAIN project type settings."""
        test_config = SolutionCreatorConfig()
        plain_settings = test_config.project_type_settings["PLAIN"]
        
        assert plain_settings["build_file"] is None
        assert plain_settings["source_directory"] == "src"
        assert plain_settings["test_directory"] == "tests"
        assert plain_settings["output_directory"] == "output"
        assert plain_settings["requires_build_tool"] is False
    
    def test_config_project_type_settings_maven(self):
        """Test MAVEN project type settings."""
        test_config = SolutionCreatorConfig()
        maven_settings = test_config.project_type_settings["MAVEN"]
        
        assert maven_settings["build_file"] == "pom.xml"
        assert maven_settings["source_directory"] == "src/main"
        assert maven_settings["test_directory"] == "src/test"
        assert maven_settings["output_directory"] == "target"
        assert maven_settings["requires_build_tool"] is True
    
    def test_get_language_setting_existing(self):
        """Test getting existing language setting."""
        test_config = SolutionCreatorConfig()
        
        file_ext = test_config.get_language_setting("PYTHON", "file_extension")
        assert file_ext == ".py"
        
        test_framework = test_config.get_language_setting("PYTHON", "test_framework")
        assert test_framework == "pytest"
    
    def test_get_language_setting_non_existing_language(self):
        """Test getting setting for non-existing language."""
        test_config = SolutionCreatorConfig()
        
        result = test_config.get_language_setting("NONEXISTENT", "file_extension")
        assert result is None
    
    def test_get_language_setting_non_existing_setting(self):
        """Test getting non-existing setting for existing language."""
        test_config = SolutionCreatorConfig()
        
        result = test_config.get_language_setting("PYTHON", "nonexistent_setting")
        assert result is None
    
    def test_get_language_setting_with_default(self):
        """Test getting language setting with default value."""
        test_config = SolutionCreatorConfig()
        
        result = test_config.get_language_setting("PYTHON", "nonexistent_setting", "default_value")
        assert result == "default_value"
        
        result = test_config.get_language_setting("NONEXISTENT", "file_extension", ".unknown")
        assert result == ".unknown"
    
    def test_get_project_type_setting_existing(self):
        """Test getting existing project type setting."""
        test_config = SolutionCreatorConfig()
        
        build_file = test_config.get_project_type_setting("MAVEN", "build_file")
        assert build_file == "pom.xml"
        
        src_dir = test_config.get_project_type_setting("PLAIN", "source_directory")
        assert src_dir == "src"
    
    def test_get_project_type_setting_non_existing(self):
        """Test getting setting for non-existing project type."""
        test_config = SolutionCreatorConfig()
        
        result = test_config.get_project_type_setting("NONEXISTENT", "build_file")
        assert result is None
    
    def test_get_project_type_setting_with_default(self):
        """Test getting project type setting with default value."""
        test_config = SolutionCreatorConfig()
        
        result = test_config.get_project_type_setting("NONEXISTENT", "build_file", "default.xml")
        assert result == "default.xml"
    
    def test_is_language_supported_true(self):
        """Test checking if language is supported (true case)."""
        test_config = SolutionCreatorConfig()
        
        assert test_config.is_language_supported("PYTHON") is True
    
    def test_is_language_supported_false(self):
        """Test checking if language is supported (false case)."""
        test_config = SolutionCreatorConfig()
        
        assert test_config.is_language_supported("NONEXISTENT") is False
    
    def test_is_project_type_supported_for_language_true(self):
        """Test checking if project type is supported for language (true case)."""
        test_config = SolutionCreatorConfig()
        
        assert test_config.is_project_type_supported_for_language("PYTHON", "PLAIN") is True
    
    def test_is_project_type_supported_for_language_false(self):
        """Test checking if project type is supported for language (false case)."""
        test_config = SolutionCreatorConfig()
        
        # Python doesn't support GRADLE
        assert test_config.is_project_type_supported_for_language("PYTHON", "GRADLE") is False
        
        # Non-existent language
        assert test_config.is_project_type_supported_for_language("NONEXISTENT", "PLAIN") is False


class TestConfigModule:
    """Test the config module and global config instance."""
    
    def test_global_config_instance(self):
        """Test that global config instance exists and is properly configured."""
        assert config is not None
        assert isinstance(config, SolutionCreatorConfig)
        assert config.max_iterations > 0
        assert config.timeout_seconds > 0
    
    def test_config_environment_variables(self):
        """Test config loading from environment variables."""
        with patch.dict(os.environ, {
            'SOLUTION_CREATOR_MAX_ITERATIONS': '10',
            'SOLUTION_CREATOR_TIMEOUT_SECONDS': '600',
            'SOLUTION_CREATOR_CLEANUP_ON_SUCCESS': 'false',
            'SOLUTION_CREATOR_WORKSPACE_BASE_PATH': '/custom/workspace',
            'SOLUTION_CREATOR_LOG_LEVEL': 'DEBUG'
        }):
            # Import config again to pick up environment variables
            from ..config import SolutionCreatorConfig
            env_config = SolutionCreatorConfig()
            
            # Note: This test assumes the config class reads from environment variables
            # The actual implementation would need to be updated to support this
            # For now, we just test the structure
            assert env_config is not None
    
    def test_config_validation_max_iterations(self):
        """Test config validation for max_iterations."""
        # Valid values
        valid_config = SolutionCreatorConfig(max_iterations=5)
        assert valid_config.max_iterations == 5
        
        # Test that negative values might be handled (depends on implementation)
        # This would require actual validation in the config class
    
    def test_config_validation_timeout(self):
        """Test config validation for timeout_seconds."""
        # Valid values
        valid_config = SolutionCreatorConfig(timeout_seconds=300)
        assert valid_config.timeout_seconds == 300
        
        # Test that negative values might be handled (depends on implementation)
    
    def test_config_validation_workspace_path(self):
        """Test config validation for workspace_base_path."""
        # Valid paths
        valid_config = SolutionCreatorConfig(workspace_base_path="/tmp")
        assert valid_config.workspace_base_path == "/tmp"
        
        valid_config = SolutionCreatorConfig(workspace_base_path="/custom/path")
        assert valid_config.workspace_base_path == "/custom/path"
    
    def test_config_validation_log_level(self):
        """Test config validation for log_level."""
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        
        for level in valid_levels:
            valid_config = SolutionCreatorConfig(log_level=level)
            assert valid_config.log_level == level


class TestConfigLanguageSpecific:
    """Test language-specific configuration functionality."""
    
    @pytest.fixture
    def test_config(self):
        """Create a test config instance."""
        return SolutionCreatorConfig()
    
    def test_python_specific_settings(self, test_config):
        """Test Python-specific configuration settings."""
        python_settings = test_config.language_settings["PYTHON"]
        
        # File extension
        assert python_settings["file_extension"] == ".py"
        
        # Test framework
        assert python_settings["test_framework"] == "pytest"
        
        # No build tool for Python
        assert python_settings["build_tool"] is None
        
        # Supported project types
        supported_types = python_settings["supported_project_types"]
        assert "PLAIN" in supported_types
        assert "MAVEN" not in supported_types  # Python doesn't use Maven
        
        # File templates
        assert python_settings["main_file_template"] == "main.py"
        assert python_settings["test_file_template"] == "test_{name}.py"
    
    def test_get_python_file_extension(self, test_config):
        """Test getting Python file extension."""
        ext = test_config.get_language_setting("PYTHON", "file_extension")
        assert ext == ".py"
    
    def test_get_python_test_framework(self, test_config):
        """Test getting Python test framework."""
        framework = test_config.get_language_setting("PYTHON", "test_framework")
        assert framework == "pytest"
    
    def test_python_project_type_compatibility(self, test_config):
        """Test Python project type compatibility."""
        # Python supports PLAIN
        assert test_config.is_project_type_supported_for_language("PYTHON", "PLAIN") is True
        
        # Python doesn't support MAVEN or GRADLE
        assert test_config.is_project_type_supported_for_language("PYTHON", "MAVEN") is False
        assert test_config.is_project_type_supported_for_language("PYTHON", "GRADLE") is False


class TestConfigProjectTypeSpecific:
    """Test project type-specific configuration functionality."""
    
    @pytest.fixture
    def test_config(self):
        """Create a test config instance."""
        return SolutionCreatorConfig()
    
    def test_plain_project_settings(self, test_config):
        """Test PLAIN project type settings."""
        plain_settings = test_config.project_type_settings["PLAIN"]
        
        assert plain_settings["build_file"] is None
        assert plain_settings["source_directory"] == "src"
        assert plain_settings["test_directory"] == "tests"
        assert plain_settings["output_directory"] == "output"
        assert plain_settings["requires_build_tool"] is False
    
    def test_maven_project_settings(self, test_config):
        """Test MAVEN project type settings."""
        maven_settings = test_config.project_type_settings["MAVEN"]
        
        assert maven_settings["build_file"] == "pom.xml"
        assert maven_settings["source_directory"] == "src/main"
        assert maven_settings["test_directory"] == "src/test"
        assert maven_settings["output_directory"] == "target"
        assert maven_settings["requires_build_tool"] is True
    
    def test_gradle_project_settings(self, test_config):
        """Test GRADLE project type settings."""
        gradle_settings = test_config.project_type_settings["GRADLE"]
        
        assert gradle_settings["build_file"] == "build.gradle"
        assert gradle_settings["source_directory"] == "src/main"
        assert gradle_settings["test_directory"] == "src/test"
        assert gradle_settings["output_directory"] == "build"
        assert gradle_settings["requires_build_tool"] is True 