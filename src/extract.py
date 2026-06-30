"""Audio extraction from video files using ffmpeg, with real-time progress bar.

ffmpeg is already a hard dependency (used by transcriber and metadata), so audio
extraction goes through it too — no separate VLC install needed.
"""

import json
import subprocess
from pathlib import Path

AUDIO_EXTENSIONS = {".m4a", ".mp3", ".wav", ".aiff", ".caf", ".aac"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"}

_BAR_WIDTH = 40
_AUDIO_BITRATE_KBPS = 192  # AAC bitrate for the kept-audio .m4a artifact


def is_audio(path: Path) -> bool:
    return path.suffix.lower() in AUDIO_EXTENSIONS


def _get_duration(path: Path) -> float | None:
    """Return media duration in seconds via ffprobe (reliable on any volume)."""
    result = subprocess.run(
        [
            "ffprobe", "-v", "quiet",
            "-print_format", "json",
            "-show_format", str(path),
        ],
        capture_output=True, text=True,
    )
    try:
        return float(json.loads(result.stdout)["format"]["duration"])
    except (ValueError, KeyError, json.JSONDecodeError):
        return None


def _hms_to_seconds(ts: str) -> float | None:
    """Parse ffmpeg out_time (HH:MM:SS.ffffff) into seconds, or None."""
    try:
        h, m, s = ts.split(":")
        return int(h) * 3600 + int(m) * 60 + float(s)
    except (ValueError, AttributeError):
        return None


def _draw_bar(pct: float) -> None:
    filled = int(pct / 100 * _BAR_WIDTH)
    bar = "█" * filled + "░" * (_BAR_WIDTH - filled)
    print(f"\r  [{bar}] {pct:5.1f}%", end="", flush=True)


def _run_with_progress(cmd: list[str], duration: float | None) -> None:
    """Run ffmpeg, parsing its -progress stream to drive the bar (or a wait, no duration)."""
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)

    assert proc.stdout is not None
    for line in proc.stdout:
        line = line.strip()
        if line == "progress=end":
            break
        if duration and line.startswith("out_time="):
            secs = _hms_to_seconds(line.split("=", 1)[1])
            if secs is not None:
                _draw_bar(min(secs / duration * 100, 99))

    proc.wait()
    if duration:
        _draw_bar(100)
        print()  # newline after bar
    else:
        print("  done.")


def extract_audio(video_path: Path, output_path: Path) -> Path:
    """Extract the audio track from a video file to M4A (AAC) via ffmpeg."""
    print(f"Extracting: {video_path.name} → {output_path.name}")

    duration = _get_duration(video_path)
    cmd = [
        "ffmpeg", "-y", "-i", str(video_path),
        "-vn", "-acodec", "aac", "-b:a", f"{_AUDIO_BITRATE_KBPS}k",
        "-progress", "pipe:1", "-nostats", "-loglevel", "error",
        str(output_path),
    ]

    _run_with_progress(cmd, duration)

    if not output_path.exists():
        # Raise (not sys.exit): a batch run must be able to skip this one file
        # and continue — SystemExit would bypass the caller's except Exception.
        raise RuntimeError(f"ffmpeg did not produce output for {video_path.name}")

    return output_path
