import os
import subprocess  # nosec B404

from iris.common.logging_config import get_logger
from iris.tracing import observe

logger = get_logger(__name__)


@observe(name="Split Audio")
def split_audio_ffmpeg(
    audio_path: str, output_dir: str, chunk_duration: int
) -> list[str]:
    """Split an audio file into fixed-length chunks optimised for Whisper.

    Each chunk is encoded as a 16 kHz mono MP3 at 64 kbps — small enough to
    stay well under Whisper's 25 MB file-size limit while retaining speech quality.

    Args:
        audio_path: Path to the source audio file.
        output_dir: Directory where chunk files will be written.
        chunk_duration: Length of each chunk in seconds (from config).

    Returns:
        Sorted list of paths to the generated chunk files.

    Raises:
        RuntimeError: If FFmpeg fails or produces no output chunks.
    """
    os.makedirs(output_dir, exist_ok=True)

    # Remove any leftover chunks from a previous (failed) attempt.
    for filename in os.listdir(output_dir):
        if filename.endswith(".mp3"):
            os.remove(os.path.join(output_dir, filename))

    filename_base = os.path.splitext(os.path.basename(audio_path))[0]
    output_template = os.path.join(output_dir, f"{filename_base}_%03d.mp3")

    command = [
        "ffmpeg",
        "-i",
        audio_path,
        "-f",
        "segment",
        "-segment_time",
        str(chunk_duration),
        "-acodec",
        "libmp3lame",  # MP3 encoder
        "-b:a",
        "64k",  # small size, sufficient for speech
        "-ar",
        "16000",  # 16 kHz sample rate
        "-ac",
        "1",  # mono
        output_template,
        "-y",
    ]

    logger.info("Splitting audio into %ss chunks: %s", chunk_duration, audio_path)

    try:
        subprocess.run(  # nosec B603
            command,
            shell=False,
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"FFmpeg audio split failed: {e.stderr}") from e

    chunk_files = sorted(
        os.path.join(output_dir, f)
        for f in os.listdir(output_dir)
        if f.endswith(".mp3")
    )

    if not chunk_files:
        raise RuntimeError("FFmpeg produced no audio chunks.")

    logger.info("Created %s chunks in %s", len(chunk_files), output_dir)
    return chunk_files
