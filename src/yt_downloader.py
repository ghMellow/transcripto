"""YouTube audio downloader — batch downloads .m4a via yt-dlp, skip-if-exists, rate-limited."""

import glob
import sys
import time
from pathlib import Path

_DELAY_BETWEEN_DOWNLOADS = 2  # seconds — avoids YouTube throttling
_SOCKET_TIMEOUT = 60           # seconds — abort stalled connections
MAX_DURATION_SECONDS = 3600    # skip videos longer than 1 hour

# Containers a merged video file may end up in (native, no re-encode).
# mp4 when streams are mp4-compatible, otherwise mkv/webm for VP9/AV1.
_VIDEO_OUTPUT_EXTS = {".mp4", ".mkv", ".webm", ".mov", ".m4v"}

_BAR_WIDTH = 30
_SPIN_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]


def _make_progress_hook():
    """Build a yt-dlp progress_hook that draws a live bar (or spinner if size unknown).

    A fresh hook is created per download so the spinner state is isolated. YouTube
    DASH streams download video then audio separately, so two bars may appear in
    sequence, each ending with a 'Stream complete' line.
    """
    state = {"spin": 0}

    def hook(d: dict) -> None:
        status = d.get("status")
        if status == "downloading":
            done = d.get("downloaded_bytes", 0)
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            speed = d.get("speed") or 0
            spd = f"{speed / 1_000_000:5.1f} MB/s" if speed else "   --    "
            if total:
                pct = min(done / total * 100, 100)
                filled = int(pct / 100 * _BAR_WIDTH)
                bar = "█" * filled + "░" * (_BAR_WIDTH - filled)
                print(f"\r  [{bar}] {pct:5.1f}%  {spd}", end="", flush=True)
            else:
                frame = _SPIN_FRAMES[state["spin"] % len(_SPIN_FRAMES)]
                state["spin"] += 1
                print(f"\r  {frame} downloading {done / 1_000_000:7.1f} MB  {spd}", end="", flush=True)
        elif status == "finished":
            name = Path(d.get("filename", "")).name
            # overwrite the bar line, then newline
            print(f"\r  Stream complete: {name}".ljust(_BAR_WIDTH + 24), flush=True)

    return hook


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


def _build_video_dict(info: dict, url: str) -> dict:
    """Build the canonical video metadata dict from a yt-dlp info object."""
    duration_s = info.get("duration") or 0
    h, rem = divmod(int(duration_s), 3600)
    m, s = divmod(rem, 60)
    duration = f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

    return {
        "id": info["id"],
        "title": info.get("title", info["id"]),
        "url": url,
        "channel": info.get("uploader") or info.get("channel", ""),
        "date_uploaded": info.get("upload_date", ""),
        "duration": duration,
    }


def fetch_video_info(url: str) -> dict:
    """Fetch metadata for a single YouTube video URL. Returns a video dict."""
    import yt_dlp

    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)

    return _build_video_dict(info, url)


def list_video_formats(url: str) -> tuple[dict, list[dict]]:
    """Probe a YouTube video's available video qualities without downloading.

    Returns (video_dict, options) where options is a list of one entry per
    distinct resolution (highest first), each:
        {"height": int, "ext": str, "vcodec": str, "fps": float|None, "filesize": int}
    `filesize` is the estimated final size (video stream + best audio stream).
    """
    import yt_dlp

    opts = {"quiet": True, "no_warnings": True, "skip_download": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)

    video = _build_video_dict(info, url)
    formats = info.get("formats", [])

    # Best (largest) audio-only stream — added to each estimate since high-res
    # video streams are video-only on YouTube (DASH).
    audio_size = 0
    for f in formats:
        if f.get("acodec") not in (None, "none") and f.get("vcodec") in (None, "none"):
            audio_size = max(audio_size, f.get("filesize") or f.get("filesize_approx") or 0)

    # Keep the best format per resolution height: prefer mp4/H.264, then bitrate.
    best_by_height: dict[int, dict] = {}
    for f in formats:
        if f.get("vcodec") in (None, "none"):
            continue
        height = f.get("height")
        if not height:
            continue
        size = f.get("filesize") or f.get("filesize_approx") or 0
        score = (1 if f.get("ext") == "mp4" else 0, f.get("tbr") or 0)
        current = best_by_height.get(height)
        if current is None or score > current["_score"]:
            best_by_height[height] = {
                "height": height,
                "ext": f.get("ext") or "mp4",
                "vcodec": (f.get("vcodec") or "").split(".")[0],
                "fps": f.get("fps"),
                "filesize": (size + audio_size) if size else 0,
                "_score": score,
            }

    options = [best_by_height[h] for h in sorted(best_by_height, reverse=True)]
    for opt in options:
        opt.pop("_score", None)
    return video, options


def download_audio(video: dict, output_dir: Path) -> Path:
    """Download a single video's audio as .m4a. Returns the output path."""
    import yt_dlp  # local import keeps startup fast when YouTube is not used

    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = _audio_path(video, output_dir)

    if out_path.exists():
        return out_path

    opts = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "format": "bestaudio[ext=m4a]/bestaudio/best",
        "outtmpl": str(output_dir / "%(id)s.%(ext)s"),
        "socket_timeout": _SOCKET_TIMEOUT,
        "retries": 3,
        "progress_hooks": [_make_progress_hook()],
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "m4a",
            }
        ],
    }
    print(f"  Downloading audio ...")
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([video["url"]])

    return out_path


def download_video(video: dict, output_dir: Path, max_height: int, stem: str) -> Path:
    """Download a single video up to max_height (px), merging best audio.

    The output file is named `<stem>.<ext>` — `stem` must already be filesystem-safe
    (caller cleans the video title). Native container, no re-encode: mp4 when streams
    are mp4-compatible, otherwise mkv/webm (VP9/AV1). Skip-if-exists by stem.
    Returns the path to the merged file.
    """
    import yt_dlp

    output_dir.mkdir(parents=True, exist_ok=True)

    def _final(prefix: str) -> list[Path]:
        return [p for p in output_dir.glob(f"{prefix}.*") if p.suffix.lower() in _VIDEO_OUTPUT_EXTS]

    existing = _final(glob.escape(stem))
    if existing:
        return existing[0]

    # Prefer mp4/m4a so common resolutions stay mp4; fall back to whatever the
    # video offers (webm/VP9/AV1) at high resolutions — no re-encode either way.
    fmt = (
        f"bestvideo[height<={max_height}][ext=mp4]+bestaudio[ext=m4a]/"
        f"bestvideo[height<={max_height}]+bestaudio/"
        f"best[height<={max_height}]"
    )

    # Download under the stable video id, then rename to the clean title. This keeps
    # yt-dlp's outtmpl free of title characters (% format specs, length limits).
    opts = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "format": fmt,
        "outtmpl": str(output_dir / "%(id)s.%(ext)s"),
        "socket_timeout": _SOCKET_TIMEOUT,
        "retries": 3,
        "progress_hooks": [_make_progress_hook()],
    }
    print(f"  Downloading video (up to {max_height}p) ...")
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([video["url"]])

    downloaded = _final(glob.escape(video["id"]))
    if not downloaded:
        return output_dir / f"{stem}.mp4"

    src = downloaded[0]
    dst = src.with_name(f"{stem}{src.suffix}")
    src.rename(dst)
    return dst


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
