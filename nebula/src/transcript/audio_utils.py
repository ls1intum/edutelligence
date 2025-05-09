import os
import subprocess


def split_audio_ffmpeg(audio_path, output_dir, chunk_duration=60):
    os.makedirs(output_dir, exist_ok=True)
    filename_base = os.path.splitext(os.path.basename(audio_path))[0]
    output_template = os.path.join(output_dir, f"{filename_base}_%03d.wav")

    command = [
        "ffmpeg",
        "-i", audio_path,
        "-f", "segment",
        "-segment_time", str(chunk_duration),
        "-c", "copy",
        output_template,
        "-y"
    ]

    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg split failed: {result.stderr}")

    # List chunk files in order
    chunk_files = sorted([
        os.path.join(output_dir, f)
        for f in os.listdir(output_dir)
        if f.endswith(".wav")
    ])
    return chunk_files
