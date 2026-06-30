# transcripto

Automates the workflow: **video/audio → on-device transcription → markdown file**.

## Goal

Turn video lessons (or any audio) into clean markdown notes, fully local, no external APIs, no paid services.

Pipeline:

```text
<any path>  →  extract.py (ffmpeg)  →  transcriber.py (mlx-whisper)  →  data/<name>/transcription/<file>.md
```

---

## Project layout

```text
transcripto/
├── data/                    # all project data (gitignored)
│   └── <name>/              # one folder per project or channel
│       ├── audio/           # extracted or downloaded audio (.m4a)
│       ├── video/           # downloaded YouTube video (--video mode only)
│       ├── transcription/   # markdown output
│       └── video_list.json  # YouTube metadata cache (YouTube mode only)
├── src/
│   ├── pipeline.py          # CLI entrypoint — orchestrates the full flow
│   ├── extract.py           # video → audio via ffmpeg
│   ├── transcriber.py       # transcription via mlx-whisper
│   ├── metadata.py          # extracts metadata from local files via ffprobe
│   ├── yt_scraper.py        # lists YouTube channel videos via yt-dlp
│   └── yt_downloader.py     # batch downloads audio from YouTube
├── pyproject.toml
└── CLAUDE.md
```

**Removed from original layout:**

- `input/` — was a fixed drop zone; replaced by arbitrary path via `--name` CLI flag
- `output/` — was a fixed output dir; replaced by `data/<name>/transcription/`
- `transcribe.swift` — was using SFSpeechRecognizer, blocked by macOS 26 TCC
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

# 2. local: single file (video or audio), any path on disk
poetry run transcripto --name Fisica /path/to/video.mp4
poetry run transcripto --name Fisica /path/to/recording.m4a  # audio skips extraction

# 3. local: entire folder (batch — auto-detects video vs audio)
poetry run transcripto --name Fisica /Volumes/HDD/lezioni/

# 4. local: watch a folder, auto-transcribes new files as they arrive
poetry run transcripto --name Fisica --watch /path/to/folder/

# 5. youtube: --youtube is just the source link; explicit actions say what to do.
#    Channel link → batch transcription is automatic (only possible action):
poetry run transcripto --youtube https://www.youtube.com/@IBMTechnology --lang en

# 5b. single video — pick action(s): --transcribe, --video, or both
poetry run transcripto --youtube "https://www.youtube.com/watch?v=VIDEO_ID" --transcribe --lang en
poetry run transcripto --youtube "https://www.youtube.com/watch?v=VIDEO_ID" --video             # video file only (quality menu)
poetry run transcripto --youtube "https://www.youtube.com/watch?v=VIDEO_ID" --video --transcribe --quality 1080 --lang en  # both

# 6. batch-transcribe: transcribe already-downloaded audio (resume-safe)
poetry run transcripto --batch-transcribe data/IBMTechnology/audio/ --lang en

# 7. language (default: Italian)
poetry run transcripto --name Fisica /path/to/video.mp4 --lang en
```

Output always lands in `data/<name>/transcription/<stem>.md`.

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

Metadata is extracted via `ffprobe`. Fields like `title` and `author` come from the file's
embedded ID3/container tags — often empty for downloaded files, in which case `filename`
(without extension) is used as title fallback.

### YouTube output

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
- Uses **ffmpeg** to extract the audio track as `.m4a` (AAC), with a live progress bar
  driven by ffmpeg's `-progress` stream (no separate VLC install needed — ffmpeg is
  already a dependency). Raises `RuntimeError` on failure so a batch run can skip one
  bad file instead of aborting.
- Output: `.m4a` written to `data/<name>/audio/`
- Only used when audio is **kept** (`--keep-audio`). For transcription-only runs the
  pipeline skips this entirely and feeds the video straight to the transcriber, whose
  ffmpeg step extracts + resamples to 16kHz mono in a **single pass** (no throwaway m4a).
- `is_audio()` lets callers detect already-audio inputs (`.m4a`, `.mp3`, `.wav`, ...)

### `src/transcriber.py`

**Replaces the broken Swift/SFSpeechRecognizer approach.**

- Uses `mlx-whisper` — pip-installable, Apple Silicon GPU-accelerated via Metal, 100% offline
- Pre-processes audio to 16kHz mono WAV via ffmpeg before passing to Whisper (improves stability).
  The temp WAV is written to the **system temp dir** (`tempfile`), never next to the
  source file — the input may live on a read-only volume.
- Model loaded once per process — batch runs reuse it with no re-load overhead
- Signature: `def transcribe(audio_path: str, language: str = None, initial_prompt: str | None = None) -> str`
  - `initial_prompt` biases Whisper toward domain vocabulary (titles, proper nouns,
    acronyms). Callers pass the lecture/video **title**.
- **Output is paragraph-segmented**: Whisper's timestamped segments are grouped into
  paragraphs (new paragraph on a >`PARAGRAPH_GAP_SECONDS` pause, or when a paragraph
  exceeds `PARAGRAPH_MAX_CHARS`) instead of one wall of text. Falls back to `result["text"]`
  if no segments are returned.
- Anti-drift decoding params (`CONDITION_ON_PREVIOUS_TEXT=False` + temperature ladder +
  compression/logprob/no-speech thresholds) prevent hallucination cascades on long audio.
- Cleans up temp WAV after transcription

```python
import mlx_whisper
import subprocess
from pathlib import Path

WHISPER_MODEL = "mlx-community/whisper-large-v3-turbo"   # production
# WHISPER_MODEL = "mlx-community/whisper-base"           # dev/test (faster, lower quality)

