# transcripto — quick reference

## Setup (once)

```bash
poetry install
./build.sh          # compile Swift binary (requires Xcode CLI tools)
```

---

## Commands

### Single file — full pipeline (extract + transcribe → markdown)
```bash
poetry run transcripto input/lecture.mp4
poetry run transcripto input/recording.m4a   # audio input skips extraction
```
Output: `output/<stem>.md`

### Single file — extract audio only
```bash
poetry run transcripto --extract-only input/lecture.mp4
```
Output: `output/<stem>.m4a`

### Folder — batch extract all videos to audio
```bash
poetry run transcripto --batch-extract /path/to/folder/
```
- Converts every `.mp4 .mov .avi .mkv .webm .m4v` found in the folder
- Saves `<same-name>.m4a` next to each source video
- Skips videos that already have a `.m4a` alongside them (safe to re-run)

### Watch mode — auto-process anything dropped in `input/`
```bash
poetry run transcripto --watch
```

### Language (default: Italian)
```bash
poetry run transcripto input/lecture.mp4 --lang en-US
poetry run transcripto --batch-extract /folder/ --lang en-US   # N/A for extract-only
```

---

## Notes

- Transcription is currently blocked on macOS 26 (TCC issue — see `BLOCKERS.md`)
- Extraction via VLC works fine regardless
- VLC must be installed at `/Applications/VLC.app`


---

## Example

```
poetry run transcripto --youtube https://www.youtube.com/@IBMTechnology

poetry run transcripto --youtube https://www.youtube.com/@IBMTechnology --lang en --refresh
```