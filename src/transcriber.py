"""Transcription via mlx-whisper — Apple Silicon GPU-accelerated, fully offline."""

import os
import subprocess
import tempfile
from pathlib import Path

import mlx_whisper

try:
    from huggingface_hub.utils import disable_progress_bars
    disable_progress_bars()
except Exception:
    pass

WHISPER_MODEL = "mlx-community/whisper-large-v3-turbo"
# WHISPER_MODEL = "mlx-community/whisper-base"  # dev/test: faster, lower quality
DEFAULT_LANGUAGE = None  # None = Whisper auto-detects from first 30s of audio

# --- Anti-drift decoding params (matter most on long files) ---------------
# Whisper transcribes in 30s windows; there is no whole-file context limit.
# The real failure mode on long audio is hallucination drift: a bad window
# (music, silence, overlapping speech) gets fed as the prompt to the next
# window and the error cascades (runaway repetitions / invented sentences).
# CONDITION_ON_PREVIOUS_TEXT=False is the main lever — it stops that cascade
# by decoding each window independently. The thresholds below let Whisper
# detect a degenerate window and retry it at a higher temperature.
CONDITION_ON_PREVIOUS_TEXT = False  # don't let a bad window poison the next
TEMPERATURE = (0.0, 0.2, 0.4, 0.6, 0.8, 1.0)  # fallback ladder on failed windows
COMPRESSION_RATIO_THRESHOLD = 2.4   # above this = repetitive garbage → retry
LOGPROB_THRESHOLD = -1.0            # below this avg logprob = low confidence → retry
NO_SPEECH_THRESHOLD = 0.6           # above this no-speech prob = treat as silence

# --- Paragraph segmentation -----------------------------------------------
# Whisper returns ~sentence-sized segments with timestamps. We group them into
# readable paragraphs instead of one wall of text: a new paragraph starts on a
# noticeable silence gap, or when the current one grows too long (continuous
# speech with no pauses still gets broken up).
PARAGRAPH_GAP_SECONDS = 2.0   # silence between segments that starts a new paragraph
PARAGRAPH_MAX_CHARS = 700     # hard cap so gapless speech still breaks


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


def _segments_to_paragraphs(segments: list[dict]) -> str:
    """Join Whisper segments into readable paragraphs using pause + length cues."""
    paragraphs: list[str] = []
    current: list[str] = []
    current_len = 0
    prev_end: float | None = None

    for seg in segments:
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        start = seg.get("start")
        gap = (start - prev_end) if (prev_end is not None and start is not None) else 0.0

        if current and (gap >= PARAGRAPH_GAP_SECONDS or current_len >= PARAGRAPH_MAX_CHARS):
            paragraphs.append(" ".join(current))
            current, current_len = [], 0

        current.append(text)
        current_len += len(text) + 1
        prev_end = seg.get("end", prev_end)

    if current:
        paragraphs.append(" ".join(current))
    return "\n\n".join(paragraphs)


def transcribe(
    audio_path: str,
    language: str = DEFAULT_LANGUAGE,
    initial_prompt: str | None = None,
) -> str:
    """Transcribe audio to paragraph-segmented text.

    `initial_prompt` biases Whisper toward domain vocabulary (titles, proper
    nouns, acronyms) — pass the lecture/video title when available.
    """
    path = Path(audio_path)
    if not path.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    # Temp WAV in the system temp dir — never write next to the user's source
    # file (which may live on a read-only volume).
    fd, wav_path = tempfile.mkstemp(suffix="_16k.wav")
    os.close(fd)
    _preprocess(audio_path, wav_path)

    try:
        result = mlx_whisper.transcribe(
            wav_path,
            path_or_hf_repo=WHISPER_MODEL,
            language=language,
            initial_prompt=initial_prompt,
            verbose=False,
            condition_on_previous_text=CONDITION_ON_PREVIOUS_TEXT,
            temperature=TEMPERATURE,
            compression_ratio_threshold=COMPRESSION_RATIO_THRESHOLD,
            logprob_threshold=LOGPROB_THRESHOLD,
            no_speech_threshold=NO_SPEECH_THRESHOLD,
        )
    finally:
        Path(wav_path).unlink(missing_ok=True)

    segments = result.get("segments") or []
    if segments:
        return _segments_to_paragraphs(segments)
    return (result.get("text") or "").strip()
