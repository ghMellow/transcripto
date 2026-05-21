"""Transcriber using SFSpeechRecognizer via PyObjC (no subprocess, no binary)."""

import time
from pathlib import Path

from Foundation import NSURL, NSRunLoop, NSDate
from Speech import SFSpeechRecognizer, SFSpeechURLRecognitionRequest

DEFAULT_LANGUAGE = "it-IT"
TIMEOUT = 600  # seconds


def transcribe(audio_path: str, language: str = DEFAULT_LANGUAGE) -> str:
    path = Path(audio_path)
    if not path.exists():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    url = NSURL.fileURLWithPath_(str(path.absolute()))
    from Foundation import NSLocale
    locale = NSLocale.alloc().initWithLocaleIdentifier_(language)
    recognizer = SFSpeechRecognizer.alloc().initWithLocale_(locale)

    if recognizer is None:
        raise RuntimeError(f"SFSpeechRecognizer unavailable for locale {language}")

    state: dict = {"text": None, "error": None, "done": False}

    def auth_callback(status):
        # status 3 == SFSpeechRecognizerAuthorizationStatusAuthorized
        if status != 3:
            state["error"] = f"Speech recognition not authorized (status: {status})"
            state["done"] = True
            return

        request = SFSpeechURLRecognitionRequest.alloc().initWithURL_(url)
        request.setRequiresOnDeviceRecognition_(True)
        request.setShouldReportPartialResults_(False)

        def task_callback(result, error):
            if error:
                state["error"] = str(error)
                state["done"] = True
                return
            if result and result.isFinal():
                state["text"] = str(result.bestTranscription().formattedString())
                state["done"] = True

        recognizer.recognitionTaskWithRequest_resultHandler_(request, task_callback)

    SFSpeechRecognizer.requestAuthorization_(auth_callback)

    # Drive the main run loop so callbacks (delivered on the main queue) can fire.
    start = time.monotonic()
    while not state["done"]:
        NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.1))
        if time.monotonic() - start > TIMEOUT:
            raise RuntimeError("Transcription timed out")

    if state["error"]:
        raise RuntimeError(f"Transcription failed: {state['error']}")

    return state["text"] or ""
