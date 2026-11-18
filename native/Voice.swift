import AVFoundation
import Speech

/// Dictation for the message box, using the Mac's own speech recognition. Nothing is recorded to disk.
/// Recognition stays on this Mac when the language supports it; otherwise macOS sends the audio to Apple,
/// which the system's permission prompt says before the first use.
final class VoiceInput {
    static let languages = ["zh-TW", "en-US", "ja-JP"]
    private let engine = AVAudioEngine()
    private var request: SFSpeechAudioBufferRecognitionRequest?
    private var task: SFSpeechRecognitionTask?
    private var limit: Timer?
    private var round = 0
    private let report: ([String: Any]) -> Void

    init(report: @escaping ([String: Any]) -> Void) { self.report = report }

    func start(language: String) {
        guard task == nil else { return }
        switch AVCaptureDevice.authorizationStatus(for: .audio) {
        case .authorized: askSpeech(language)
        case .notDetermined: AVCaptureDevice.requestAccess(for: .audio) { ok in DispatchQueue.main.async { if ok { self.askSpeech(language) } else { self.fail("mic") } } }
        default: fail("mic")
        }
    }

    private func askSpeech(_ language: String) {
        switch SFSpeechRecognizer.authorizationStatus() {
        case .authorized: begin(language)
        case .notDetermined: SFSpeechRecognizer.requestAuthorization { status in DispatchQueue.main.async { if status == .authorized { self.begin(language) } else { self.fail("speech") } } }
        default: fail("speech")
        }
    }

    private func begin(_ language: String) {
        guard task == nil else { return }
        let wanted = VoiceInput.languages.contains(language) ? language : (Locale.preferredLanguages.first ?? "zh-TW")
        guard let recognizer = SFSpeechRecognizer(locale: Locale(identifier: wanted)) ?? SFSpeechRecognizer(locale: Locale(identifier: "zh-TW")), recognizer.isAvailable else { fail("unavailable"); return }
        let request = SFSpeechAudioBufferRecognitionRequest()
        request.shouldReportPartialResults = true
        if recognizer.supportsOnDeviceRecognition { request.requiresOnDeviceRecognition = true }
        let input = engine.inputNode
        let format = input.outputFormat(forBus: 0)
        guard format.sampleRate > 0, format.channelCount > 0 else { fail("mic"); return }
        input.removeTap(onBus: 0)
        input.installTap(onBus: 0, bufferSize: 1024, format: format) { buffer, _ in request.append(buffer) }
        engine.prepare()
        do { try engine.start() } catch { input.removeTap(onBus: 0); fail("mic"); return }
        self.request = request; round += 1
        task = recognizer.recognitionTask(with: request) { [weak self] result, error in
            DispatchQueue.main.async {
                guard let self = self, self.task != nil else { return }
                if let result = result { self.report(["state": "partial", "text": result.bestTranscription.formattedString]) }
                if error != nil || result?.isFinal == true { self.finish() }
            }
        }
        report(["state": "listening", "onDevice": request.requiresOnDeviceRecognition])
        limit = Timer.scheduledTimer(withTimeInterval: 120, repeats: false) { [weak self] _ in self?.stop() }  // a forgotten microphone does not stay open
    }

    /// Stop listening; the last words still arrive, then "ended".
    func stop() {
        guard task != nil else { return }
        stopAudio()
        request?.endAudio()
        let stopping = round
        DispatchQueue.main.asyncAfter(deadline: .now() + 3) { [weak self] in if self?.round == stopping { self?.finish() } }  // in case the recognizer never says it is done; a new round is left alone
    }

    private func stopAudio() {
        limit?.invalidate(); limit = nil
        if engine.isRunning { engine.stop() }
        engine.inputNode.removeTap(onBus: 0)
    }

    private func finish() {
        guard let running = task else { return }
        task = nil; request = nil
        stopAudio()
        running.cancel()
        report(["state": "ended"])
    }

    private func fail(_ reason: String) {
        report(["state": "error", "reason": reason])
    }
}
