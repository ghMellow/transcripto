# Why this project is on standby

## The blocker: TCC on macOS 26 Tahoe

macOS 26 (Tahoe) enforces a strict privacy rule: any process that calls
`SFSpeechRecognizer` (Apple's on-device speech recognition framework) must have
`NSSpeechRecognitionUsageDescription` declared in a valid, **signed** `Info.plist`
associated with its binary.

When this key is missing or unrecognized, macOS does not show a permission dialog —
it **crashes the process immediately** (SIGABRT, exit 134, namespace TCC).

## What we tried

### 1. Swift CLI binary (`src/transcribe.swift`)

Compiled with `swiftc`, run as a subprocess from Python.

- Embedded `Info.plist` via linker flag (`-sectcreate __TEXT __info_plist`)
- Wrapped in a minimal `.app` bundle
- Ad-hoc signed with `codesign --sign -`

**Result**: crash every time. macOS 26 does not accept ad-hoc signed binaries
for speech recognition — TCC reads the bundle but still crashes.

**Crash evidence** (`~/Library/Logs/DiagnosticReports/transcribe-*.ips`):
```
termination → namespace: TCC
details: "This app has crashed because it attempted to access privacy-sensitive
data without a usage description. The app's Info.plist must contain an
NSSpeechRecognitionUsageDescription key..."
```

### 2. PyObjC — calling `SFSpeechRecognizer` directly from Python

Replaced the Swift subprocess with `pyobjc-framework-Speech`, calling
`SFSpeechRecognizer` inline from the Python process.

**Result**: same crash, same TCC error. Python (Homebrew) has no
`NSSpeechRecognitionUsageDescription` in its binary, so macOS 26 crashes it too.

## Root cause

To use `SFSpeechRecognizer` on macOS 26 without crashing, the requesting binary
needs one of:

| Path | Requirement |
| ---- | ----------- |
| Proper `.app` bundle, Developer ID signed | Apple Developer account ($99/year) |
| Notarized and distributed via App Store | Same |
| Manual TCC database edit | Requires disabling SIP |

None of these are acceptable for a personal local tool.

## What would unblock this

### Option A — Apple Developer account
Sign the `.app` bundle with a real Developer ID certificate. TCC accepts it,
the permission dialog appears once, done. Cost: $99/year.

### Option B — `mlx-whisper` as transcription engine
Drop `SFSpeechRecognizer` entirely. Use `mlx-whisper` (pip-installable, free,
Apple Silicon GPU-accelerated via Metal, runs 100% offline). Model quality is
excellent for Italian. First run downloads ~1.5 GB; after that it is fully local.
Downside: not Apple's model — different from the one Notes uses.

### Option C — Wait for Apple to relax TCC for CLI tools
Unlikely.

## Current state of the repo

The pipeline code (`src/pipeline.py`, `src/extract.py`) is complete and correct.
The Swift binary and the PyObjC transcriber both exist in the repo but are broken
by the TCC issue above. Only the transcription step is blocked — everything else
(VLC extraction, markdown output, watch mode, Poetry CLI) works.
