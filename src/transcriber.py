"""Transcription via mlx-whisper — Apple Silicon GPU-accelerated, fully offline."""

import json
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

# --- Long-audio chunking --------------------------------------------------
# Beyond the per-window anti-drift settings, very long files get sliced into
# overlapping chunks transcribed independently: each chunk resets the decoder
# (a hard ceiling on any drift) and bounds the mel-spectrogram size. Chunks
# are merged deterministically by timestamp — no LLM needed. The overlap
# guarantees a sentence straddling a cut is captured whole in one chunk; the
# merge keeps each segment from whichever chunk owns its half of the overlap.
SPLIT_THRESHOLD_SECONDS = 60 * 60   # only files longer than this are chunked
CHUNK_LENGTH_SECONDS = 60 * 60      # ~1h cuts
CHUNK_OVERLAP_SECONDS = 15          # overlap so boundary sentences aren't lost

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


def _audio_duration(wav_path: str) -> float | None:
    """Return WAV duration in seconds via ffprobe, or None."""
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", wav_path],
        capture_output=True, text=True,
    )
    try:
        return float(json.loads(result.stdout)["format"]["duration"])
    except (ValueError, KeyError, json.JSONDecodeError):
        return None


def _slice_wav(src_wav: str, start: float, length: float, out_wav: str) -> None:
    """Cut [start, start+length] out of a 16kHz mono WAV (fast, sample-accurate)."""
    subprocess.run(
        [
            "ffmpeg", "-ss", f"{start}", "-t", f"{length}", "-i", src_wav,
            "-ac", "1", "-ar", "16000", out_wav, "-y", "-loglevel", "error",
        ],
        check=True,
    )


def _whisper(wav_path: str, language: str | None, initial_prompt: str | None) -> dict:
    """Run mlx-whisper with the shared anti-drift decoding params."""
    return mlx_whisper.transcribe(
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


def _chunk_spans(duration: float) -> list[tuple[float, float]]:
    """List of (start, end) covering [0, duration] in overlapping chunks."""
    stride = CHUNK_LENGTH_SECONDS - CHUNK_OVERLAP_SECONDS
    spans: list[tuple[float, float]] = []
    start = 0.0
    while start < duration:
        spans.append((start, min(start + CHUNK_LENGTH_SECONDS, duration)))
        start += stride
    return spans


def _merge_chunk_segments(
    chunk_segments: list[list[dict]], spans: list[tuple[float, float]], duration: float
) -> list[dict]:
    """Stitch per-chunk (chunk-relative) segments into one absolute-timestamp list.

    Segments are shifted to absolute time, then deduplicated across each overlap
    by a midpoint cut: between chunk i and i+1 the cut is the middle of their
    overlap zone; chunk i keeps segments centered before its right cut, chunk i+1
    keeps those centered at/after it. No text matching — purely positional.
    """
    cuts = [
        (spans[i + 1][0] + spans[i][1]) / 2.0  # mid of [next.start, this.end]
        for i in range(len(spans) - 1)
    ]
    merged: list[dict] = []
    for i, segs in enumerate(chunk_segments):
        lower = cuts[i - 1] if i > 0 else 0.0
        upper = cuts[i] if i < len(cuts) else duration + 1.0
        offset = spans[i][0]
        for seg in segs:
            a = (seg.get("start") or 0.0) + offset
            b = (seg.get("end") or 0.0) + offset
            if lower <= (a + b) / 2.0 < upper:
                merged.append({"start": a, "end": b, "text": seg.get("text") or ""})
    merged.sort(key=lambda s: s["start"])
    return merged


def _transcribe_chunked(
    wav_path: str, duration: float, language: str | None, initial_prompt: str | None
) -> list[dict]:
    """Transcribe a long WAV in overlapping chunks; return merged absolute segments."""
    spans = _chunk_spans(duration)
    print(
        f"  Long audio ({duration / 60:.0f} min) → {len(spans)} chunk(s) of "
        f"{CHUNK_LENGTH_SECONDS // 60}min, {CHUNK_OVERLAP_SECONDS}s overlap"
    )
    chunk_segments: list[list[dict]] = []
    for i, (start, end) in enumerate(spans, 1):
        chunk_wav = f"{wav_path}.chunk{i}.wav"
        _slice_wav(wav_path, start, end - start, chunk_wav)
        try:
            print(f"  [chunk {i}/{len(spans)}] {start / 60:.0f}–{end / 60:.0f} min")
            result = _whisper(chunk_wav, language, initial_prompt)
        finally:
            Path(chunk_wav).unlink(missing_ok=True)
        chunk_segments.append(result.get("segments") or [])
    return _merge_chunk_segments(chunk_segments, spans, duration)


def transcribe(
    audio_path: str,
    language: str = DEFAULT_LANGUAGE,
    initial_prompt: str | None = None,
) -> str:
    """Transcribe audio to paragraph-segmented text.

    `initial_prompt` biases Whisper toward domain vocabulary (titles, proper
    nouns, acronyms) — pass the lecture/video title when available. Audio longer
    than SPLIT_THRESHOLD_SECONDS is transcribed in overlapping chunks and merged.
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
        duration = _audio_duration(wav_path)
        if duration and duration > SPLIT_THRESHOLD_SECONDS:
            segments = _transcribe_chunked(wav_path, duration, language, initial_prompt)
            return _segments_to_paragraphs(segments)

        result = _whisper(wav_path, language, initial_prompt)
        segments = result.get("segments") or []
        if segments:
            return _segments_to_paragraphs(segments)
        return (result.get("text") or "").strip()
    finally:
        Path(wav_path).unlink(missing_ok=True)


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
