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

# youtube: single video
poetry run transcripto --youtube URL

# youtube: full channel
poetry run transcripto --youtube URL

# youtube: check for new videos and download up to N
poetry run transcripto --youtube URL --refresh --limit N

# transcribe already-downloaded audio folder
poetry run transcripto --batch-transcribe data/NAME/audio/
```

---

## Options

| Option | Description |
| --- | --- |
| `--name NAME` | Project name — output goes to `data/NAME/transcription/` |
| `--lang CODE` | Language code (`it`, `en`, …). Omit to auto-detect |
| `--watch` | Watch folder for new files, transcribe on arrival |
| `--youtube URL` | Single video URL (`watch?v=`) or channel URL (`@Handle`) |
| `--refresh` | Fetch the 50 most recent channel videos and merge new ones into cache |
| `--limit N` | Process at most N pending videos, most recent first |
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