def transcribe(audio_path: str, language: str = "it") -> str:
    wav_path = str(Path(audio_path).with_suffix("_16k.wav"))
    # preprocess to 16kHz mono WAV, then transcribe, then cleanup
    ...
    return result["text"]
```

**Whisper model reference:**

| Model | Size | Speed on M4 Pro | Accuracy |
| --- | --- | --- | --- |
| `large-v3-turbo` | ~809MB | 5–8x realtime | 95–98% — **default** |
| `base` | ~74MB | very fast | ~85% — dev/test only |

Model is downloaded automatically from HuggingFace on first run, cached at
`~/.cache/huggingface/hub/` locally after.

### `src/metadata.py`

Extracts metadata from local video/audio files using `ffprobe` (part of ffmpeg, no extra install).
Returns: `title`, `author`, `duration`, `date_created`, `filename`.
Falls back gracefully if tags are missing (uses filename stem as title).

### `src/yt_scraper.py`

- Lists all videos from a YouTube channel via yt-dlp flat-playlist (fast, no full extract)
- Caches result to `data/<slug>/video_list.json` to avoid re-fetching (1000+ videos = slow)
- `--refresh` flag forces re-fetch

### `src/yt_downloader.py`

- `iter_audio_downloads(videos, dir, max_duration_seconds=None)` — **lazy generator**:
  yields `(video, audio_path)` one at a time (skip-if-exists, duration-filtered, rate-limited).
  Lets the channel pipeline transcribe + delete each file before the next download, so the
  disk never holds the whole channel at once. `max_duration_seconds=None` = no length limit
  (the CLI's `--max-duration` is off by default).
- Skip-if-exists (resume-safe)
- 2s delay between downloads to avoid YouTube throttling
- `socket_timeout=60`, `retries=3` to handle CDN drops (not rate limits)
- `list_video_formats(url)` — probes a single video's available resolutions
  without downloading (one entry per height, best codec/bitrate kept; size
  estimate = video stream + best audio stream). Used by the `--video` quality menu.
- `download_video(video, dir, max_height, stem)` — downloads `bestvideo[height<=N]+bestaudio`,
  merged by ffmpeg. **Native container, no re-encode**: `.mp4` when streams are
  mp4-compatible, otherwise `.mkv`/`.webm` for VP9/AV1 (all readable by VLC).
  Saved as `<stem>.<ext>` where `stem` is the cleaned video title (caller passes
  `_safe_stem(title)`, same as the `.md` filename) — downloaded under the video id
  then renamed. Single video only — no channel batch.

### `src/pipeline.py`

CLI entrypoint, registered as `transcripto` via Poetry scripts. Orchestrates:

- `--name NAME path` — local single file or folder, any path on disk
- `--name NAME --watch path` — FSEvents-based watch mode (zero CPU at rest)
- `--youtube URL` — source link only; explicit action flags decide what happens:
  - **channel link** → batch transcription, automatic (the only valid action).
    `--video` on a channel is an error. Download is **interleaved** with transcription
    (one video at a time). `--max-duration MINUTES` skips overly long uploads (default: no limit).
  - **single video** (`watch?v=` / `youtu.be/`) → requires at least one action:
    - `--transcribe` → transcribe (audio path; video file not kept)
    - `--video [--quality N]` → download the video file (interactive quality menu,
      or `--quality N` to skip it), kept in `data/<name>/video/`
    - `--video --transcribe` → both; audio is extracted from the downloaded video
      only as a means to transcribe (with `--lang` for language)
    - no action flag → error
- `--batch-transcribe DIR` — transcribe already-downloaded audio folder (resume-safe)
- All output → `data/<name>/transcription/`; extracted audio → `data/<name>/audio/`

---

## Configuration

All runtime config as named constants at the top of each module:

| Constant | Module | Default |
| --- | --- | --- |
| `DEFAULT_LANGUAGE` | `transcriber.py` | `it` |
| `WHISPER_MODEL` | `transcriber.py` | `mlx-community/whisper-large-v3-turbo` |
| `CONDITION_ON_PREVIOUS_TEXT` | `transcriber.py` | `False` (anti-drift on long files) |
| `TEMPERATURE` | `transcriber.py` | `(0.0, 0.2, 0.4, 0.6, 0.8, 1.0)` |
| `COMPRESSION_RATIO_THRESHOLD` | `transcriber.py` | `2.4` |
| `LOGPROB_THRESHOLD` | `transcriber.py` | `-1.0` |
| `NO_SPEECH_THRESHOLD` | `transcriber.py` | `0.6` |
| `PARAGRAPH_GAP_SECONDS` | `transcriber.py` | `2.0` (pause that starts a new paragraph) |
| `PARAGRAPH_MAX_CHARS` | `transcriber.py` | `700` (cap so gapless speech still breaks) |

---

## Dependencies

```toml
# pyproject.toml — relevant deps
mlx-whisper = ">=0.4.0"
watchdog = ">=4.0.0"    # for --watch mode
yt-dlp = "*"            # for --youtube mode
```

**System dependency:** `ffmpeg` via `brew install ffmpeg` (provides both `ffmpeg` and `ffprobe`)

No other external dependencies. No API keys. No `.env` needed.

---

## Constraints

- macOS on Apple Silicon (M-series) — mlx-whisper uses Metal, will not run on Intel Mac
- ffmpeg must be installed via Homebrew (provides `ffmpeg` + `ffprobe`)
- Python 3.11+

---

## Future work

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
