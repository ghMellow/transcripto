# transcripto — quick reference

## Setup (once)

```bash
brew install ffmpeg
poetry install
```

---

## Commands

```bash
# local: single file
poetry run transcripto --name NAME PATH

# local: folder (batch)
poetry run transcripto --name NAME PATH/TO/FOLDER/

# local: watch folder for new files
poetry run transcripto --name NAME --watch PATH/TO/FOLDER/

# NOTE: always wrap YouTube URLs in quotes — zsh treats ? and & as special chars
#   poetry run transcripto --youtube "https://www.youtube.com/watch?v=ID" --video

# --youtube is just the link. Add explicit actions: --transcribe and/or --video.

# youtube single video: transcribe it
poetry run transcripto --youtube "URL" --transcribe --lang en

# youtube single video: download the VIDEO file only (interactive quality menu)
poetry run transcripto --youtube "URL" --video

# youtube single video: download the video AND transcribe it
poetry run transcripto --youtube "URL" --video --transcribe --lang en

# youtube single video: same, skip the menu (max resolution in px)
poetry run transcripto --youtube "URL" --video --quality 1080 --transcribe --lang en

# youtube full channel: transcription is automatic (only valid action; --video errors)
poetry run transcripto --youtube "CHANNEL_URL" --lang en

# youtube channel: check for new videos and download up to N
poetry run transcripto --youtube "CHANNEL_URL" --refresh --limit N

# youtube channel: skip uploads longer than 90 min (default: no limit)
poetry run transcripto --youtube "CHANNEL_URL" --max-duration 90

# transcribe already-downloaded audio folder
poetry run transcripto --batch-transcribe data/NAME/audio/
```

> Channel downloads are **interleaved** with transcription: one video is downloaded,
> transcribed, then its audio deleted (unless `--keep-audio`) before the next — the
> disk never holds the whole channel's audio at once. Resume-safe: already-transcribed
> videos are skipped on re-run.

---

## Options

| Option | Description |
| --- | --- |
| `--name NAME` | Project name — output goes to `data/NAME/transcription/` |
| `--lang CODE` | Language code (`it`, `en`, …). Omit to auto-detect |
| `--watch` | Watch folder for new files, transcribe on arrival |
| `--youtube URL` | Source link only — single video (`watch?v=`) or channel (`@Handle`). Add action flags below |
| `--transcribe` | Action: transcribe. Required for a single video (alone or with `--video`); automatic for channels |
| `--video` | Action (single video only): download the video file (quality menu) → `data/<channel>/video/`. Errors on a channel link |
| `--quality HEIGHT` | Max video height in px (e.g. `1080`) — skips the `--video` quality menu |
| `--refresh` | Fetch the 50 most recent channel videos and merge new ones into cache |
| `--limit N` | Process at most N pending videos, most recent first |
| `--max-duration MIN` | Channel only: skip videos longer than MIN minutes (default: no limit) |
| `--keep-audio` | Keep `.m4a` after transcription (default: deleted to save space) |
| `--batch-transcribe DIR` | Transcribe all audio files in DIR, skip already-done |
| `--out-dir DIR` | Output dir for `--batch-transcribe` (default: `../transcription/`) |

---

## Output

All transcriptions are saved as markdown with YAML frontmatter:

```text
data/<name>/transcription/<title>.md     # local files
data/<channel>/transcription/<title>.md  # YouTube
```
