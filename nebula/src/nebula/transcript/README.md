# Nebula Transcriber Service

This is the transcription service component of Nebula that processes lecture videos.

## Features

- Process `.m3u8` lecture video URLs (e.g., from TUM-Live)
- Transcribe audio using Azure Whisper
- Detect slide numbers via GPT-4o Vision (Azure)
- Async background job processing via polling
- Stateless FastAPI service

## Setup & Deployment

See the [main README](../../../README.md) for complete setup and deployment instructions.

## API Endpoints

### Health Check

```
GET /transcribe/health
```

### Submit Transcription Job

```
POST /transcribe/submit
```

Request body:

```json
{
  "video_url": "https://example.com/video.m3u8",
  "metadata": {
    "lecture_id": 123,
    "lecture_unit_id": 456
  }
}
```

### Check Job Status

```
GET /transcribe/status/{job_id}
```

### Get Job Result

```
GET /transcribe/result/{job_id}
```

## System Requirements

- **FFmpeg**: Required for video/audio processing

  - macOS: `brew install ffmpeg`
  - Windows: Download from https://ffmpeg.org/download.html
  - Linux: `apt-get install ffmpeg` or equivalent

- **Tesseract OCR**: Required for text extraction from slides
  - macOS: `brew install tesseract`
  - Linux: `apt-get install tesseract-ocr`

## Temp File Handling

- Temporary files are stored in `./temp` directory
- Files are automatically cleaned up after job completion
- Controlled by environment variable or config

## Troubleshooting

- **404 from GPT Vision**: Check Azure deployment name and API version in llm_config
- **FFmpeg not found**: Ensure ffmpeg is installed and in system PATH
- **Memory issues**: Monitor temp directory size, increase Docker memory limits if needed
- **Timeout errors**: Long videos may exceed default timeouts, adjust proxy settings

## Development

For local development without Docker:

```bash
poetry run uvicorn nebula.transcript.app:app --host 0.0.0.0 --port 3870 --reload
```

The service will be available at http://localhost:3870/transcribe/
