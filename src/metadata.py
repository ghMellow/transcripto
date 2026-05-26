"""Metadata extraction from local video/audio files via ffprobe."""

import json
import subprocess
from pathlib import Path


def extract_metadata(file_path: str) -> dict:
    result = subprocess.run(
        [
            "ffprobe", "-v", "quiet",
            "-print_format", "json",
            "-show_format", file_path,
        ],
        capture_output=True, text=True, check=True,
    )

    data = json.loads(result.stdout)
    fmt = data.get("format", {})
    tags = fmt.get("tags", {})

    duration_s = float(fmt.get("duration", 0))
    h = int(duration_s // 3600)
    m = int((duration_s % 3600) // 60)
    s = int(duration_s % 60)
    duration = f"{h:02d}:{m:02d}:{s:02d}"

    stem = Path(file_path).stem
    date_raw = tags.get("date") or tags.get("creation_time", "")
    date = date_raw[:10] if date_raw else ""

    return {
        "title": tags.get("title") or stem,
        "author": tags.get("artist") or tags.get("author") or "",
        "duration": duration,
        "date_created": date,
        "filename": Path(file_path).name,
    }
