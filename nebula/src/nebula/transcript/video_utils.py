import logging
import subprocess  # nosec B404

from nebula.tracing import trace_subprocess


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

    with trace_subprocess(
        "Download Video (ffmpeg)",
        command,
        {"video_url": video_url, "output_path": video_path},
    ) as span:
        try:
            result = subprocess.run(
                command,
                shell=False,
                capture_output=True,
                text=True,
                check=True,
            )  # nosec B603

            if result.stdout:
                logging.debug("ffmpeg stdout: %s", result.stdout)
            if result.stderr:
                logging.debug("ffmpeg stderr: %s", result.stderr)

            span.end(success=True, output={"returncode": result.returncode})

        except subprocess.CalledProcessError as e:
            span.end(
                success=False,
                output={"returncode": e.returncode},
                error=e.stderr,
            )
            raise RuntimeError(
                f"FFmpeg download failed with exit {e.returncode}: {e.stderr}"
            ) from e

    logging.info("Download complete.")


def extract_audio(video_path: str, audio_path: str) -> None:
    """Extract audio from a video file using ffmpeg."""
    logging.info("Extracting audio...")
    command = ["ffmpeg", "-i", video_path, "-q:a", "0", "-map", "a", audio_path, "-y"]

    with trace_subprocess(
        "Extract Audio (ffmpeg)",
        command,
        {"video_path": video_path, "audio_path": audio_path},
    ) as span:
        try:
            result = subprocess.run(
                command, shell=False, capture_output=True, text=True, check=True
            )  # nosec B603

            span.end(success=True, output={"returncode": result.returncode})

        except subprocess.CalledProcessError as e:
            span.end(
                success=False,
                output={"returncode": e.returncode},
                error=e.stderr,
            )
            raise RuntimeError(f"FFmpeg audio extraction failed: {e.stderr}") from e

    logging.info("Audio extraction complete.")
