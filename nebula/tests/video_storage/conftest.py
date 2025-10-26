"""
Test configuration and fixtures for video storage tests
"""

import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from nebula.video_storage.app import app
from nebula.video_storage.config import Config
from nebula.video_storage.storage import VideoStorageService


@pytest.fixture
def temp_storage_dir():
    """Create a temporary directory for video storage"""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Override the storage directory
        original_dir = Config.STORAGE_DIR
        Config.STORAGE_DIR = tmpdir
        yield Path(tmpdir)
        # Restore original
        Config.STORAGE_DIR = original_dir


@pytest.fixture
def temp_dir():
    """Create a temporary directory for temp files"""
    with tempfile.TemporaryDirectory() as tmpdir:
        original_dir = Config.TEMP_DIR
        Config.TEMP_DIR = tmpdir
        yield Path(tmpdir)
        Config.TEMP_DIR = original_dir


@pytest.fixture
def storage_service(temp_storage_dir):
    """Create a storage service instance with temp directory"""
    return VideoStorageService()


@pytest.fixture
def client():
    """Create a test client for the FastAPI app"""
    return TestClient(app)


@pytest.fixture
def sample_video_content():
    """Create sample video content (fake video data)"""
    return b"FAKE VIDEO DATA - This is not a real video " b"but serves as test data"


@pytest.fixture
def sample_video_file(tmp_path, sample_video_content):
    """Create a sample video file"""
    video_file = tmp_path / "test_video.mp4"
    video_file.write_bytes(sample_video_content)
    return video_file
