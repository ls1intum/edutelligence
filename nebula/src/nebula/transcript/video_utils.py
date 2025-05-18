import base64
import logging
import subprocess  # nosec B404

import cv2


def download_video(video_url: str, video_path: str) -> None:
    """Download video from a given URL using ffmpeg."""
    logging.info("Downloading video...")
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-protocol_whitelist",
        "file,http,https,tcp,tls",
        "-i",
        video_url,
        "-y",
        video_path,
    ]

    result = subprocess.run(
        command, shell=False, capture_output=True, text=True, check=True
    )  # nosec B603

    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg download failed: {result.stderr}")
    logging.info("Download complete.")


def extract_audio(video_path: str, audio_path: str) -> None:
    """Extract audio from a video file using ffmpeg."""
    logging.info("Extracting audio...")
    command = ["ffmpeg", "-i", video_path, "-q:a", "0", "-map", "a", audio_path, "-y"]
    result = subprocess.run(
        command, shell=False, capture_output=True, text=True, check=True
    )  # nosec B603

    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg audio extraction failed: {result.stderr}")
    logging.info("Audio extraction complete.")


def extract_frames_at_timestamps(
    video_path: str, timestamps: list[float]
) -> list[tuple[float, str]]:
    """Extract cropped base64-encoded frames from given timestamps."""
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS)
    result = []

    for ts in timestamps:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(ts * fps))
        ret, frame = cap.read()
        if not ret:
            continue
        height = frame.shape[0]
        cropped = frame[int(height * 0.95) :, :]
        _, buffer = cv2.imencode(".jpg", cropped)
        img_b64 = base64.b64encode(buffer).decode("utf-8")
        result.append((ts, img_b64))

    cap.release()
    return result
