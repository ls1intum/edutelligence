# Video Storage Service

A microservice for video upload and HLS streaming, built for Artemis integration with the Nebula platform.

## Overview

The Video Storage Service provides HLS (HTTP Live Streaming) video storage and streaming. It follows a **separation of concerns** architecture where:

- **Artemis** stores all business logic and metadata (titles, courses, permissions)
- **Nebula Video Storage** only handles video files and streaming

## Quick Start

### Run Locally

```bash
cd nebula

# Terminal 1 - Start Video Storage Service
poetry run uvicorn nebula.video_storage.app:app --host 0.0.0.0 --port 3872 --reload

# Terminal 2 - Start Nginx Gateway
docker compose -f docker/nginx-only.yml up
```

### Run with Docker

```bash
cd nebula
docker compose -f docker/nebula-local.yml up --build
```

### Test the Service

```bash
# Health check
curl http://localhost:3007/video-storage/health

# Upload a video
curl -X POST http://localhost:3007/video-storage/upload \
  -H "Authorization: nebula-secret" \
  -F "file=@test_video.mp4"
```

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    ARTEMIS (Source of Truth)                │
│                                                             │
│  Stores:                                                    │
│  ✅ Video metadata (title, description)                    │
│  ✅ Course/lecture relationships                           │
│  ✅ User permissions                                        │
│  ✅ Business logic                                          │
│                                                             │
│  Database: videos table with nebula_video_id               │
└─────────────────────────────────────────────────────────────┘
                        │
                        │ API Calls
                        ▼
┌─────────────────────────────────────────────────────────────┐
│              NEBULA VIDEO STORAGE (File Store)              │
│                                                             │
│  Stores:                                                    │
│  ✅ Video files (.mp4)                                     │
│  ✅ HLS playlists (.m3u8)                                  │
│  ✅ HLS segments (.ts)                                     │
│                                                             │
│  Handles:                                                   │
│  ✅ Video conversion to HLS                                │
│  ✅ Video streaming                                         │
│  ✅ File management                                         │
└─────────────────────────────────────────────────────────────┘
```

## API Endpoints

### 1. Upload Video

```bash
POST /video-storage/upload
```

Upload a video and convert it to HLS format. Returns `playlist_url` that Artemis should store.

**Request:**

```bash
curl -X POST http://localhost:3007/video-storage/upload \
  -H "Authorization: nebula-secret" \
  -F "file=@video.mp4"
```

**Response:**

```json
{
  "video_id": "550e8400-e29b-41d4-a716-446655440000",
  "filename": "video.mp4",
  "size_bytes": 104857600,
  "uploaded_at": "2024-01-15T10:30:00Z",
  "playlist_url": "/video-storage/playlist/550e8400.../playlist.m3u8",
  "duration_seconds": 125.5,
  "message": "Video uploaded and converted to HLS successfully"
}
```

**Artemis should store:** `video_id`, `playlist_url`, `duration_seconds` in its database.

### 2. Get HLS Playlist

```bash
GET /video-storage/playlist/{video_id}/playlist.m3u8
```

Get the HLS playlist for streaming. Called by the video player using the `playlist_url` stored in Artemis.

**Request:**

```bash
curl -H "Authorization: nebula-secret" \
  http://localhost:3007/video-storage/playlist/550e8400.../playlist.m3u8
```

**Response:** HLS playlist file (`.m3u8`)

### 3. Get HLS Segment

```bash
GET /video-storage/playlist/{video_id}/{segment_name}
```

Get video segments. Called automatically by the video player - not called directly by Artemis.

### 4. Delete Video

```bash
DELETE /video-storage/delete/{video_id}
```

Delete a video and all associated files. Called by Artemis when removing a video.

**Request:**

```bash
curl -X DELETE \
  -H "Authorization: nebula-secret" \
  http://localhost:3007/video-storage/delete/550e8400...
```

**Response:** `204 No Content`

**Note:** Artemis should also delete its database entry after calling this.

### 5. Health Check

```bash
GET /video-storage/health
```

## Storage Structure

```
video_storage/
└── {video_id}/
    ├── video.mp4              # Original uploaded video
    ├── metadata.json          # Basic metadata
    └── hls/                   # HLS streaming files
        ├── playlist.m3u8      # HLS playlist
        ├── segment000.ts      # Video segment 1
        ├── segment001.ts      # Video segment 2
        └── ...
```

## HLS (HTTP Live Streaming)

### Why HLS?

- ✅ **Artemis Compatible** - Works with `.m3u8` playlists
- ✅ **Adaptive Streaming** - Adjusts to network conditions
- ✅ **Seekable** - Jump to any point in the video
- ✅ **Standard** - Works in all modern browsers
- ✅ **Efficient** - Segments enable better caching

### HLS Configuration

Videos are automatically converted with:

- **Video Codec:** H.264 (libx264)
- **Audio Codec:** AAC
- **Video Bitrate:** 2 Mbps
- **Audio Bitrate:** 128 kbps
- **Segment Duration:** 10 seconds
- **Format:** MPEG-TS (.ts) segments

### Conversion Process

1. Upload video (any format: MP4, AVI, MOV, MKV, WebM, FLV, WMV)
2. FFmpeg converts to HLS format
3. Creates `.m3u8` playlist and `.ts` segments
4. Extracts video duration
5. Returns `playlist_url` for Artemis

## Supported Video Formats

| Format        | Extension | MIME Type          |
| ------------- | --------- | ------------------ |
| MP4           | `.mp4`    | `video/mp4`        |
| AVI           | `.avi`    | `video/x-msvideo`  |
| QuickTime     | `.mov`    | `video/quicktime`  |
| Matroska      | `.mkv`    | `video/x-matroska` |
| WebM          | `.webm`   | `video/webm`       |
| Flash Video   | `.flv`    | `video/x-flv`      |
| Windows Media | `.wmv`    | `video/x-ms-wmv`   |

All formats are automatically converted to HLS for streaming.

## Docker Deployment

### Build

```bash
docker build -t video-storage-service \
  -f nebula/docker/video_storage/Dockerfile .
