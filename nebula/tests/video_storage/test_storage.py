"""
Tests for video storage service
"""

# pylint: disable=redefined-outer-name,unused-argument


def test_storage_service_initialization(storage_service):
    """Test that storage service initializes correctly"""
    assert storage_service is not None
    assert storage_service.storage_dir.exists()


def test_generate_video_id(storage_service):
    """Test video ID generation"""
    video_id = storage_service.generate_video_id()
    assert video_id is not None
    assert len(video_id) > 0
    assert isinstance(video_id, str)

    # Generate another and ensure they're different
    video_id2 = storage_service.generate_video_id()
    assert video_id != video_id2


def test_save_video(storage_service, sample_video_content):
    """Test saving a video"""
    metadata = storage_service.save_video(
        video_data=sample_video_content,
        filename="test_video.mp4",
        content_type="video/mp4",
    )

    assert metadata is not None
    assert metadata.video_id is not None
    assert metadata.filename == "test_video.mp4"
    assert metadata.content_type == "video/mp4"
    assert metadata.size_bytes == len(sample_video_content)
    assert metadata.uploaded_at is not None


def test_get_video_path(storage_service, sample_video_content):
    """Test getting video path"""
    # Save a video first
    metadata = storage_service.save_video(
        video_data=sample_video_content,
        filename="test_video.mp4",
        content_type="video/mp4",
    )

    # Get the path
    video_path = storage_service.get_video_path(metadata.video_id)
    assert video_path is not None
    assert video_path.exists()
    assert video_path.name == "test_video.mp4"

    # Test with non-existent video
    non_existent_path = storage_service.get_video_path("non-existent-id")
    assert non_existent_path is None


def test_get_metadata(storage_service, sample_video_content):
    """Test getting video metadata"""
    # Save a video first
    metadata = storage_service.save_video(
        video_data=sample_video_content,
        filename="test_video.mp4",
        content_type="video/mp4",
    )

    # Get metadata
    retrieved_metadata = storage_service.get_metadata(metadata.video_id)
    assert retrieved_metadata is not None
    assert retrieved_metadata.video_id == metadata.video_id
    assert retrieved_metadata.filename == metadata.filename
    assert retrieved_metadata.content_type == metadata.content_type
    assert retrieved_metadata.size_bytes == metadata.size_bytes

    # Test with non-existent video
    non_existent_metadata = storage_service.get_metadata("non-existent-id")
    assert non_existent_metadata is None


def test_list_videos(storage_service, sample_video_content):
    """Test listing videos"""
    # Initially should be empty
    videos = storage_service.list_videos()
    assert len(videos) == 0

    # Save some videos
    metadata1 = storage_service.save_video(
        video_data=sample_video_content,
        filename="video1.mp4",
        content_type="video/mp4",
    )
    metadata2 = storage_service.save_video(
        video_data=sample_video_content,
        filename="video2.mp4",
        content_type="video/mp4",
    )

    # List videos
    videos = storage_service.list_videos()
    assert len(videos) == 2
    video_ids = [v.video_id for v in videos]
    assert metadata1.video_id in video_ids
    assert metadata2.video_id in video_ids


def test_delete_video(storage_service, sample_video_content):
    """Test deleting a video"""
    # Save a video first
    metadata = storage_service.save_video(
        video_data=sample_video_content,
        filename="test_video.mp4",
        content_type="video/mp4",
    )

    # Verify it exists
    assert storage_service.video_exists(metadata.video_id)

    # Delete it
    success = storage_service.delete_video(metadata.video_id)
    assert success is True

    # Verify it's gone
    assert not storage_service.video_exists(metadata.video_id)
    assert storage_service.get_video_path(metadata.video_id) is None

    # Try deleting non-existent video
    success = storage_service.delete_video("non-existent-id")
    assert success is False


def test_video_exists(storage_service, sample_video_content):
    """Test checking if video exists"""
    # Non-existent video
    assert not storage_service.video_exists("non-existent-id")

    # Save a video
    metadata = storage_service.save_video(
        video_data=sample_video_content,
        filename="test_video.mp4",
        content_type="video/mp4",
    )

    # Should exist
    assert storage_service.video_exists(metadata.video_id)
