"""YouTube audio downloader — batch downloads .m4a via yt-dlp, skip-if-exists, rate-limited."""

import sys
import time
from pathlib import Path

_DELAY_BETWEEN_DOWNLOADS = 2  # seconds — avoids YouTube throttling
_SOCKET_TIMEOUT = 60           # seconds — abort stalled connections
MAX_DURATION_SECONDS = 3600    # skip videos longer than 1 hour


def _parse_duration(duration_str: str) -> int:
    """Parse HH:MM:SS or MM:SS string into total seconds. Returns 0 on parse error."""
    try:
        parts = [int(p) for p in duration_str.split(":")]
        if len(parts) == 3:
            return parts[0] * 3600 + parts[1] * 60 + parts[2]
        if len(parts) == 2:
            return parts[0] * 60 + parts[1]
    except (ValueError, AttributeError):
        pass
    return 0


def _audio_path(video: dict, output_dir: Path) -> Path:
    return output_dir / f"{video['id']}.m4a"


def download_audio(video: dict, output_dir: Path) -> Path:
    """Download a single video's audio as .m4a. Returns the output path."""
    import yt_dlp  # local import keeps startup fast when YouTube is not used

    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = _audio_path(video, output_dir)

    if out_path.exists():
        return out_path

    opts = {
        "quiet": True,
        "format": "bestaudio[ext=m4a]/bestaudio/best",
        "outtmpl": str(output_dir / "%(id)s.%(ext)s"),
        "socket_timeout": _SOCKET_TIMEOUT,
        "retries": 3,
        "js_runtimes": ["node"],  # suppress "no JS runtime" warning; node is available via brew
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "m4a",
            }
        ],
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([video["url"]])

    return out_path


def batch_download(videos: list[dict], output_dir: Path) -> list[Path]:
    """Download audio for all videos into output_dir, skipping already-downloaded ones."""
    output_dir.mkdir(parents=True, exist_ok=True)
    total = len(videos)
    results: list[Path] = []

    for i, video in enumerate(videos, 1):
        out_path = _audio_path(video, output_dir)
        if out_path.exists():
            print(f"[{i}/{total}] Skipping (already downloaded): {video['title']}")
            results.append(out_path)
            continue

        duration_s = _parse_duration(video.get("duration", ""))
        if duration_s > MAX_DURATION_SECONDS:
            print(
                f"[{i}/{total}] Skipping (too long — {video['duration']} > 1h limit): {video['title']}"
            )
            continue

        print(f"[{i}/{total}] Downloading: {video['title']}")
        try:
            path = download_audio(video, output_dir)
            results.append(path)
        except Exception as exc:
            print(f"  Warning: download failed, skipping — {exc}", file=sys.stderr)
            results.append(out_path)  # placeholder (file won't exist; transcriber will skip)
            continue

        if i < total:
            time.sleep(_DELAY_BETWEEN_DOWNLOADS)

    return results
