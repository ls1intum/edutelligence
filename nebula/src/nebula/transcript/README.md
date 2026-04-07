# Nebula Transcriber Service

This is the transcription service component of Nebula that processes lecture videos with intelligent slide detection and timestamp alignment.

## 🎯 Features

### Core Capabilities

- **Video Processing**: Process `.m3u8` lecture video streams (e.g., from TUM-Live)
- **Audio Transcription**: High-accuracy transcription using Azure Whisper or OpenAI Whisper
- **Intelligent Slide Detection**: GPT-4o Vision-based slide number recognition
- **FIFO Job Queue**: Ordered processing with First-In-First-Out guarantee
- **Two-Phase Pipeline**: Optimized separation of heavy sequential and light parallel tasks
- **Asynchronous Processing**: Non-blocking job submission with status polling
- **Stateless Design**: Horizontally scalable FastAPI service

### Advanced Features

- **Chunked Processing**: Automatic audio splitting into 180-second segments for optimal Whisper processing
- **Timestamp Alignment**: Precise slide number alignment with transcript segments
- **Frame Extraction**: Targeted extraction of slide regions from video frames
- **Retry Logic**: Robust error handling with exponential backoff
- **Temporary Storage Management**: Automatic cleanup of intermediate files
- **Job Result Caching**: 60-minute TTL for completed transcriptions

## 🏗️ Architecture

### Two-Phase Processing Pipeline

#### Phase 1: Heavy Pipeline (Sequential FIFO)

Processes one job at a time in strict order to avoid resource contention:

1. **Video Download**: Downloads `.m3u8` stream using FFmpeg
2. **Audio Extraction**: Extracts audio track from video
3. **Audio Chunking**: Splits audio into 180-second segments
4. **Whisper Transcription**: Processes audio chunks sequentially with retry logic

#### Phase 2: Light Pipeline (Parallel Per Job)

Runs in parallel for each job after heavy pipeline completes:

1. **Frame Extraction**: Extracts frames at transcript segment timestamps
2. **Frame Cropping**: Crops bottom 5% of frame (typical slide number location)
3. **GPT Vision Analysis**: Detects slide numbers using GPT-4o Vision
4. **Alignment**: Aligns detected slide numbers with transcript segments
5. **Result Storage**: Saves final transcription with metadata

### FIFO Queue System

```
┌─────────────────────────────────────────────┐
│           Job Submission                    │
│   POST /transcribe/start                    │
└──────────────┬──────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────┐
│        FIFO Job Queue                       │
│   (asyncio.Queue)                           │
│   Job 1 → Job 2 → Job 3 → ...              │
└──────────────┬──────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────┐
│     Background Worker Loop                  │
│   - Dequeues jobs in strict order          │
│   - Processes heavy pipeline sequentially   │
│   - Launches light pipeline in parallel     │
└─────────────────────────────────────────────┘
```

## 📡 API Endpoints

### Submit Transcription Job

```http
POST /transcribe/start
```

**Request Body:**

```json
{
  "videoUrl": "https://live.rbg.tum.de/w/test/12345.m3u8",
  "lectureUnitId": 456
}
```

**Response:**

```json
{
  "status": "processing",
  "transcriptionId": "550e8400-e29b-41d4-a716-446655440000"
}
```

### Check Job Status

```http
GET /transcribe/status/{job_id}
```

**Response (Processing):**

```json
{
  "status": "processing"
}
```

**Response (Completed):**

```json
{
  "status": "done",
  "lectureUnitId": 456,
  "language": "en",
  "segments": [
    {
      "startTime": 0.0,
      "endTime": 5.2,
      "text": "Welcome to today's lecture on system design.",
      "slideNumber": 1
    },
    {
      "startTime": 5.2,
      "endTime": 10.8,
      "text": "We'll cover microservices architecture patterns.",
      "slideNumber": 2
    }
  ]
}
```

**Response (Error):**

```json
{
  "status": "error",
  "error": "Failed to download video: connection timeout"
}
```

### Health Check

```http
GET /transcribe/health
```

**Response:**

```json
{
  "status": "healthy",
  "service": "transcriber"
}
```

## 🔧 System Requirements

### Required Software

- **Python 3.12+**: Primary runtime environment
- **FFmpeg**: Required for video/audio processing
  - macOS: `brew install ffmpeg`
  - Windows: Download from https://ffmpeg.org/download.html
  - Linux: `apt-get install ffmpeg` or equivalent
- **OpenCV**: Computer vision library for frame extraction (installed via Python dependencies)

### AI Service Configuration

Configure in `llm_config.yml`:

- **Azure OpenAI** or **OpenAI** credentials for Whisper
- **GPT-4o Vision** credentials for slide detection

### Storage Requirements

- **Temporary Storage**: Sufficient space for video and audio files
  - Typical: 500MB-2GB per video being processed
  - Automatically cleaned after job completion
