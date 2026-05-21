"""Python wrapper around the compiled Swift Speech binary."""

import subprocess
from pathlib import Path

BINARY_PATH = Path(__file__).parent / "transcribe"
DEFAULT_LANGUAGE = "it-IT"
TIMEOUT = 600  # seconds — allow long audio files


def transcribe(audio_path: str, language: str = DEFAULT_LANGUAGE) -> str:
    path = Path(audio_path)

    if not path.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    if not BINARY_PATH.exists():
        raise RuntimeError(
            f"Swift binary not found at {BINARY_PATH}. Run ./build.sh first."
        )

    result = subprocess.run(
        [str(BINARY_PATH), str(path), language],
        capture_output=True,
        text=True,
        timeout=TIMEOUT,
    )

    if result.returncode != 0:
        raise RuntimeError(f"Transcription failed: {result.stderr.strip()}")

    return result.stdout.strip()
