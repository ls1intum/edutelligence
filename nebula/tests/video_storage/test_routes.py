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
    assert "playlist_url" in data
    assert data["playlist_url"].endswith("/playlist.m3u8")
    assert "duration_seconds" in data
    assert "message" in data


def test_upload_video_invalid_type(temp_storage_dir):
    """Test upload with invalid file type"""
    client = TestClient(app)

    # Try to upload a text file
    invalid_content = b"This is not a video"
    files = {"file": ("test.txt", io.BytesIO(invalid_content), "text/plain")}

    response = client.post("/video-storage/upload", files=files)
    assert response.status_code == 400


def test_get_playlist(temp_storage_dir, sample_video_content):
    """Test getting HLS playlist"""
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

    # Get the playlist
    playlist_response = client.get(f"/video-storage/playlist/{video_id}/playlist.m3u8")
    assert playlist_response.status_code == 200
    assert playlist_response.headers["content-type"] == "application/vnd.apple.mpegurl"
    # Verify it's a valid m3u8 file
    content = playlist_response.content.decode("utf-8")
    assert "#EXTM3U" in content


def test_get_playlist_nonexistent_video(temp_storage_dir):
    """Test getting playlist for a video that doesn't exist"""
    client = TestClient(app)

    response = client.get("/video-storage/playlist/nonexistent-id/playlist.m3u8")
    assert response.status_code == 404


def test_get_segment(temp_storage_dir, sample_video_content):
    """Test getting HLS segment"""
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

    # Get the playlist to see what segments exist
    playlist_response = client.get(f"/video-storage/playlist/{video_id}/playlist.m3u8")
    assert playlist_response.status_code == 200

    # Parse playlist to find a segment name
    content = playlist_response.content.decode("utf-8")
    # Look for .ts files in the playlist
    lines = content.split("\n")
    segment_name = None
    for line in lines:
        if line.endswith(".ts"):
            segment_name = line.strip()
            break

    if segment_name:
        # Get the segment
        segment_response = client.get(
            f"/video-storage/playlist/{video_id}/{segment_name}"
        )
        assert segment_response.status_code == 200
        assert segment_response.headers["content-type"] == "video/mp2t"


def test_get_segment_nonexistent(temp_storage_dir):
    """Test getting a segment that doesn't exist"""
    client = TestClient(app)

    response = client.get("/video-storage/playlist/nonexistent-id/segment000.ts")
    assert response.status_code == 404


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

    # Verify it's gone by checking that the playlist no longer exists
    playlist_response = client.get(f"/video-storage/playlist/{video_id}/playlist.m3u8")
    assert playlist_response.status_code == 404


def test_delete_nonexistent_video(temp_storage_dir):
    """Test deleting a video that doesn't exist"""
    client = TestClient(app)

    response = client.delete("/video-storage/delete/nonexistent-id")
    assert response.status_code == 404
