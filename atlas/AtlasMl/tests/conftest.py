import os
from pathlib import Path

# Set environment variables before any other imports
test_dir = Path(__file__).parent
test_config_path = test_dir / "test_config.yml"
os.environ["APPLICATION_YML_PATH"] = str(test_config_path)
os.environ["TESTING"] = "true"

import pytest
from unittest.mock import patch
import logging
import asyncio

logger = logging.getLogger(__name__)

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

logger = logging.getLogger(__name__)

@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()

@pytest.fixture(autouse=True)
def test_env():
    """Setup test environment variables and configuration"""
    # Mock only os.environ.get
    original_get = os.environ.get
    def mock_get(key, default=None):
        if key == "APPLICATION_YML_PATH":
            return str(test_config_path)
        return original_get(key, default)
    
    os.environ.get = mock_get
    
    yield
    
    # Restore original get method
    os.environ.get = original_get
    
    # Cleanup after tests
    os.environ.pop("TESTING", None)
    

@pytest.fixture(autouse=True)
def mock_generate_embeddings_openai():
    with patch("atlasml.ml.VectorEmbeddings.MainEmbeddingModel.generate_embeddings_openai", return_value=[0.1, 0.2, 0.3]):
        yield