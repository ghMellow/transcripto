#!/usr/bin/env python3
"""pipeline.py — full transcription pipeline.

Usage:
    poetry run transcripto input/lecture.mp4 [--lang it]
    poetry run transcripto --watch [--lang it]
    poetry run transcripto --extract-only input/lecture.mp4
    poetry run transcripto --batch-extract input/
    poetry run transcripto --youtube https://www.youtube.com/@Channel [--lang it] [--refresh]
"""

import argparse
import sys
import tempfile
from pathlib import Path

from watchdog.events import FileSystemEventHandler, FileCreatedEvent
from watchdog.observers import Observer

from .extract import extract_audio, is_audio, AUDIO_EXTENSIONS, VIDEO_EXTENSIONS
from .transcriber import transcribe, DEFAULT_LANGUAGE
from .metadata import extract_metadata
from .yt_scraper import list_channel_videos
from .yt_downloader import batch_download

REPO_ROOT = Path(__file__).parent.parent
OUTPUT_DIR = REPO_ROOT / "output"
INPUT_DIR = REPO_ROOT / "input"


def _q(v: str) -> str:
    return f'"{v}"'


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
        f"source: {video['url']}",
        f"channel: {video['channel']}",
        f"date_uploaded: {date}",
        f"duration: {video['duration']}",
        "tags: []",
        "---",
    ]
    return "\n".join(lines)


def extract_only(input_path: Path) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if is_audio(input_path):
        print(f"Already audio, nothing to extract: {input_path.name}")
        return input_path
    out = OUTPUT_DIR / f"{input_path.stem}.m4a"
    extract_audio(input_path, out)
    return out


def process_file(input_path: Path, lang: str) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if is_audio(input_path):
        audio_path = input_path
        tmp_path = None
    else:
        tmp = tempfile.NamedTemporaryFile(suffix=".m4a", delete=False)
        tmp.close()
        tmp_path = Path(tmp.name)
        extract_audio(input_path, tmp_path)
        audio_path = tmp_path

    try:
        print(f"Transcribing: {audio_path.name} [{lang}]")
        text = transcribe(str(audio_path), lang)
        meta = extract_metadata(str(input_path))
    finally:
        if tmp_path:
            tmp_path.unlink(missing_ok=True)

    frontmatter = _build_frontmatter(meta)
    md_path = OUTPUT_DIR / f"{input_path.stem}.md"
    md_path.write_text(
        f"{frontmatter}\n\n# {meta['title']}\n\n{text}\n",
        encoding="utf-8",
    )
    print(f"Saved: {md_path}")
    return md_path


def process_youtube_channel(channel_url: str, lang: str, refresh: bool = False) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    videos = list_channel_videos(channel_url, refresh=refresh)
    if not videos:
        print("No videos found for this channel.")
        return

    audio_paths = batch_download(videos)
    total = len(videos)

    for i, (video, audio_path) in enumerate(zip(videos, audio_paths), 1):
        md_path = OUTPUT_DIR / f"{video['id']}.md"
        if md_path.exists():
            print(f"[{i}/{total}] Skipping (already transcribed): {video['title']}")
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
        print(f"  Saved: {md_path}")


def batch_extract(folder: Path) -> None:
    videos = sorted(
        f for f in folder.iterdir()
        if f.is_file() and f.suffix.lower() in VIDEO_EXTENSIONS
    )
    if not videos:
        print(f"No video files found in {folder}")
        return

    print(f"Found {len(videos)} video(s) in {folder}")
    skipped = 0
    for video in videos:
        out = video.with_suffix(".m4a")
        if out.exists():
            print(f"Skipping (already converted): {video.name}")
            skipped += 1
            continue
        extract_audio(video, out)

    converted = len(videos) - skipped
    print(f"\nDone: {converted} converted, {skipped} skipped.")


class _TranscriptoHandler(FileSystemEventHandler):
    def __init__(self, lang: str) -> None:
        self._lang = lang

    def on_created(self, event: FileCreatedEvent) -> None:
        if event.is_directory:
            return
        path = Path(event.src_path)
        if path.suffix.lower() not in AUDIO_EXTENSIONS | VIDEO_EXTENSIONS:
            return
        try:
            process_file(path, self._lang)
        except Exception as exc:
            print(f"Error processing {path.name}: {exc}", file=sys.stderr)


def watch(lang: str) -> None:
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    handler = _TranscriptoHandler(lang)
    observer = Observer()
    observer.schedule(handler, str(INPUT_DIR), recursive=False)
    observer.start()
    print(f"Watching {INPUT_DIR} ... (Ctrl-C to stop)")
    try:
        observer.join()
    except KeyboardInterrupt:
        observer.stop()
        observer.join()


def main() -> None:
    parser = argparse.ArgumentParser(description="Transcribe video/audio to markdown.")
    parser.add_argument("input", nargs="?", help="Path to video or audio file")
    parser.add_argument("--lang", default=DEFAULT_LANGUAGE, help="Language code (default: it)")
    parser.add_argument("--watch", action="store_true", help="Watch input/ for new files")
    parser.add_argument(
        "--extract-only", action="store_true",
        help="Extract audio to output/ and stop (no transcription)",
    )
    parser.add_argument(
        "--batch-extract", metavar="DIR",
        help="Extract all videos in DIR to audio (same folder, skips already converted)",
    )
    parser.add_argument(
        "--youtube", metavar="CHANNEL_URL",
        help="Scrape, download, and transcribe all videos from a YouTube channel",
    )
    parser.add_argument(
        "--refresh", action="store_true",
        help="Force re-fetch of YouTube channel video list (ignores cache)",
    )
    args = parser.parse_args()

    if args.youtube:
        process_youtube_channel(args.youtube, args.lang, refresh=args.refresh)
        return

    if args.batch_extract:
        folder = Path(args.batch_extract)
        if not folder.is_dir():
            print(f"Error: not a directory: {folder}", file=sys.stderr)
            sys.exit(1)
        batch_extract(folder)
        return

    if args.watch:
        watch(args.lang)
        return

    if not args.input:
        parser.print_help()
        sys.exit(1)

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    if args.extract_only:
        out = extract_only(input_path)
        print(f"Audio saved: {out}")
    else:
        process_file(input_path, args.lang)


if __name__ == "__main__":
    main()
