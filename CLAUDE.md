# transcripto

Automates the workflow: **video/audio → on-device transcription → markdown file**.

## Goal

Turn video lessons (or any audio) into clean markdown notes, fully local, no external APIs, no paid services.

Pipeline:

```text
input/<file>  →  extract.py (VLC)  →  transcriber.py (mlx-whisper)  →  output/<file>.md
```

---

## Project layout

```text
transcripto/
├── input/               # drop videos or audio here (gitignored)
├── output/              # markdown transcriptions land here (gitignored)
├── src/
│   ├── pipeline.py      # CLI entrypoint — orchestrates the full flow
│   ├── extract.py       # video → audio via VLC
│   ├── transcriber.py   # transcription via mlx-whisper (replaces broken Swift/SFSpeechRecognizer)
│   └── metadata.py      # extracts metadata from local files via ffprobe
├── pyproject.toml
└── CLAUDE.md
```

**Removed from original layout:**
- `transcribe.swift` — was using SFSpeechRecognizer, blocked by macOS 26 TCC (see BLOCKERS.md)
- `build.sh` — no longer needed, no Swift binary

---

## Hardware context

MacBook Pro M4 Pro, 24GB unified RAM. mlx-whisper runs natively on Apple Silicon
via Metal/MLX — uses integrated GPU and unified memory. No CUDA, no external GPU needed.

---

## Usage

```bash
# 1. install (once)
poetry install

# first run downloads mlx-whisper model (~809MB for large-v3-turbo, cached after)

# 2. single file — full pipeline
poetry run transcripto input/lecture.mp4
poetry run transcripto input/recording.m4a   # audio input skips extraction

# 3. extract audio only
poetry run transcripto --extract-only input/lecture.mp4

# 4. batch extract all videos in a folder
poetry run transcripto --batch-extract input/

# 5. watch mode — auto-transcribes anything dropped in input/
poetry run transcripto --watch

# 6. language (default: Italian)
poetry run transcripto input/lecture.mp4 --lang en
```

Output lands in `output/<stem>.md`.

---

## Output format — markdown with YAML frontmatter

Every transcription file starts with a structured metadata block, then the transcript text.
This format is Obsidian-compatible and LLM-friendly.

### Local file output
```markdown
---
title: "Lecture 03 - Neural Networks"
source: local
filename: lecture_03.mp4
duration: 1:12:44
date_created: 2024-10-15
author: ""
tags: []
---

# Lecture 03 - Neural Networks

transcript text here...
```

Metadata is extracted via `ffprobe` (bundled with ffmpeg). Fields like `title` and `author`
come from the file's embedded ID3/container tags — often empty for downloaded files,
in which case `filename` (without extension) is used as title fallback.

### YouTube output (future — see Future Work section)
```markdown
---
title: "What is Quantum Computing?"
source: https://youtube.com/watch?v=abc123
channel: IBM Technology
date_uploaded: 2024-03-15
duration: 8:32
tags: []
---

# What is Quantum Computing?

transcript text here...
```

---

## Module responsibilities

### `src/extract.py`

- Input: any video or audio path
- Uses VLC (`/Applications/VLC.app/Contents/MacOS/VLC`) to extract audio as `.m4a`
- Output: path to extracted audio file (written to a temp dir)
- Skips extraction if input is already an audio format (`.m4a`, `.mp3`, `.wav`, `.aiff`)

### `src/transcriber.py`

**This module replaces the broken Swift/SFSpeechRecognizer approach.**

- Uses `mlx-whisper` — pip-installable, Apple Silicon GPU-accelerated via Metal, 100% offline
- Pre-processes audio to 16kHz mono WAV via ffmpeg before passing to Whisper (improves stability)
- Loads model once, reuses across batch runs
- Signature: `def transcribe(audio_path: str, language: str = "it") -> str`
- Cleans up temp WAV after transcription

```python
import mlx_whisper
import subprocess
from pathlib import Path

WHISPER_MODEL = "mlx-community/whisper-large-v3-turbo"   # production
# WHISPER_MODEL = "mlx-community/whisper-base"           # dev/test (faster, lower quality)

def preprocess(input_path: str, output_path: str) -> str:
    """Convert to 16kHz mono WAV for optimal Whisper input."""
    subprocess.run([
        "ffmpeg", "-i", input_path,
        "-ac", "1", "-ar", "16000",
        output_path, "-y", "-loglevel", "error"
    ], check=True)
    return output_path

def transcribe(audio_path: str, language: str = "it") -> str:
    wav_path = str(Path(audio_path).with_suffix("_16k.wav"))
    preprocess(audio_path, wav_path)
    result = mlx_whisper.transcribe(
        wav_path,
        path_or_hf_repo=WHISPER_MODEL,
        language=language,
    )
    Path(wav_path).unlink()  # cleanup temp file
    return result["text"]
```

