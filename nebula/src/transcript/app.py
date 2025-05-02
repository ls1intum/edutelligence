from flask import Flask, request, jsonify
from flask_cors import CORS
import os, uuid, logging, time
from config import Config
from video_utils import download_video, extract_audio, extract_frames_at_timestamps
from whisper_utils import transcribe_with_local_whisper
from slide_utils import ask_gpt_for_slide_number
from align_utils import align_slides_with_segments

app = Flask(__name__)
CORS(app)
logging.basicConfig(level=getattr(logging, Config.LOG_LEVEL))

@app.route("/")
def home():
    return "Flask server is running!"

@app.route("/start-transcribe", methods=["POST"])
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
        timestamps = [s["start"] for s in transcription["segments"]]
        frames = extract_frames_at_timestamps(video_path, timestamps)

        slide_timestamps = []
        for ts, img_b64 in frames:
            slide_number = ask_gpt_for_slide_number(img_b64)
            if slide_number is not None:
                slide_timestamps.append((ts, slide_number))
            time.sleep(2)

        segments = align_slides_with_segments(transcription["segments"], slide_timestamps)
        result = {"language": transcription.get("language", "en"), "segments": segments}

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
