import subprocess, logging, cv2, base64

def download_video(video_url, video_path):
    logging.info("Downloading video...")
    command = f'ffmpeg -allowed_extensions ALL -i "{video_url}" -c copy "{video_path}" -y'
    result = subprocess.run(command, shell=True, capture_output=True, text=True)
    if result.returncode != 0:
        raise Exception(f"FFmpeg download failed: {result.stderr}")
    logging.info("Download complete.")

def extract_audio(video_path, audio_path):
    logging.info("Extracting audio...")
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
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(ts * fps))
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
