# Nebula

# Nebula_Transcriber

Nebula_Transcriber is a lightweight transcription service for educational videos.
It uses OpenAI Whisper locally and enriches transcripts with slide numbers detected using GPT Vision.

## Features

- Download videos from a URL.
- Extract audio and transcribe using local Whisper.
- Detect visible slide numbers in frames using GPT-4o Vision.
- Serve transcription results through a Flask API.
- Stateless: no external storage required.

## Setup Instructions

1. Clone the repository.

2. Create a `.env` file inside the `Nebula` folder with the following content:
     OPENAI_API_KEY=your-openai-api-key
     WHISPER_MODEL=base  
     LOG_LEVEL=INFO


1. Install Docker if you haven't already:
- Docker Desktop for Windows/Mac
- `sudo apt install docker.io` for Ubuntu/Linux

1. Navigate to the `transcription_docker/` directory and start the service:

cd transcription_docker/ docker compose up --build


## API Usage

### Start Transcription

- **Endpoint:** `POST http://localhost:8080/api/lecture/1/lecture-unit/2/nebula-transcriber`
- **Request Body:**
  {
  "videoUrl": "https://your.video.url/playlist.m3u8",
  "lectureId": 1,
  "lectureUnitId": 2
  }

