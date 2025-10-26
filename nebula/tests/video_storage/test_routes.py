"""
Tests for video storage routes
"""

# pylint: disable=redefined-outer-name,unused-argument
import io

from fastapi.testclient import TestClient

from nebula.video_storage.app import app


def test_upload_video_success(temp_storage_dir, sample_video_content):
    """Test successful video upload"""
    client = TestClient(app)

    # Create a file-like object
    files = {
        "file": (
            "test_video.mp4",
            io.BytesIO(sample_video_content),
            "video/mp4",
        )
    }

    response = client.post("/video-storage/upload", files=files)
    assert response.status_code == 201
    data = response.json()
    assert "video_id" in data
    assert data["filename"] == "test_video.mp4"
    assert data["size_bytes"] == len(sample_video_content)
    assert data["message"] == "Video uploaded successfully"


def test_upload_video_invalid_type(temp_storage_dir):
    """Test upload with invalid file type"""
    client = TestClient(app)

    # Try to upload a text file
    invalid_content = b"This is not a video"
    files = {"file": ("test.txt", io.BytesIO(invalid_content), "text/plain")}

    response = client.post("/video-storage/upload", files=files)
    assert response.status_code == 400


def test_stream_video(temp_storage_dir, sample_video_content):
    """Test streaming a video"""
    client = TestClient(app)

    # First upload a video
    files = {
        "file": (
            "test_video.mp4",
            io.BytesIO(sample_video_content),
            "video/mp4",
        )
    }
    upload_response = client.post("/video-storage/upload", files=files)
    video_id = upload_response.json()["video_id"]

    # Now stream it
    stream_response = client.get(f"/video-storage/stream/{video_id}")
    assert stream_response.status_code == 200
    assert stream_response.content == sample_video_content


def test_stream_nonexistent_video(temp_storage_dir):
    """Test streaming a video that doesn't exist"""
    client = TestClient(app)

    response = client.get("/video-storage/stream/nonexistent-id")
    assert response.status_code == 404


def test_download_video(temp_storage_dir, sample_video_content):
    """Test downloading a video"""
    client = TestClient(app)

    # First upload a video
    files = {
        "file": (
            "test_video.mp4",
            io.BytesIO(sample_video_content),
            "video/mp4",
        )
    }
    upload_response = client.post("/video-storage/upload", files=files)
    video_id = upload_response.json()["video_id"]

    # Now download it
    download_response = client.get(f"/video-storage/download/{video_id}")
    assert download_response.status_code == 200
    assert download_response.content == sample_video_content


def test_get_video_info(temp_storage_dir, sample_video_content):
    """Test getting video info"""
    client = TestClient(app)

    # First upload a video
    files = {
        "file": (
            "test_video.mp4",
            io.BytesIO(sample_video_content),
            "video/mp4",
        )
    }
    upload_response = client.post("/video-storage/upload", files=files)
    video_id = upload_response.json()["video_id"]

    # Get info
    info_response = client.get(f"/video-storage/info/{video_id}")
    assert info_response.status_code == 200
    data = info_response.json()
    assert data["video_id"] == video_id
    assert data["filename"] == "test_video.mp4"
    assert data["content_type"] == "video/mp4"
    assert data["size_bytes"] == len(sample_video_content)
    assert "stream_url" in data


def test_list_videos(temp_storage_dir, sample_video_content):
    """Test listing videos"""
    client = TestClient(app)

    # Initially should be empty
    response = client.get("/video-storage/list")
    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 0
    assert len(data["videos"]) == 0

    # Upload some videos
    for i in range(3):
        files = {
            "file": (
                f"video{i}.mp4",
                io.BytesIO(sample_video_content),
                "video/mp4",
            )
        }
        client.post("/video-storage/upload", files=files)

    # List again
    response = client.get("/video-storage/list")
    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 3
    assert len(data["videos"]) == 3


def test_delete_video(temp_storage_dir, sample_video_content):
    """Test deleting a video"""
    client = TestClient(app)

    # First upload a video
    files = {
        "file": (
            "test_video.mp4",
            io.BytesIO(sample_video_content),
            "video/mp4",
        )
    }
    upload_response = client.post("/video-storage/upload", files=files)
    video_id = upload_response.json()["video_id"]

    # Delete it
    delete_response = client.delete(f"/video-storage/delete/{video_id}")
    assert delete_response.status_code == 204

    # Verify it's gone
    info_response = client.get(f"/video-storage/info/{video_id}")
    assert info_response.status_code == 404


def test_delete_nonexistent_video(temp_storage_dir):
    """Test deleting a video that doesn't exist"""
    client = TestClient(app)

    response = client.delete("/video-storage/delete/nonexistent-id")
    assert response.status_code == 404