- **Memory**: 2-4GB recommended for concurrent processing

## 🗂️ File Management

### Temporary File Handling

The service uses temporary storage with automatic cleanup:

```
temp/
├── {uuid}.mp4         # Downloaded video
├── {uuid}.mp3         # Extracted audio
└── chunks_{uuid}/     # Audio chunks for Whisper
    ├── chunk_0000.mp3
    ├── chunk_0001.mp3
    └── ...
```

**Cleanup Strategy:**

- Files are automatically deleted after job completion (success or failure)
- Job results are cached in memory with 60-minute TTL
- Temporary directory location configurable via `NEBULA_TEMP_DIR` environment variable

## 🔍 Processing Details

### Audio Chunking Strategy

- **Chunk Duration**: 180 seconds (3 minutes)
- **Reason**: Optimal for Whisper API rate limits and accuracy
- **Overlap**: None (sequential processing with proper timestamp offset)

### Slide Detection Algorithm

1. **Frame Selection**: Extracts frame at each transcript segment's start timestamp
2. **Region of Interest**: Crops bottom 5% of frame (typical slide number location)
3. **Vision Processing**: Sends cropped image to GPT-4o Vision
4. **Prompt**: "What slide number is visible? Only number, or 'Null'."
5. **Throttling**: 2-second delay between GPT Vision calls to respect rate limits

### Alignment Algorithm

For each transcript segment:

1. Look back through all detected slide timestamps
2. Find the most recent slide number at or before the segment start time
3. Assign that slide number to the segment
4. Default to slide 1 if no prior slide detected

## 🐛 Troubleshooting

### Common Issues

**404 from GPT Vision**

- Check Azure deployment name in `llm_config.yml`
- Verify API version is correct (e.g., `2024-02-15-preview`)
- Ensure GPT-4o Vision is deployed in your Azure region

**FFmpeg not found**

- Ensure FFmpeg is installed: `ffmpeg -version`
- Add to system PATH if necessary
- Restart terminal/shell after installation

**Memory issues**

- Monitor temp directory size: `du -sh temp/`
- Check Docker memory limits: increase to 4GB+
- Verify disk space availability

**Job stuck in processing**

- Check worker logs for errors
- Verify external services (Azure OpenAI, video source) are accessible
- Check rate limits on API services

**Audio transcription failures**

- Verify Whisper API credentials
- Check audio file is valid: `ffprobe {audio_file}`
- Inspect chunk files for corruption

**Slide detection inaccuracies**

- Slide numbers may be in non-standard locations
- Adjust cropping region in `video_utils.py` if needed
- Consider adding more frame extraction points

## 🚀 Development

### Local Development Setup

```bash
# Install dependencies
poetry install

# Configure LLM services
cp llm_config.example.yml llm_config.local.yml
# Edit llm_config.local.yml with your API keys

# Run service with hot reload
poetry run uvicorn nebula.transcript.app:app --host 0.0.0.0 --port 3870 --reload
```

The service will be available at `http://localhost:3870/transcribe/`

### Testing

```bash
# Submit a test job
curl -X POST http://localhost:3870/transcribe/start \
  -H "Content-Type: application/json" \
  -d '{"videoUrl": "https://example.com/video.m3u8", "lectureUnitId": 123}'

# Check job status (replace {job_id} with returned transcriptionId)
curl http://localhost:3870/transcribe/status/{job_id}
```

### Environment Variables

- `NEBULA_TEMP_DIR`: Temporary storage path (required, no default)
- `LLM_CONFIG_PATH`: LLM configuration file path (required, no default)
- `LOG_LEVEL`: Logging level (optional, default: `INFO`)

## 📊 Performance Characteristics

### Processing Times (Typical)

For a 1-hour lecture video:

- **Video Download**: 2-5 minutes (depends on network speed)
- **Audio Extraction**: 20-30 seconds
- **Whisper Transcription**: 5-10 minutes (20 chunks × 15-30 sec/chunk)
- **Frame Analysis**: 2-3 minutes (with 2-second throttling)
- **Total**: ~10-20 minutes

### Scalability

- **Horizontal Scaling**: Service is stateless and can be replicated
- **Queue-based Processing**: Natural scaling point for worker processes
- **Bottlenecks**: External API rate limits (Whisper, GPT Vision)

## 🔗 Integration

### External Services

- **TUM-Live**: Source of `.m3u8` video streams
- **Azure OpenAI**: Whisper transcription and GPT-4o Vision
- **OpenAI**: Alternative provider for Whisper and GPT-4o

### Internal Services

- **Nginx Gateway**: API authentication and routing
- **FAQ Service**: Sibling service in Nebula ecosystem

## 📝 See Also

- [Main Nebula README](../../../README.md) - Complete setup and deployment guide
