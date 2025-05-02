# Nebula_Transcriber

Nebula_Transcriber is a lightweight transcription service for educational videos.  
It uses **Whisper** locally for audio transcription and **GPT-4o Vision** to detect visible slide numbers from video frames.

---

## ✨ Features

- 🎥 Download and process videos from a `.m3u8` playlist URL (e.g., from TUM-Live).
- 🧠 Transcribe audio using local OpenAI Whisper models.
- 👁️ Detect slide numbers using GPT-4o Vision from selected video frames.
- ⚡ Fast and stateless — no external storage, no database.
- 🌍 Exposes a simple Flask API.

---

## 🧪 Local Development Setup

### 1. Clone the Repository

```bash
git clone https://github.com/ls1intum/edutelligence.git
go to nebula/feature/transcript branch
cd nebula/transcript
```

### 2–6. Environment Setup, Config, and Running

```bash
# (Optional) Create and activate a virtual environment
python -m venv .venv
.venv\Scripts\activate         # on Windows
source .venv/bin/activate        # on Unix/Mac

# Install required dependencies
pip install -r requirements.txt

# Create a file named `llm_config.nebula.yml` in the root directory with this structure:
```

```yaml
- id: azure-gpt-4-omni
  type: azure_chat
  api_key: <your-api-key>
  api_version: 2025-01-01-preview
  azure_deployment: gpt-4o
  endpoint: https://<your-endpoint>.openai.azure.com/
```

```bash
# (Optional) Add a .env file in the root directory:
# .env
WHISPER_MODEL=base
LOG_LEVEL=INFO
VIDEO_STORAGE_PATH=./temp

# Then run the application:
python src/transcript/app.py
```

---

## 🐳 Docker Setup

```bash
cd src/transcript/docker
docker compose up --build
```

Ensure `llm_config.nebula.yml` is available inside the container.

---

## 🚀 API Usage

**POST** `/api/lecture/{lectureId}/lecture-unit/{lectureUnitId}/nebula-transcriber`

```json
{
  "videoUrl": "https://your.video.url/playlist.m3u8",
  "lectureId": 1,
  "lectureUnitId": 2
}
```

---

## 🎓 How to Get a TUM-Live `.m3u8` Link

1. Open [TUM Live](https://live.rbg.tum.de)
2. Inspect Network tab > find `.m3u8` link
3. Copy full URL (including `jwt`)
4. Use it in the request above

---

## 🧹 Temporary File Cleanup

- Temporary `.mp4` files are saved in `./temp` by default
- Auto-deleted after processing
- You can change this via `.env` → `VIDEO_STORAGE_PATH=./temp`

---

## 📁 Project Structure

```
nebula/
├── src/
│   └── transcript/
│       ├── app.py
│       ├── slide_utils.py
│       ├── whisper_utils.py
│       ├── config.py
│       ├── llm_utils.py
│       └── docker/
│           └── docker-compose.yml
├── llm_config.nebula.yml
└── .env (optional)
```

---

## 🛠️ Troubleshooting

- GPT Vision 404: Check deployment name and model match in Azure.
- FFmpeg not found: Ensure it's installed and in PATH.
- Whisper FP16 Warning: Safe to ignore on CPU.

---
