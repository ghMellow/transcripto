#!/usr/bin/env python3
"""pipeline.py — full transcription pipeline.

All output lives under data/<name>/:
    data/<name>/audio/          extracted or downloaded audio
    data/<name>/transcription/  markdown output

Usage:
    # local: single file or folder, any path on disk
    poetry run transcripto --name Fisica /path/to/video.mp4 [--lang it]
    poetry run transcripto --name Fisica /Volumes/HDD/lezioni/ [--lang it]

    # local: watch a folder for new files
    poetry run transcripto --name Fisica --watch /path/to/folder/ [--lang it]

    # youtube: download + transcribe a full channel
    poetry run transcripto --youtube https://www.youtube.com/@Channel [--lang en] [--refresh]

    # youtube: single video
    poetry run transcripto --youtube https://www.youtube.com/watch?v=VIDEO_ID [--lang en]

    # batch-transcribe: transcribe already-downloaded audio in a folder
    poetry run transcripto --batch-transcribe data/IBMTechnology/audio/ [--lang en]
"""

import argparse
import json
import re
import sys
from pathlib import Path

from watchdog.events import FileSystemEventHandler, FileCreatedEvent
from watchdog.observers import Observer

from .extract import extract_audio, is_audio, AUDIO_EXTENSIONS, VIDEO_EXTENSIONS
from .transcriber import transcribe, DEFAULT_LANGUAGE
from .metadata import extract_metadata
from .yt_scraper import list_channel_videos
from .yt_downloader import (
    batch_download,
    fetch_video_info,
    download_audio as yt_download_audio,
    list_video_formats,
    download_video,
)

REPO_ROOT = Path(__file__).parent.parent
DATA_DIR = REPO_ROOT / "data"

MEDIA_EXTENSIONS = AUDIO_EXTENSIONS | VIDEO_EXTENSIONS


# ---------------------------------------------------------------------------
# Frontmatter builders
# ---------------------------------------------------------------------------

def _q(v: str) -> str:
    return f'"{v}"'


def _safe_stem(title: str, max_len: int = 120) -> str:
    """Convert a video title to a safe filename stem (no extension).

    Removes characters that are invalid on macOS/Windows/Linux filesystems,
    collapses whitespace, and truncates to max_len.
    """
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", title)
    safe = re.sub(r"\s+", " ", safe).strip()
    safe = safe.rstrip(".")          # trailing dots are problematic on Windows
    return safe[:max_len] if safe else "untitled"


def _build_frontmatter(meta: dict) -> str:
    lines = [
        "---",
        f"title: {_q(meta['title'])}",
        "source: local",
        f"filename: {meta['filename']}",
        f"duration: {meta['duration']}",
        f"date_created: {meta['date_created']}",
        f"author: {_q(meta['author'])}",
        "tags: []",
        "---",
    ]
    return "\n".join(lines)