**Whisper model reference:**

| Model | Size | Speed on M4 Pro | Accuracy |
|---|---|---|---|
| `large-v3-turbo` | ~809MB | 5–8x realtime | 95–98% — **default** |
| `base` | ~74MB | very fast | ~85% — dev/test only |

Model is downloaded automatically from HuggingFace on first run, cached locally after.

### `src/metadata.py`

Extracts metadata from local video/audio files using `ffprobe` (part of ffmpeg, no extra install).

```python
import subprocess, json
from pathlib import Path

def extract_metadata(file_path: str) -> dict:
    """
    Returns dict with: title, author, duration, date_created, filename.
    Falls back gracefully if tags are missing.
    """
    result = subprocess.run([
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_format", file_path
    ], capture_output=True, text=True, check=True)

    data = json.loads(result.stdout)
    tags = data.get("format", {}).get("tags", {})
    duration_s = float(data.get("format", {}).get("duration", 0))
    duration = f"{int(duration_s // 3600):02d}:{int((duration_s % 3600) // 60):02d}:{int(duration_s % 60):02d}"

    stem = Path(file_path).stem
    return {
        "title": tags.get("title") or stem,
        "author": tags.get("artist") or tags.get("author") or "",
        "duration": duration,
        "date_created": tags.get("date") or tags.get("creation_time", "")[:10],
        "filename": Path(file_path).name,
    }
```

### `src/pipeline.py`

- CLI entrypoint, registered as `transcripto` via Poetry scripts
- Detects if input needs audio extraction or can be transcribed directly
- Calls `metadata.extract_metadata()` to build YAML frontmatter
- Writes `output/<stem>.md` with frontmatter + transcript
- `--extract-only`: extract audio to `output/`, no transcription
- `--batch-extract <dir>`: extract all videos in a folder, skips already-converted
- `--watch` mode: monitors `input/` with watchdog, auto-processes new files
- `--lang`: language code passed to transcriber (default: `it`)

---

## Configuration

All runtime config as named constants at the top of each module:

| Constant | Module | Default |
|---|---|---|
| `VLC_PATH` | `extract.py` | `/Applications/VLC.app/Contents/MacOS/VLC` |
| `OUTPUT_DIR` | `pipeline.py` | `output/` (repo root) |
| `DEFAULT_LANGUAGE` | `pipeline.py` | `it` |
| `WHISPER_MODEL` | `transcriber.py` | `mlx-community/whisper-large-v3-turbo` |

---

## Dependencies

```toml
# pyproject.toml — relevant deps
mlx-whisper = ">=0.4.0"
watchdog = ">=4.0.0"    # for --watch mode
```

**System dependency:** `ffmpeg` via `brew install ffmpeg` (provides both `ffmpeg` and `ffprobe`)

No other external dependencies. No API keys. No `.env` needed.

---

## Constraints

- macOS on Apple Silicon (M-series) — mlx-whisper uses Metal, will not run on Intel Mac
- VLC must be installed at `/Applications/VLC.app`
- ffmpeg must be installed via Homebrew
- Python 3.11+

---

## Future work

### Immediate next: merge with yt-pipeline project

A separate project (`yt-pipeline`) automates downloading audio from YouTube channels
and transcribing them. The transcription engine is identical (mlx-whisper).
Plan: merge both into a single tool with two input modes:

```text
# local file (current)
poetry run transcripto input/lecture.mp4

# youtube channel (future)
poetry run transcripto --youtube https://www.youtube.com/@IBMTechnology
```

The YouTube mode adds:
- `src/yt_scraper.py` — lists all videos from a channel via yt-dlp flat-playlist, cached to `data/video_list.json`
- `src/yt_downloader.py` — batch downloads audio as .m4a via yt-dlp Python API, with delay between downloads and skip-if-exists
- YouTube frontmatter: title, channel, source URL, upload date, duration (all available from yt-dlp metadata)
- Rate limiting: 2s delay between downloads to avoid YouTube throttling (not scraping — yt-dlp uses YouTube's internal API, same as the browser)

### Web UI (non-technical users)

Minimal local web interface (Flask or FastAPI + simple HTML) so non-technical users
can use the tool without a terminal:
- Drop zone for local files
- URL input for YouTube links
- Progress indicator
- Download/copy transcript output
- No deployment — runs on localhost only

### Obsidian vault export

Configurable `VAULT_DIR` (via `.env`) to write markdown directly into an Obsidian vault folder.

---

## Language

All code, comments, variable names, and documentation must be in **English**.