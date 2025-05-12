# Nebula_Transcriber

Nebula_Transcriber is a lightweight transcription service for educational videos.  
It uses **Whisper** locally for audio transcription and **GPT-4o Vision** to detect visible slide numbers from video frames.

---

## ✨ Features

- 🎥 Process `.m3u8` lecture video URLs (e.g., from TUM-Live)
- 🧠 Transcribe audio using local Whisper models
- 👁️ Detect slide numbers via GPT-4o Vision (Azure)
- ⚡ Stateless and fast — no database or external storage
- 🚀 Exposes a clean **FastAPI** interface

---

## 🧪 Local Development Setup

```bash
git clone https://github.com/ls1intum/edutelligence.git
cd edutelligence
git checkout feature/transcript
cd nebula/transcript
```

```bash
python -m venv .venv
.venv\Scripts\activate      # on Windows
source .venv/bin/activate  # on Unix/Mac

pip install -r requirements.txt
```

Create `llm_config.nebula.yml`:

```yaml
- id: azure-gpt-4-omni
  type: azure_chat
  api_key: <your-api-key>
  api_version: 2024-02-15-preview
  azure_deployment: gpt-4o
  endpoint: https://<your-endpoint>.openai.azure.com/
```

Run the FastAPI app:

```bash
uvicorn app:app --reload --host 0.0.0.0 --port 5000
```

---

## 🐳 Docker Setup

```bash
cd src/transcript/docker
docker compose up --build
```

Ensure `llm_config.nebula.yml` is available in the container.

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
│   └── transcript/
│       ├── app.py
│       ├── slide_utils.py
│       ├── whisper_utils.py
│       ├── config.py
│       ├── llm_utils.py
│       └── docker/
│           └── docker-compose.yml
├── llm_config.nebula.yml
```

---

## 🛠 Troubleshooting

- 404 from GPT Vision: Check Azure deployment name and API version
- Whisper FP16 warning: Ignored if using CPU
- FFmpeg error: Ensure it's installed and on PATH
- `proxies` error: Use OpenAI SDK ≤ 1.55.3 or strip extra config keys