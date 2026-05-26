"""YouTube audio downloader — batch downloads .m4a via yt-dlp, skip-if-exists, rate-limited."""

import time
from pathlib import Path

import yt_dlp

DOWNLOAD_DIR = Path(__file__).parent.parent / "data" / "audio"
_DELAY_BETWEEN_DOWNLOADS = 2  # seconds — avoids YouTube throttling


def download_audio(video: dict, output_dir: Path = DOWNLOAD_DIR) -> Path:
    """Download a single video's audio as .m4a. Returns the output path."""
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"{video['id']}.m4a"

    if out_path.exists():
        return out_path

    opts = {
        "quiet": True,
        "format": "bestaudio[ext=m4a]/bestaudio/best",
        "outtmpl": str(output_dir / "%(id)s.%(ext)s"),
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


def batch_download(videos: list[dict], output_dir: Path = DOWNLOAD_DIR) -> list[Path]:
    """Download audio for all videos, skipping already-downloaded ones."""
    output_dir.mkdir(parents=True, exist_ok=True)
    total = len(videos)
    results: list[Path] = []

    for i, video in enumerate(videos, 1):
        out_path = output_dir / f"{video['id']}.m4a"
        if out_path.exists():
            print(f"[{i}/{total}] Skipping (already downloaded): {video['title']}")
            results.append(out_path)
            continue

        print(f"[{i}/{total}] Downloading: {video['title']}")
        path = download_audio(video, output_dir)
        results.append(path)

        if i < total:
            time.sleep(_DELAY_BETWEEN_DOWNLOADS)

    return results
