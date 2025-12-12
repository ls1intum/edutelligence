import logging
import subprocess  # nosec B404


def download_video(video_url: str, video_path: str) -> None:
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
        "-c",
        "copy",
        "-bsf:a",
        "aac_adtstoasc",
        "-y",
        video_path,
    ]

    result = subprocess.run(
        command,
        shell=False,
        capture_output=True,
        text=True,
        check=True,
    )  # nosec B603

    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr)

    if result.returncode != 0:
        raise RuntimeError(
            f"FFmpeg download failed with exit {result.returncode}: {result.stderr}"
        )

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
