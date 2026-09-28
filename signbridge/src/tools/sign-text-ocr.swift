// Offline macOS Vision OCR for caption crops. Prints one JSON record per image.
import Foundation
import Vision

let request = VNRecognizeTextRequest()
request.recognitionLevel = .accurate
request.usesLanguageCorrection = false
request.recognitionLanguages = ["zh-Hans", "en-US"]

for path in CommandLine.arguments.dropFirst() {
    do {
        let handler = VNImageRequestHandler(url: URL(fileURLWithPath: path), options: [:])
        try handler.perform([request])
        let results: [[String: Any]] = (request.results ?? []).compactMap { result in
            guard let candidate = result.topCandidates(1).first else { return nil }
            return ["text": candidate.string, "confidence": Double(candidate.confidence)]
        }
        let encoded = try JSONSerialization.data(withJSONObject: ["image": path, "lines": results], options: [.fragmentsAllowed, .sortedKeys])
        print(String(data: encoded, encoding: .utf8)!)
    } catch {
        fputs("OCR failed for \(path): \(error)\n", stderr)
        exit(1)
    }
}
