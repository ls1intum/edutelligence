from flask import Flask, request, jsonify
from flask_cors import CORS
import os
import subprocess
import uuid
import logging
import base64
import cv2
import whisper
import time
from openai import OpenAI
from config import Config

app = Flask(__name__)
CORS(app)

# Initialize OpenAI client
client = OpenAI(api_key=Config.OPENAI_API_KEY)

# Initialize logging
logging.basicConfig(level=getattr(logging, Config.LOG_LEVEL))

# Helper Functions
def download_video(video_url, video_path):
    logging.info("Starting video download...")
    command = f'ffmpeg -allowed_extensions ALL -i "{video_url}" -c copy "{video_path}" -y'
    result = subprocess.run(command, shell=True, capture_output=True, text=True)
    if result.returncode != 0:
        raise Exception(f"FFmpeg download failed: {result.stderr}")
    logging.info("Video download complete.")

def extract_audio(video_path, audio_path):
    logging.info("Extracting audio from video...")
    command = f"ffmpeg -i {video_path} -q:a 0 -map a {audio_path} -y"
    result = subprocess.run(command, shell=True, capture_output=True, text=True)
    if result.returncode != 0:
        raise Exception(f"FFmpeg audio extraction failed: {result.stderr}")
    logging.info("Audio extraction complete.")

def extract_frames_at_timestamps(video_path, timestamps):
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS)
    result = []

    for ts in timestamps:
        frame_number = int(ts * fps)
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
        ret, frame = cap.read()
        if not ret:
            continue
        height = frame.shape[0]
        cropped = frame[int(height * 0.95):, :]
        _, buffer = cv2.imencode(".jpg", cropped)
        img_b64 = base64.b64encode(buffer).decode("utf-8")
        result.append((ts, img_b64))

    cap.release()
    return result

def ask_gpt_for_slide_number(image_b64):
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "What slide number is visible? Only number, or 'unknown'."},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}}
                    ]
                }
            ]
        )
        content = response.choices[0].message.content.strip().lower()
        if "unknown" in content:
            return None
        return int("".join(filter(str.isdigit, content)))
    except Exception as e:
        logging.warning(f"GPT Vision failed: {e}")
        return None

def transcribe_with_local_whisper(audio_path):
    logging.info("Using local Whisper model...")
    model = whisper.load_model(Config.WHISPER_MODEL)
    if whisper.torch.cuda.is_available():
        logging.info("Running Whisper on GPU.")
        model = model.to("cuda")
    else:
        logging.info("Running Whisper on CPU.")
    return model.transcribe(audio_path)

def align_slides_with_segments(segments, slide_timestamps):
    result = []
    for segment in segments:
        slide_number = 1
        for ts, num in reversed(slide_timestamps):
            if ts <= segment["start"]:
                slide_number = num
                break
        result.append({
            "startTime": segment["start"],
            "endTime": segment["end"],
            "text": segment["text"].strip(),
            "slideNumber": slide_number
        })
    return result

# Routes
@app.route("/")
def home():
    return "Flask server is running!"

@app.route('/start-transcribe', methods=['POST'])
def start_transcribe():
    data = request.get_json()
    video_url = data.get("videoUrl")

    if not video_url:
        return jsonify({"error": "Missing videoUrl"}), 400

    try:
        uid = str(uuid.uuid4())
        video_path = os.path.join(Config.VIDEO_STORAGE_PATH, f"{uid}.mp4")
        audio_path = os.path.join(Config.VIDEO_STORAGE_PATH, f"{uid}.wav")

        download_video(video_url, video_path)
        extract_audio(video_path, audio_path)

        transcription = transcribe_with_local_whisper(audio_path)
        logging.info("Local Whisper transcription successful.")

        timestamps = [segment["start"] for segment in transcription["segments"]]
        frames = extract_frames_at_timestamps(video_path, timestamps)

        slide_timestamps = []
        for ts, img_b64 in frames:
            slide_number = ask_gpt_for_slide_number(img_b64)
            if slide_number is not None:
                slide_timestamps.append((ts, slide_number))
            time.sleep(2)  # polite wait between GPT calls

        segments = align_slides_with_segments(transcription["segments"], slide_timestamps)

        result = {
            "language": transcription.get("language", "en"),
            "segments": segments
        }

        # Cleanup
        try:
            os.remove(video_path)
            os.remove(audio_path)
        except Exception as cleanup_err:
            logging.warning(f"Cleanup failed: {cleanup_err}")

        return jsonify(result)

    except Exception as e:
        logging.error(f"Transcription failed: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, threaded=True)
