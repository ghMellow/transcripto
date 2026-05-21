"""Audio extraction from video files using VLC."""

import subprocess
import sys
from pathlib import Path

VLC_PATH = "/Applications/VLC.app/Contents/MacOS/VLC"

AUDIO_EXTENSIONS = {".m4a", ".mp3", ".wav", ".aiff", ".caf", ".aac"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"}


def is_audio(path: Path) -> bool:
    return path.suffix.lower() in AUDIO_EXTENSIONS


def extract_audio(video_path: Path, output_path: Path) -> Path:
    """Extract audio track from a video file to M4A via VLC."""
    print(f"Extracting audio: {video_path.name} -> {output_path.name}")

    cmd = [
        VLC_PATH,
        str(video_path),
        "--intf", "dummy",
        "--sout",
        (
            f"#transcode{{acodec=mp4a,ab=192,channels=2,samplerate=44100}}"
            f":std{{access=file,mux=mp4,dst={output_path}}}"
        ),
        "vlc://quit",
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)

    if not output_path.exists():
        raise RuntimeError(
            f"VLC did not produce output.\nStderr: {result.stderr[:500]}"
        )

    return output_path