def _build_yt_frontmatter(video: dict) -> str:
    date = video.get("date_uploaded", "")
    if len(date) == 8:  # yt-dlp returns YYYYMMDD
        date = f"{date[:4]}-{date[4:6]}-{date[6:]}"
    lines = [
        "---",
        f"title: {_q(video['title'])}",
        f"id: {video['id']}",
        f"source: {video['url']}",
        f"channel: {video['channel']}",
        f"date_uploaded: {date}",
        f"duration: {video['duration']}",
        "tags: []",
        "---",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Local file processing
# ---------------------------------------------------------------------------

def _transcription_dir(name: str) -> Path:
    return DATA_DIR / name / "transcription"


def _audio_dir(name: str) -> Path:
    return DATA_DIR / name / "audio"


def process_file(input_path: Path, name: str, lang: str, keep_audio: bool = False) -> Path:
    """Transcribe a single video or audio file into data/<name>/transcription/.

    If the input is a video, the extracted audio is deleted after transcription
    unless keep_audio=True. Original audio files passed directly are never deleted.
    """
    t_dir = _transcription_dir(name)
    t_dir.mkdir(parents=True, exist_ok=True)

    md_path = t_dir / f"{input_path.stem}.md"
    if md_path.exists():
        print(f"Skip (exists): {md_path.name}")
        return md_path

    if is_audio(input_path):
        audio_path = input_path
        extracted = False  # original audio — never delete
    else:
        a_dir = _audio_dir(name)
        a_dir.mkdir(parents=True, exist_ok=True)
        audio_out = a_dir / f"{input_path.stem}.m4a"
        if not audio_out.exists():
            extract_audio(input_path, audio_out)
        audio_path = audio_out
        extracted = True  # we created this — safe to delete after

    print(f"Transcribing: {input_path.name} [{lang}]")
    text = transcribe(str(audio_path), lang)
    meta = extract_metadata(str(input_path))

    frontmatter = _build_frontmatter(meta)
    md_path.write_text(
        f"{frontmatter}\n\n# {meta['title']}\n\n{text}\n",
        encoding="utf-8",
    )
    print(f"Saved: {md_path}")

    if extracted and not keep_audio:
        audio_path.unlink(missing_ok=True)
        print(f"Deleted audio: {audio_path.name}")

    return md_path


def process_folder(folder: Path, name: str, lang: str, keep_audio: bool = False) -> None:
    """Transcribe all video/audio files in folder into data/<name>/transcription/."""
    files = sorted(
        f for f in folder.iterdir()
        if f.is_file() and f.suffix.lower() in MEDIA_EXTENSIONS
    )
    if not files:
        print(f"No media files found in {folder}")
        return

    total = len(files)
    errors = 0
    print(f"Found {total} file(s) in {folder}")

    for i, f in enumerate(files, 1):
        print(f"[{i}/{total}]", end=" ")
        try:
            process_file(f, name, lang, keep_audio=keep_audio)
        except Exception as exc:
            print(f"  Error: {exc}", file=sys.stderr)
            errors += 1

    print(f"\nDone. Errors: {errors}")


# ---------------------------------------------------------------------------
# YouTube channel processing
# ---------------------------------------------------------------------------

def process_youtube_channel(
    channel_url: str, lang: str, refresh: bool = False, keep_audio: bool = False, limit: int | None = None
) -> None:
    """Download and transcribe all videos from a YouTube channel.

    Audio  → data/<slug>/audio/   (deleted after transcription unless keep_audio=True)
    Output → data/<slug>/transcription/

    Videos that already have a transcription .md are skipped entirely — no re-download.
    """
    videos, slug = list_channel_videos(channel_url, refresh=refresh)
    if not videos:
        print("No videos found for this channel.")
        return

    audio_dir = DATA_DIR / slug / "audio"
    t_dir = DATA_DIR / slug / "transcription"
    t_dir.mkdir(parents=True, exist_ok=True)

    # Skip videos already transcribed — transcription file is the source of truth.
    # This avoids re-downloading audio that was deleted after a previous transcription.
    pending = [v for v in videos if not (t_dir / f"{_safe_stem(v['title'])}.md").exists()]
    already_done = len(videos) - len(pending)
    if already_done:
        print(f"Skipping {already_done} already-transcribed video(s).")
    if not pending:
        print("All videos already transcribed.")
        return

    # Most recent first — date_uploaded is YYYYMMDD, lexicographic sort works
    pending.sort(key=lambda v: v.get("date_uploaded", ""), reverse=True)
    if limit is not None:
        pending = pending[:limit]
        print(f"Limit: processing {len(pending)} video(s).")

    audio_paths = batch_download(pending, audio_dir)
    total = len(pending)

    for i, (video, audio_path) in enumerate(zip(pending, audio_paths), 1):
        md_path = t_dir / f"{_safe_stem(video['title'])}.md"

        if not audio_path.exists():
            print(f"[{i}/{total}] Skip (download failed): {video['title']}")
            continue

        print(f"[{i}/{total}] Transcribing: {video['title']} [{lang}]")
        try:
            text = transcribe(str(audio_path), lang)
        except Exception as exc:
            print(f"  Error: {exc}", file=sys.stderr)
            continue

        frontmatter = _build_yt_frontmatter(video)
        md_path.write_text(
            f"{frontmatter}\n\n# {video['title']}\n\n{text}\n",
            encoding="utf-8",
        )
        print(f"  Saved: {md_path.name}")

        if not keep_audio:
            audio_path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# YouTube single video processing
# ---------------------------------------------------------------------------

def process_youtube_video(video_url: str, lang: str, keep_audio: bool = False) -> None:
    """Download and transcribe a single YouTube video.

    Audio  → data/<channel>/audio/   (deleted after transcription unless keep_audio=True)
    Output → data/<channel>/transcription/
    """
    print(f"Fetching video info: {video_url}")
    video = fetch_video_info(video_url)
    print(f"Title:   {video['title']}")
    print(f"Channel: {video['channel']}")

    slug = re.sub(r"[^\w\-]", "", video["channel"]) or "youtube"
    audio_dir = DATA_DIR / slug / "audio"
    t_dir = DATA_DIR / slug / "transcription"
    t_dir.mkdir(parents=True, exist_ok=True)

    md_path = t_dir / f"{_safe_stem(video['title'])}.md"
    if md_path.exists():
        print(f"Skip (exists): {md_path.name}")
        return

    audio_path = yt_download_audio(video, audio_dir)
    if not audio_path.exists():
        print("Error: download failed.", file=sys.stderr)
        return

    print(f"Transcribing: {video['title']} [{lang}]")
    text = transcribe(str(audio_path), lang)

    frontmatter = _build_yt_frontmatter(video)
    md_path.write_text(
        f"{frontmatter}\n\n# {video['title']}\n\n{text}\n",
        encoding="utf-8",
    )
    print(f"Saved: {md_path}")

    if not keep_audio:
        audio_path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# YouTube single video DOWNLOAD (interactive quality selection)
# ---------------------------------------------------------------------------

def _format_size(num_bytes: int) -> str:
    """Human-readable size estimate, or '?' when unknown."""
    if not num_bytes:
        return "? MB"
    mb = num_bytes / 1_000_000
    return f"{mb / 1000:.2f} GB" if mb >= 1000 else f"{mb:.0f} MB"


def _select_video_quality(video: dict, options: list[dict]) -> int | None:
    """Print available qualities and prompt for a choice on the CLI.

    Returns the chosen max height in pixels, or None if the user cancels.
    """
    print(f'\nAvailable video qualities for "{video["title"]}":')
    for idx, opt in enumerate(options, 1):
        fps = f"{opt['fps']:.0f}fps" if opt.get("fps") else ""
        print(
            f"  [{idx}]  {opt['height']:>4}p {fps:>6}  "
            f"{opt['vcodec']:<5}  .{opt['ext']:<4}  ~{_format_size(opt['filesize'])}"
        )
    print("  [0]  Cancel")

    while True:
        choice = input(f"Select quality [0-{len(options)}]: ").strip()
        if choice == "0":
            return None
        if choice.isdigit() and 1 <= int(choice) <= len(options):
            return options[int(choice) - 1]["height"]
        print("Invalid choice, try again.")


def process_youtube_video_download(
    video_url: str, lang: str, max_height: int | None = None, transcribe_after: bool = False
) -> None:
    """Download a single YouTube video (interactive quality). Transcription is opt-in.

    Video → data/<channel>/video/   (kept on disk)

    With transcribe_after=True, audio is extracted from the downloaded video,
    transcribed to data/<channel>/transcription/, then the temp audio is deleted;
    no separate audio stream is downloaded. If max_height is given, the interactive
    menu is skipped and the best stream up to that height is downloaded.
    """
    print(f"Fetching video info: {video_url}")
    video, options = list_video_formats(video_url)
    print(f"Title:   {video['title']}")
    print(f"Channel: {video['channel']}")

    if not options:
        print("Error: no downloadable video formats found.", file=sys.stderr)
        return

    if max_height is None:
        max_height = _select_video_quality(video, options)
        if max_height is None:
            print("Cancelled — nothing downloaded.")
            return

    slug = re.sub(r"[^\w\-]", "", video["channel"]) or "youtube"
    video_dir = DATA_DIR / slug / "video"
    video_path = download_video(video, video_dir, max_height, _safe_stem(video["title"]))
    if not video_path.exists():
        print("Error: download failed.", file=sys.stderr)
        return
    print(f"Saved video: {video_path}")

    if not transcribe_after:
        return  # video-only — transcription must be requested explicitly with --transcribe

    t_dir = DATA_DIR / slug / "transcription"
    t_dir.mkdir(parents=True, exist_ok=True)
    md_path = t_dir / f"{_safe_stem(video['title'])}.md"
    if md_path.exists():
        print(f"Transcription exists: {md_path.name}")
        return

    # Extract audio from the downloaded video — only a means to transcribe.
    audio_dir = DATA_DIR / slug / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    audio_tmp = audio_dir / f"{video['id']}.m4a"
    if not audio_tmp.exists():
        extract_audio(video_path, audio_tmp)

    print(f"Transcribing: {video['title']} [{lang}]")
    text = transcribe(str(audio_tmp), lang)

    frontmatter = _build_yt_frontmatter(video)
    md_path.write_text(
        f"{frontmatter}\n\n# {video['title']}\n\n{text}\n",
        encoding="utf-8",
    )
    print(f"Saved: {md_path}")

    audio_tmp.unlink(missing_ok=True)  # keep the video, drop the throwaway audio


# ---------------------------------------------------------------------------
# Batch-transcribe: already-downloaded audio folder (resume-safe)
# ---------------------------------------------------------------------------

def batch_transcribe_local(
    audio_dir: Path, out_dir: Path, lang: str, keep_audio: bool = False
) -> None:
    """Transcribe all audio files in audio_dir, output markdown to out_dir.

    Reads video_list.json from parent dir (if present) for YouTube frontmatter.
    Falls back to ffprobe metadata for local files.
    Skips files already transcribed (out_dir/<stem>.md exists).
    """
    audio_files = sorted(
        f for f in audio_dir.iterdir()
        if f.is_file() and f.suffix.lower() in AUDIO_EXTENSIONS
    )
    if not audio_files:
        print(f"No audio files found in {audio_dir}")
        return

    out_dir.mkdir(parents=True, exist_ok=True)

    # Load YouTube metadata index if available
    yt_index: dict[str, dict] = {}
    video_list_path = audio_dir.parent / "video_list.json"
    if video_list_path.exists():
        data = json.loads(video_list_path.read_text(encoding="utf-8"))
        videos = data.get("videos", data) if isinstance(data, dict) else data
        yt_index = {v["id"]: v for v in videos if "id" in v}
        print(f"Loaded YouTube metadata for {len(yt_index)} videos from {video_list_path.name}")

    total = len(audio_files)
    skipped = errors = 0

    for i, audio_path in enumerate(audio_files, 1):
        stem = audio_path.stem
        md_path = out_dir / f"{stem}.md"

        if md_path.exists():
            print(f"[{i}/{total}] Skip (exists): {stem}")
            skipped += 1
            continue

        print(f"[{i}/{total}] Transcribing: {stem} [{lang}]")
        try:
            text = transcribe(str(audio_path), lang)
        except Exception as exc:
            print(f"  Error: {exc}", file=sys.stderr)
            errors += 1
            continue

        video_meta = yt_index.get(stem)
        if video_meta:
            frontmatter = _build_yt_frontmatter(video_meta)
            title = video_meta.get("title", stem)
            md_path = out_dir / f"{_safe_stem(title)}.md"
        else:
            meta = extract_metadata(str(audio_path))
            frontmatter = _build_frontmatter(meta)
            title = meta["title"]
            # md_path already set above using stem (filename-based for non-YT audio)

        md_path.write_text(
            f"{frontmatter}\n\n# {title}\n\n{text}\n",
            encoding="utf-8",
        )
        print(f"  Saved: {md_path.name}")

        if not keep_audio:
            audio_path.unlink(missing_ok=True)

    done = total - skipped - errors
    print(f"\nDone: {done} transcribed, {skipped} skipped, {errors} errors.")


# ---------------------------------------------------------------------------
# Watch mode
# ---------------------------------------------------------------------------

class _TranscriptoHandler(FileSystemEventHandler):
    def __init__(self, name: str, lang: str) -> None:
        self._name = name
        self._lang = lang

    def on_created(self, event: FileCreatedEvent) -> None:
        if event.is_directory:
            return
        path = Path(event.src_path)
        if path.suffix.lower() not in MEDIA_EXTENSIONS:
            return
        try:
            process_file(path, self._name, self._lang)
        except Exception as exc:
            print(f"Error processing {path.name}: {exc}", file=sys.stderr)


def watch(watch_path: Path, name: str, lang: str) -> None:
    watch_path.mkdir(parents=True, exist_ok=True)
    handler = _TranscriptoHandler(name, lang)
    observer = Observer()
    observer.schedule(handler, str(watch_path), recursive=False)
    observer.start()
    print(f"Watching {watch_path} for new media ... (Ctrl-C to stop)")
    print(f"Output → data/{name}/transcription/")
    try:
        observer.join()
    except KeyboardInterrupt:
        observer.stop()
        observer.join()


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Transcribe video/audio to markdown. Output: data/<name>/transcription/",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # local file or folder (any path on disk)
  transcripto --name Fisica /path/to/video.mp4
  transcripto --name Fisica /Volumes/HDD/lezioni/

  # watch a folder for new files
  transcripto --name Fisica --watch /path/to/folder/

  # youtube channel (name auto-derived from channel)
  transcripto --youtube https://www.youtube.com/@IBMTechnology --lang en

  # youtube single video
  transcripto --youtube https://www.youtube.com/watch?v=dQw4w9WgXcQ --lang en

  # transcribe already-downloaded audio
  transcripto --batch-transcribe data/IBMTechnology/audio/ --lang en
""",
    )
    parser.add_argument(
        "--name", metavar="NAME",
        help="Project name — determines data/<name>/ output folder (required for local mode)",
    )
    parser.add_argument(
        "input", nargs="?",
        help="Path to video/audio file or folder (local mode)",
    )
    parser.add_argument(
        "--lang", default=DEFAULT_LANGUAGE,
        help="Language code (e.g. it, en). Omit to let Whisper auto-detect.",
    )
    parser.add_argument(
        "--watch", action="store_true",
        help="Watch the given folder for new media files (requires --name and input path)",
    )
    parser.add_argument(
        "--youtube", metavar="CHANNEL_URL",
        help="Download and transcribe all videos from a YouTube channel",
    )
    parser.add_argument(
        "--refresh", action="store_true",
        help="Force re-fetch of YouTube channel video list (ignores cache)",
    )
    parser.add_argument(
        "--video", action="store_true",
        help="Action (single YouTube video only): download the video file, with a quality menu",
    )
    parser.add_argument(
        "--quality", type=int, metavar="HEIGHT",
        help="Max video height in px (e.g. 1080) — skips the --video quality menu",
    )
    parser.add_argument(
        "--transcribe", action="store_true",
        help="Action: transcribe the video (uses --lang for the language). Combine with --video for both. Automatic for channel links",
    )
    parser.add_argument(
        "--batch-transcribe", metavar="AUDIO_DIR",
        help="Transcribe all audio files in AUDIO_DIR (skips already done)",
    )
    parser.add_argument(
        "--out-dir", metavar="DIR",
        help="Output dir for --batch-transcribe (default: <parent>/transcription/)",
    )
    parser.add_argument(
        "--keep-audio", action="store_true",
        help="Keep audio files after transcription (default: delete to save space)",
    )
    parser.add_argument(
        "--limit", type=int, metavar="N",
        help="Process at most N pending videos, most recent first (YouTube channel mode only)",
    )
    args = parser.parse_args()

    # --- YouTube mode ---
    # --youtube is just the source link; explicit actions say what to do:
    #   --transcribe → produce a transcription   --video → download the video file
    # Single video: at least one action required.
    # Channel link: batch transcription is the only possible action (automatic);
    #               --video errors out (no per-video quality choice in batch).
    if args.youtube:
        url = args.youtube
        is_single = "watch?v=" in url or "youtu.be/" in url

        if not is_single:
            if args.video:
                parser.error("--video works on a single video only; a channel link does batch transcription")
            process_youtube_channel(url, args.lang, refresh=args.refresh, keep_audio=args.keep_audio, limit=args.limit)
            return

        # single video
        if not args.video and not args.transcribe:
            parser.error("choose an action for the video: --transcribe and/or --video")
        if args.video:
            process_youtube_video_download(
                url, args.lang, max_height=args.quality, transcribe_after=args.transcribe
            )
        else:  # --transcribe only → audio path, no video file kept
            process_youtube_video(url, args.lang, keep_audio=args.keep_audio)
        return

    # --- Batch-transcribe mode (already-downloaded audio) ---
    if args.batch_transcribe:
        audio_dir = Path(args.batch_transcribe)
        if not audio_dir.is_dir():
            print(f"Error: not a directory: {audio_dir}", file=sys.stderr)
            sys.exit(1)
        out_dir = Path(args.out_dir) if args.out_dir else audio_dir.parent / "transcription"
        print(f"Output dir: {out_dir}")
        batch_transcribe_local(audio_dir, out_dir, args.lang, keep_audio=args.keep_audio)
        return

    # --- Local mode: requires --name ---
    if not args.name:
        parser.print_help()
        sys.exit(1)

    if not args.input:
        parser.error("local mode requires an input path (file or folder)")

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: path not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    # Watch mode
    if args.watch:
        if not input_path.is_dir():
            parser.error("--watch requires a directory path")
        watch(input_path, args.name, args.lang)
        return

    # Single file
    if input_path.is_file():
        process_file(input_path, args.name, args.lang, keep_audio=args.keep_audio)
        return

    # Folder: batch process all media files
    if input_path.is_dir():
        process_folder(input_path, args.name, args.lang, keep_audio=args.keep_audio)
        return

    print(f"Error: not a file or directory: {input_path}", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
