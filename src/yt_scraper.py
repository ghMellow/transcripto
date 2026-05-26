"""YouTube channel scraper — lists all videos via yt-dlp flat-playlist, cached to disk."""

import json
from pathlib import Path

import yt_dlp

CACHE_FILE = Path(__file__).parent.parent / "data" / "video_list.json"


def _fetch_channel_videos(channel_url: str) -> list[dict]:
    opts = {
        "quiet": True,
        "extract_flat": True,
        "skip_download": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(channel_url, download=False)

    entries = info.get("entries", [])
    videos = []
    for entry in entries:
        if not entry:
            continue
        duration_s = entry.get("duration") or 0
        h = int(duration_s // 3600)
        m = int((duration_s % 3600) // 60)
        s = int(duration_s % 60)
        videos.append({
            "id": entry.get("id", ""),
            "title": entry.get("title", ""),
            "url": entry.get("url") or f"https://www.youtube.com/watch?v={entry.get('id', '')}",
            "channel": info.get("channel") or info.get("uploader", ""),
            "duration": f"{h:02d}:{m:02d}:{s:02d}",
            "date_uploaded": entry.get("upload_date", ""),
        })
    return videos


def list_channel_videos(channel_url: str, refresh: bool = False) -> list[dict]:
    """Return video list for a channel, reading from cache unless refresh=True."""
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)

    if not refresh and CACHE_FILE.exists():
        cached = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        if cached.get("channel_url") == channel_url:
            print(f"Loaded {len(cached['videos'])} videos from cache ({CACHE_FILE.name})")
            return cached["videos"]

    print(f"Fetching video list from: {channel_url}")
    videos = _fetch_channel_videos(channel_url)
    CACHE_FILE.write_text(
        json.dumps({"channel_url": channel_url, "videos": videos}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"Found {len(videos)} videos — cached to {CACHE_FILE}")
    return videos