```

### Run

```bash
docker run -d \
  -p 3872:3872 \
  -v $(pwd)/video_storage:/app/video_storage \
  -e VIDEO_STORAGE_DIR=/app/video_storage \
  -e LOG_LEVEL=INFO \
  video-storage-service
```

### Docker Compose

Already configured in `nebula/docker/nebula.yml`:

```yaml
video_storage:
  build:
    context: ../..
    dockerfile: ./nebula/docker/video_storage/Dockerfile
  container_name: video-storage-service
  expose:
    - "3872"
  volumes:
    - video_storage_data:/app/video_storage
```

## Testing

### Run Tests

```bash
cd nebula
poetry run pytest tests/video_storage/ -v
```

### Test Coverage

```bash
poetry run pytest tests/video_storage/ \
  --cov=nebula.video_storage \
  --cov-report=html
```

### Manual Testing

```bash
# 1. Upload
RESPONSE=$(curl -X POST http://localhost:3007/video-storage/upload \
  -H "Authorization: nebula-secret" \
  -F "file=@test.mp4")

VIDEO_ID=$(echo $RESPONSE | jq -r '.video_id')
echo "Uploaded: $VIDEO_ID"

# 2. Get playlist
curl http://localhost:3007/video-storage/playlist/$VIDEO_ID/playlist.m3u8

# 3. Delete
curl -X DELETE http://localhost:3007/video-storage/delete/$VIDEO_ID \
  -H "Authorization: nebula-secret"
```

## Troubleshooting

### Video Upload Fails

**Issue:** 413 Request Entity Too Large

**Solution:**

- File exceeds 5GB limit
- Increase `MAX_VIDEO_SIZE` environment variable
- Update nginx `client_max_body_size`

### Video Conversion Fails

**Issue:** FFmpeg error during HLS conversion

**Solution:**

- Check FFmpeg is installed: `ffmpeg -version`
- Check video file is not corrupted
- Check disk space available
- Review logs: `docker logs video-storage-service`

### Playlist Not Found

**Issue:** 404 when requesting playlist

**Solution:**

- Check video was uploaded successfully
- Verify HLS conversion completed
- Check `video_id` is correct
- Ensure storage volume is mounted

### Connection Refused

**Issue:** Cannot connect to service

**Solution:**

- Verify service is running: `curl http://localhost:3872/video-storage/health`
- Check Docker container: `docker ps | grep video-storage`
- Verify nginx is routing correctly
- Check firewall settings

## Monitoring

### Health Check

```bash
# Service health
curl http://localhost:3007/video-storage/health

# Full system health (includes all Nebula services)
curl http://localhost:3007/health
```

### Logs

```bash
# Docker logs
docker logs video-storage-service -f

# Local development - logs appear in terminal
```

### Metrics

Monitor:

- Storage usage: `du -sh nebula/video_storage`
- Video count: `ls nebula/video_storage | wc -l`
- Conversion time: Check logs for timing

## Security

1. **Authentication:** All endpoints require API key (except health check)
2. **File Validation:** Only allowed video formats accepted
3. **Size Limits:** Maximum 5GB per video
4. **MIME Type Validation:** Strict content type checking
5. **CORS:** Enabled for streaming endpoints

## Performance

- **Upload:** Supports files up to 5GB
- **Conversion:** ~1-2 minutes per hour of video
- **Streaming:** HLS segments (10 seconds each)
- **Storage:** File-based with persistent Docker volumes
- **Concurrency:** FastAPI async for multiple requests

## Key Principles

1. **Artemis is the source of truth** for all metadata
2. **Nebula only stores files** - no business logic
3. **Upload returns playlist_url** - Artemis stores this
4. **Playback uses stored URL** - no additional lookups needed
5. **Delete from both** - Nebula files + Artemis database

## Development

### Project Structure

```
video_storage/
├── __init__.py
├── app.py                 # FastAPI application
├── config.py              # Configuration
├── dto.py                 # Data models (Pydantic)
├── storage.py             # Storage service logic
└── routes/
    └── video_routes.py    # API endpoints
```

### Adding Features

When adding new features:

1. Keep separation of concerns (Artemis = metadata, Nebula = files)
2. Update this README
3. Add tests in `tests/video_storage/`
4. Update integration examples if API changes

## Support

For issues or questions:

- Check troubleshooting section above
- Review error logs: `docker logs video-storage-service`
- Test with curl commands to isolate issues
- Verify Artemis integration code matches examples
