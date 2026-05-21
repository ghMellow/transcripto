#!/usr/bin/env python3
"""
pipeline.py — full transcription pipeline.

Usage:
    python src/pipeline.py <input_file> [--lang it-IT]
    python src/pipeline.py --watch [--lang it-IT]
"""

import argparse
import sys
import time
import tempfile
from pathlib import Path

from .extract import extract_audio, is_audio, AUDIO_EXTENSIONS, VIDEO_EXTENSIONS
from .transcriber import transcribe

REPO_ROOT = Path(__file__).parent.parent
OUTPUT_DIR = REPO_ROOT / "output"
INPUT_DIR = REPO_ROOT / "input"


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
    finally:
        if tmp_path:
            tmp_path.unlink(missing_ok=True)

    md_path = OUTPUT_DIR / f"{input_path.stem}.md"
    md_path.write_text(f"# {input_path.stem}\n\n{text}\n", encoding="utf-8")
    print(f"Saved: {md_path}")
    return md_path


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


def watch(lang: str) -> None:
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    known = set(INPUT_DIR.iterdir())
    print(f"Watching {INPUT_DIR} ... (Ctrl-C to stop)")

    while True:
        time.sleep(2)
        current = set(INPUT_DIR.iterdir())
        new_files = current - known
        known = current

        for f in sorted(new_files):
            if f.suffix.lower() in AUDIO_EXTENSIONS | VIDEO_EXTENSIONS:
                try:
                    process_file(f, lang)
                except Exception as exc:
                    print(f"Error processing {f.name}: {exc}", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(description="Transcribe video/audio to markdown.")
    parser.add_argument("input", nargs="?", help="Path to video or audio file")
    parser.add_argument("--lang", default="it-IT", help="Language code (default: it-IT)")
    parser.add_argument("--watch", action="store_true", help="Watch input/ for new files")
    parser.add_argument("--extract-only", action="store_true", help="Extract audio to output/ and stop (no transcription)")
    parser.add_argument("--batch-extract", metavar="DIR", help="Extract all videos in DIR to audio (same folder, skips already converted)")
    args = parser.parse_args()

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
