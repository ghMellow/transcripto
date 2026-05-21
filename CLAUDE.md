# transcripto

Automates the workflow: **video/audio → on-device transcription → markdown file**.

## Goal

Turn video lessons (or any audio) into clean markdown notes, fully local, no external APIs, no paid services.

Pipeline:

```text
input/<file>  →  extract.py (VLC)  →  transcriber.py (SFSpeechRecognizer)  →  output/<file>.md
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
│   ├── transcriber.py   # Python wrapper around the Swift binary
│   ├── transcribe.swift # SFSpeechRecognizer on-device recognition
│   └── transcribe       # compiled Swift binary (gitignored, built by build.sh)
├── build.sh             # one-shot: compiles transcribe.swift → src/transcribe
├── pyproject.toml
└── CLAUDE.md
```

---

## Usage

```bash
# 1. install the project (once)
poetry install

# 2. build the Swift binary (once, or after editing transcribe.swift)
./build.sh

# 3. run the full pipeline on a file
poetry run transcripto input/lecture.mp4

# 4. or on an audio file directly (skips extraction)
poetry run transcripto input/recording.m4a

# 5. extract audio only (no transcription), saved to output/
poetry run transcripto --extract-only input/lecture.mp4

# 6. batch-extract all videos in a folder to audio (same folder, skips already done)
poetry run transcripto --batch-extract input/

# 7. watch mode — auto-transcribes anything dropped in input/
poetry run transcripto --watch
```

Output lands in `output/<stem>.md`.

---

## Module responsibilities

### `src/extract.py`

- Input: any video or audio path
- Uses VLC (`/Applications/VLC.app/Contents/MacOS/VLC`) to extract audio as `.m4a`
- Output: path to the extracted audio file (written to a temp dir)
- Skips extraction if input is already an audio format (`.m4a`, `.mp3`, `.wav`, `.aiff`)

### `src/transcribe.swift`

- Compiled to `src/transcribe`
- CLI: `./src/transcribe <audio_path> [language]` (default language: `it-IT`)
- Uses `SFSpeechRecognizer` with `requiresOnDeviceRecognition = true`
- Prints transcription to stdout; errors to stderr; exits 1 on failure
- No network calls, no external models — uses Apple's on-device model (same as Notes)

### `src/transcriber.py`

- Python wrapper: calls `src/transcribe` via `subprocess.run`
- Signature: `def transcribe(audio_path: str, language: str = "it-IT") -> str`
- Handles: file-not-found, binary-not-compiled, timeout, non-zero exit
- No external Python dependencies (stdlib only)

### `src/pipeline.py`

- CLI entrypoint, registered as `transcripto` via Poetry scripts
- Detects if input needs audio extraction or can be transcribed directly
- Writes `output/<stem>.md` with a `# Title` header
- `--extract-only`: extract audio to `output/`, no transcription
- `--batch-extract <dir>`: extract all videos in a folder to `.m4a` next to the source, skips already-converted
- `--watch` mode: monitors `input/` and auto-processes new files

### `build.sh`

- Runs `swiftc src/transcribe.swift -o src/transcribe`
- Checks for `swiftc`; prints a friendly error if Xcode CLI tools are missing

---

## Configuration

All runtime config lives at the top of each module as named constants (no config files needed at this scale):

| Constant           | Module            | Default                                    |
| ------------------ | ----------------- | ------------------------------------------ |
| `VLC_PATH`         | `extract.py`      | `/Applications/VLC.app/Contents/MacOS/VLC` |
| `OUTPUT_DIR`       | `pipeline.py`     | `output/` (repo root)                      |
| `DEFAULT_LANGUAGE` | `transcriber.py`  | `it-IT`                                    |
| `BINARY_PATH`      | `transcriber.py`  | `src/transcribe`                           |

---

## Constraints

- **No external Python dependencies** in `src/` (stdlib only)
- **No network calls** — all transcription is on-device via Apple Speech framework
- **No Homebrew**, no paid APIs, no downloaded models
- Swift binary must be compiled locally with Xcode Command Line Tools
- System: macOS Tahoe 26+ on Apple Silicon (M-series) — `SFSpeechRecognizer` on-device mode requires this

---

## Future

- Vault export: configurable `VAULT_DIR` (via `.env`) to write markdown directly into an Obsidian vault
- Web UI: minimal Flask interface — drop file, get transcription (skip for now, keep the pipeline headless)

---

## Language

All code, comments, variable names, and documentation must be in **English**.
