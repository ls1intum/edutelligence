import pytest
import os
from pathlib import Path
from unittest.mock import patch
import logging

logger = logging.getLogger(__name__)

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

logger = logging.getLogger(__name__)

@pytest.fixture(autouse=True)
def test_env():
    """Setup test environment variables and configuration"""
    # Set test environment
    os.environ["TESTING"] = "true"
    
    # Mock settings with test API keys
    with patch('atlasml.dependencies.settings') as mock_settings:
        mock_settings.get_api_keys.return_value = ["secret-token"]
        yield
    
    # Cleanup after tests
    os.environ.pop("TESTING", None)
    