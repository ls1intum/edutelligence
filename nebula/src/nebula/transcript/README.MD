# Nebula_Transcriber

Nebula_Transcriber is a lightweight transcription service for educational videos.  
It uses **Whisper** (Azure or local) for audio transcription and **GPT-4o Vision** to detect visible slide numbers from video frames.

---

## ✨ Features

- 🎥 Process `.m3u8` lecture video URLs (e.g., from TUM-Live)
- 🧠 Transcribe audio using local or Azure Whisper
- 👁️ Detect slide numbers via GPT-4o Vision (Azure)
- ⚡ Stateless and fast — no database or external storage
- 🚀 Exposes a clean **FastAPI** interface

---

## 🧪 Local Development Setup

```bash
git clone https://github.com/ls1intum/edutelligence.git
cd edutelligence
git checkout feature/transcript
cd nebula
```

### Python Installation

Ensure Python version `>=3.10,<3.13` is installed.
You can check with:
```bash
python --version
```
If needed, install from https://www.python.org/downloads/

---

## 📦 Poetry-Based Setup

We use [Poetry](https://python-poetry.org/) for dependency and virtual environment management.

### Install Poetry (if not installed)
```bash
pip install poetry
```

### Install Dependencies
```bash
poetry install
```


## 🛠 FFmpeg Installation

FFmpeg is required for video/audio processing.

### Windows
- Download from https://ffmpeg.org/download.html (or use chocolatey: `choco install ffmpeg`)
- Ensure `ffmpeg.exe` is added to your system `PATH`

### macOS
```bash
brew install ffmpeg
```

---

## 🔧 Configuration Files

### Create `llm_config.nebula.yml`
Copy `llm_config.example.yml` and add your keys:

```yaml
- id: azure-gpt-4o
  type: azure_chat
  api_key: <your-gpt-api-key>
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

### Create `application_local.nebula.yml`
Copy from `application_local.example.nebula.yml`

---
### Run App
Set environment variables and run:

#### Windows PowerShell
```powershell
$env:APPLICATION_YML_PATH = "./application_local.nebula.yml"
$env:LLM_CONFIG_PATH = "./llm_config.nebula.yml"
poetry run uvicorn src.nebula.transcript.app:app --reload --port 5000
```

#### macOS / Linux
```bash
export APPLICATION_YML_PATH=./application_local.nebula.yml
export LLM_CONFIG_PATH=./llm_config.nebula.yml
poetry run uvicorn src.nebula.transcript.app:app --reload --port 5000
```

---

## 🐳 Docker Setup

> Docker setup is isolated inside the `docker/transcript/` folder.

```bash
cd docker/transcript
docker compose up --build
```

Make sure these files are present or mounted in the container:
- `llm_config.nebula.yml`
- `application_local.nebula.yml`

---

## 📡 API Usage

**POST** `/api/lecture/{lectureId}/lecture-unit/{lectureUnitId}/nebula-transcriber`

```json
{
  "videoUrl": "https://your.video.url/playlist.m3u8",
  "lectureId": 1,
  "lectureUnitId": 2
}
```

---

## 🎓 Getting a TUM-Live `.m3u8` Link

1. Open [https://live.rbg.tum.de](https://live.rbg.tum.de)
2. Open DevTools → Network tab → Filter by `.m3u8`
3. Copy full link (including `jwt`)
4. Use in `videoUrl`

---

## 🧹 Temporary Files

- Stored in `./temp` by default
- Automatically removed after transcription
- Configurable via `.env`

---

## 📁 Project Structure

```
nebula/
├── src/
│   └── nebula/
│       ├── transcript/
│       │   ├── app.py
│       │   ├── slide_utils.py
│       │   ├── whisper_utils.py
│       │   ├── llm_utils.py
│       │   ├── config.py
│       ├── health.py
│       ├── security.py
├── application_local.nebula.yml
├── llm_config.nebula.yml
├── docker/
│   └── transcript/
│       ├── docker-compose.yml
│       └── requirements.txt
└── temp/
```

---

## 🛠 Troubleshooting

- 404 from GPT Vision: Check Azure deployment name and API version
- FFmpeg error: Ensure it's installed and on PATH
- `proxies` error: Use OpenAI SDK version ≤ `1.55.3`
