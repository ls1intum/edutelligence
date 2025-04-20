from flask import Flask, request, jsonify
from flask_cors import CORS
import whisper
import os
import requests
import subprocess
import uuid
import logging
import base64
import cv2
from openai import OpenAI
import shutil
import time

app = Flask(__name__)
CORS(app)

# Load Whisper model
model = whisper.load_model("base")

# OpenAI API key
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

logging.basicConfig(level=logging.INFO)


def download_video(video_url, video_path):
    """Download video from an m3u8 URL and save it as an MP4 file using FFmpeg."""
    logging.info("Starting video download...")
    # Use -allowed_extensions ALL to permit segment filenames with query parameters.
    command = f'ffmpeg -allowed_extensions ALL -i "{video_url}" -c copy "{video_path}" -y'
    result = subprocess.run(command, shell=True, capture_output=True, text=True)

    if result.returncode != 0:
        logging.error("FFmpeg video download failed.")
        logging.error("STDOUT:\n" + result.stdout)
        logging.error("STDERR:\n" + result.stderr)
        raise Exception("Failed to download video using FFmpeg.")

    logging.info("Video download complete.")



def extract_audio(video_path, audio_path):
    """Extract audio from video using FFmpeg"""
    logging.info("Extracting audio from video...")
    command = f"ffmpeg -i {video_path} -q:a 0 -map a {audio_path} -y"
    result = subprocess.run(command, shell=True, capture_output=True, text=True)

    if result.returncode != 0:
        logging.error("FFmpeg audio extraction failed.")
        logging.error("STDOUT:\n" + result.stdout)
        logging.error("STDERR:\n" + result.stderr)
        raise Exception("Failed to extract audio using FFmpeg.")

    logging.info("Audio extraction complete.")


def extract_frames_at_timestamps(video_path, timestamps):
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS)
    result = []

    for i, ts in enumerate(timestamps):
        frame_number = int(ts * fps)
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
        ret, frame = cap.read()
        if not ret:
            continue

        height = frame.shape[0]
        cropped = frame[int(height * 0.95):, :]  # Bottom 5%
        _, buffer = cv2.imencode(".jpg", cropped)
        img_b64 = base64.b64encode(buffer).decode("utf-8")
        result.append((ts, img_b64))

        if i < 3:
            debug_path = f"/tmp/debug_frame_{i+1}.jpg"
            cv2.imwrite(debug_path, cropped)
            logging.info(f"Saved debug frame to {debug_path}")

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
                        {
                            "type": "text",
                            "text": "What slide number is visible in this image? Only return the number. If none is visible, reply with 'unknown'."
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{image_b64}"
                            }
                        }
                    ]
                }
            ]
        )
        content = response.choices[0].message.content.strip().lower()
        logging.info(f"GPT response: {content}")
        if "unknown" in content:
            return None
        return int("".join(filter(str.isdigit, content)))

    except Exception as e:
        logging.warning(f"GPT Vision failed: {e}")
        return None


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


@app.route("/")
def home():
    return "Flask is running!"
@app.route('/transcribe', methods=['POST'])
def transcribe():
    data = request.get_json()
    video_url = data.get("video_url")
    lecture_id = data.get("lecture_id")  # <-- NEW

    if not video_url:
        return jsonify({"error": "Missing video_url in request body"}), 400
    if not lecture_id:
        return jsonify({"error": "Missing lecture_id in request body"}), 400

    logging.info(f"Transcribing lectureId={lecture_id} using video URL: {video_url}")

    try:
        uid = str(uuid.uuid4())
        video_path = f"/tmp/{uid}.mp4"
        audio_path = f"/tmp/{uid}.wav"

        download_video(video_url, video_path)
        extract_audio(video_path, audio_path)

        logging.info("Transcribing with Whisper...")
        transcription = model.transcribe(audio_path)

        logging.info("Extracting frames...")
        timestamps = [segment["start"] for segment in transcription["segments"]]
        frames = extract_frames_at_timestamps(video_path, timestamps)

        logging.info("Querying GPT-4V for slide numbers...")
        slide_timestamps = []
        for ts, img_b64 in frames:
            slide_number = ask_gpt_for_slide_number(img_b64)
            if slide_number is not None:
                slide_timestamps.append((ts, slide_number))
            time.sleep(3)

        logging.info("Aligning transcript with slides...")
        segments = align_slides_with_segments(transcription["segments"], slide_timestamps)

        os.remove(video_path)
        os.remove(audio_path)

        return jsonify({
            "language": transcription.get("language", "en"),
            "segments": segments
        })


    except Exception as e:
        logging.error(f"Transcription failed: {e}")
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
