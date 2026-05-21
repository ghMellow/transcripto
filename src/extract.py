"""Audio extraction from video files using VLC, with real-time progress bar."""

import subprocess
import sys
import time
from pathlib import Path

VLC_PATH = "/Applications/VLC.app/Contents/MacOS/VLC"

AUDIO_EXTENSIONS = {".m4a", ".mp3", ".wav", ".aiff", ".caf", ".aac"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"}

_BAR_WIDTH = 40
_AUDIO_BITRATE = 192_000  # bits/s — must match the transcode command below


def is_audio(path: Path) -> bool:
    return path.suffix.lower() in AUDIO_EXTENSIONS


def _get_duration(path: Path) -> float | None:
    """Return media duration in seconds via mdls (macOS Spotlight, no extra deps)."""
    result = subprocess.run(
        ["mdls", "-name", "kMDItemDurationSeconds", "-raw", str(path)],
        capture_output=True, text=True,
    )
    val = result.stdout.strip()
    try:
        return float(val) if val != "(null)" else None
    except ValueError:
        return None


def _draw_bar(pct: float) -> None:
    filled = int(pct / 100 * _BAR_WIDTH)
    bar = "█" * filled + "░" * (_BAR_WIDTH - filled)
    print(f"\r  [{bar}] {pct:5.1f}%", end="", flush=True)


def _run_with_progress(cmd: list[str], output_path: Path, expected_bytes: int | None) -> subprocess.CompletedProcess:
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    if expected_bytes:
        while proc.poll() is None:
            size = output_path.stat().st_size if output_path.exists() else 0
            _draw_bar(min(size / expected_bytes * 100, 99))
            time.sleep(0.5)
        _draw_bar(100)
        print()  # newline after bar
    else:
        # No duration info — show a spinner instead
        frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        i = 0
        while proc.poll() is None:
            print(f"\r  {frames[i % len(frames)]} extracting...", end="", flush=True)
            i += 1
            time.sleep(0.1)
        print("\r  done.              ")

    proc.wait()
    return proc


def extract_audio(video_path: Path, output_path: Path) -> Path:
    """Extract audio track from a video file to M4A via VLC."""
    print(f"Extracting: {video_path.name} → {output_path.name}")

    duration = _get_duration(video_path)
    # expected output bytes: duration × bitrate(bits/s) ÷ 8, with small overhead
    expected_bytes = int(duration * _AUDIO_BITRATE / 8 * 1.05) if duration else None

    cmd = [
        VLC_PATH,
        str(video_path),
        "--intf", "dummy",
        "--sout",
        (
            f"#transcode{{vcodec=none,acodec=mp4a,ab=192,channels=2,samplerate=44100}}"
            f":std{{access=file,mux=mp4,dst={output_path}}}"
        ),
        "vlc://quit",
    ]

    _run_with_progress(cmd, output_path, expected_bytes)

    if not output_path.exists():
        print("Error: VLC did not produce output file.", file=sys.stderr)
        sys.exit(1)

    return output_path
