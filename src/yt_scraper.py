"""YouTube channel scraper — lists all videos via yt-dlp flat-playlist, cached per channel."""

import json
from pathlib import Path
from urllib.parse import urlparse

DATA_DIR = Path(__file__).parent.parent / "data"


_YT_NOISE_SEGMENTS = {"videos", "shorts", "streams", "playlists", "community", "about", "featured"}


def channel_slug(channel_url: str) -> str:
    """Derive a filesystem-safe slug from a YouTube channel URL.

    Examples:
        https://www.youtube.com/@IBMTechnology          →  IBMTechnology
        https://www.youtube.com/@IBMTechnology/videos   →  IBMTechnology
        https://www.youtube.com/c/SomeName              →  SomeName
        https://www.youtube.com/channel/UCxxx           →  UCxxx
    """
    path = urlparse(channel_url).path
    parts = [p for p in path.split("/") if p and p not in _YT_NOISE_SEGMENTS]
    return parts[-1].lstrip("@") if parts else "unknown_channel"


def _cache_path(slug: str) -> Path:
    return DATA_DIR / slug / "video_list.json"


def _fetch_channel_videos(channel_url: str) -> list[dict]:
    import yt_dlp  # local import keeps startup fast when YouTube is not used

    opts = {
        "quiet": True,
        "extract_flat": True,
        "skip_download": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(channel_url, download=False)

    entries = info.get("entries", [])
    channel_name = info.get("channel") or info.get("uploader", "")
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
            "channel": channel_name,
            "duration": f"{h:02d}:{m:02d}:{s:02d}",
            "date_uploaded": entry.get("upload_date", ""),
        })
    return videos


def list_channel_videos(channel_url: str, refresh: bool = False) -> tuple[list[dict], str]:
    """Return (videos, slug) for a channel, reading from per-channel cache unless refresh=True."""
    slug = channel_slug(channel_url)
    cache = _cache_path(slug)
    cache.parent.mkdir(parents=True, exist_ok=True)

    if not refresh and cache.exists():
        cached = json.loads(cache.read_text(encoding="utf-8"))
        videos = cached["videos"]
        print(f"Loaded {len(videos)} videos from cache ({cache})")
        return videos, slug

    print(f"Fetching video list from: {channel_url}")
    videos = _fetch_channel_videos(channel_url)
    cache.write_text(
        json.dumps({"channel_url": channel_url, "videos": videos}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"Found {len(videos)} videos — cached to {cache}")
    return videos, slug
