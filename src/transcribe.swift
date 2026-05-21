import Foundation
import Speech

guard CommandLine.arguments.count >= 2 else {
    fputs("Usage: transcribe <audio_path> [language]\n", stderr)
    exit(1)
}

let audioPath = CommandLine.arguments[1]
let language  = CommandLine.arguments.count >= 3 ? CommandLine.arguments[2] : "it-IT"
let audioURL  = URL(fileURLWithPath: audioPath)

guard FileManager.default.fileExists(atPath: audioPath) else {
    fputs("Error: file not found: \(audioPath)\n", stderr)
    exit(1)
}

guard let recognizer = SFSpeechRecognizer(locale: Locale(identifier: language)) else {
    fputs("Error: SFSpeechRecognizer unavailable for locale \(language)\n", stderr)
    exit(1)
}

// requestAuthorization and recognitionTask both deliver callbacks on the main queue.
// dispatchMain() below keeps the run loop alive so those callbacks can fire.
SFSpeechRecognizer.requestAuthorization { status in
    guard status == .authorized else {
        fputs("Error: speech recognition not authorized (status: \(status.rawValue))\n", stderr)
        exit(1)
    }

    let request = SFSpeechURLRecognitionRequest(url: audioURL)
    request.requiresOnDeviceRecognition = true
    request.shouldReportPartialResults = false

    recognizer.recognitionTask(with: request) { result, error in
        if let error = error {
            fputs("Error: \(error.localizedDescription)\n", stderr)
            exit(1)
        }
        guard let result = result, result.isFinal else { return }
        print(result.bestTranscription.formattedString)
        exit(0)
    }
}

dispatchMain()
