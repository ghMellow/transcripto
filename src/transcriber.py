"""Transcription via mlx-whisper — Apple Silicon GPU-accelerated, fully offline."""

import subprocess
from pathlib import Path

import mlx_whisper

WHISPER_MODEL = "mlx-community/whisper-large-v3-turbo"
# WHISPER_MODEL = "mlx-community/whisper-base"  # dev/test: faster, lower quality
DEFAULT_LANGUAGE = "it"


def _preprocess(input_path: str, output_path: str) -> str:
    """Convert to 16kHz mono WAV for optimal Whisper input."""
    subprocess.run(
        [
            "ffmpeg", "-i", input_path,
            "-ac", "1", "-ar", "16000",
            output_path, "-y", "-loglevel", "error",
        ],
        check=True,
    )
    return output_path


def transcribe(audio_path: str, language: str = DEFAULT_LANGUAGE) -> str:
    path = Path(audio_path)
    if not path.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    wav_path = str(path.parent / (path.stem + "_16k.wav"))
    _preprocess(audio_path, wav_path)

    try:
        result = mlx_whisper.transcribe(
            wav_path,
            path_or_hf_repo=WHISPER_MODEL,
            language=language,
        )
    finally:
        Path(wav_path).unlink(missing_ok=True)

    return result["text"]
