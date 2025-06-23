# 🧠 Nebula Transcriber

Nebula is a lightweight, modular transcription system that powers automated lecture transcription for Artemis using **Whisper** and **GPT-4o Vision**. It includes two components:

- 🎯 **Transcriber**: Transcribes `.m3u8` lecture videos, detects slide numbers
- 🚪 **Gateway**: Provides an authenticated API layer for Artemis integration

---

## ✨ Features

- 🎥 Process `.m3u8` lecture video URLs (e.g., from TUM-Live)
- 🧠 Transcribe audio using **Azure Whisper**
- 👁️ Detect slide numbers via **GPT-4o Vision** (Azure)
- 🔁 Async background job processing via polling
- ✅ Clean FastAPI interface, Docker-ready, stateless

---

## 🧪 Local Development Setup

```bash
git clone https://github.com/ls1intum/edutelligence.git
cd edutelligence/nebula
```

### Python Installation

Ensure Python version `>=3.10,<3.13` is installed:

```bash
python --version
```

---

## 📦 Poetry Setup

We use [Poetry](https://python-poetry.org/) for dependency and environment management.

```bash
pip install poetry
poetry install
```

---

## 🛠 FFmpeg Installation

FFmpeg is required for video/audio processing.

### Windows

- Download from https://ffmpeg.org/download.html (or use chocolatey: choco install ffmpeg)
- Ensure ffmpeg.exe is added to your system PATH

### macOS

```bash
brew install ffmpeg
```

---

## 🔧 Configuration

### 1. `application_local.nebula.yml`

-Copy from application_local.example.nebula.yml
+Copy from `nebula/application_local.example.nebula.yml` to `nebula/application_local.nebula.yml`

### 2. `llm_config.nebula.yml`

-Copy llm_config.example.yml and add your keys:
+Copy `nebula/llm_config.example.yml` to `nebula/llm_config.nebula.yml` and add your keys:

```yaml
- id: azure-gpt-4o
  type: azure_chat
  api_key: <your-api-key>
  api_version: 2024-02-15-preview
  azure_deployment: gpt-4o
  endpoint: https://<your-endpoint>.openai.azure.com/

- id: azure-whisper
  type: azure_whisper
  api_key: <your-whisper-api-key>
  api_version: 2024-06-01
  azure_deployment: whisper
  endpoint: https://<your-endpoint>.openai.azure.com/
```

---

## ▶️ Running Locally

```bash
# Set environment variable

### Windows PowerShell
$env:APPLICATION_YML_PATH = "./application_local.nebula.yml"
$env:LLM_CONFIG_PATH = "./llm_config.nebula.yml"
$env:TRANSCRIBE_SERVICE_URL = "http://localhost:5000"

### macOS / Linux
export APPLICATION_YML_PATH=./application_local.nebula.yml
export LLM_CONFIG_PATH=./llm_config.nebula.yml
export TRANSCRIBE_SERVICE_URL=http://localhost:5000

# Run the transcription service
poetry run uvicorn nebula.transcript.app:app --reload --port 5000

# In a separate terminal, run the gateway
poetry run uvicorn nebula.gateway.main:app --reload --port 8000

```

---

## 🐳 Docker

```bash
cd nebula
docker compose up --build
```

Make sure to mount both `.yml` config files inside the container.

---

## 📁 Project Structure

```
nebula/
├── docker/
│   └── transcript/
│       └── Dockerfile
├── src/
│   ├── gateway/
│   │   ├── main.py
│   │   ├── security.py
│   │   └── routes/
│   │       └── transcribe.py
│   └── nebula/
│       ├── __init__.py
│       ├── main.py
│       ├── health.py
│       └── transcript/
│           ├── app.py
│           ├── audio_utils.py
│           ├── align_utils.py
│           ├── config.py
│           ├── dto.py
│           ├── jobs.py
│           ├── llm_utils.py
│           ├── slide_utils.py
│           ├── video_utils.py
│           └── whisper_utils.py
├── temp/  # Temporary files
├── application_local.nebula.yml
├── llm_config.nebula.yml
└── pyproject.toml
```

---

## 📡 API Usage (via Artemis)

**POST** `/api/lecture/{lectureId}/lecture-unit/{lectureUnitId}/nebula-transcriber`

```json
{
  "videoUrl": "https://your.video.url/playlist.m3u8",
  "lectureId": 1,
  "lectureUnitId": 2
}
```

---

## 🧹 Temp File Handling

- Stored under `./temp`
- Removed automatically after job completion
- Controlled by `Config.VIDEO_STORAGE_PATH`

---

## 🛠 Troubleshooting

- ❌ **404 from GPT Vision**: Check Azure deployment + API version
- ❌ **FFmpeg not found**: Ensure installed and in PATH
- 🧪 **OpenAI errors**: Use SDK ≤ `1.55.3`

---
