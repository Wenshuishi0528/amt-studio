import CryptoKit
import Foundation
import XCTest

final class AMTStudioAppUITests: XCTestCase {
  @MainActor
  func testOpenWaveformPlaybackReviewEditUndoAndRestart() throws {
    continueAfterFailure = false
    let fixture = try UITestProject()
    defer { fixture.remove() }
    let app = XCUIApplication()
    defer { app.terminate() }
    app.launchArguments = [
      "--project",
      fixture.root.path,
      "--no-recent-project",
      "-ApplePersistenceIgnoreState",
      "YES",
    ]
    app.launch()
    ensureWindow(for: app)
    let status = app.descendants(matching: .any)["status-message"]
    XCTAssertTrue(
      status.waitForExistence(timeout: 8),
      "应用没有打开 UI 测试项目"
    )
    XCTAssertTrue(
      waitForLabel(status, prefix: "候选轨 UI candidate"),
      "应用没有自动选择唯一候选轨"
    )
    let waveform = app.descendants(matching: .any)["audio-waveform"]
    XCTAssertTrue(
      waitForLabel(waveform, prefix: "已加载"),
      "音频波形没有完成解码"
    )
    XCTAssertTrue(app.descendants(matching: .any)["piano-roll"].exists)
    XCTAssertTrue(app.sliders["review-confidence-threshold"].exists)
    XCTAssertTrue(app.buttons["review-next"].isEnabled)

    let slider = app.sliders["transport-position"]
    let playButton = app.buttons["transport-play-pause"]
    XCTAssertTrue(slider.waitForExistence(timeout: 3))
    XCTAssertTrue(playButton.waitForExistence(timeout: 3))
    let initialPosition = String(describing: slider.value)
    playButton.click()
    Thread.sleep(forTimeInterval: 0.6)
    let advancedPosition = String(describing: slider.value)
    XCTAssertNotEqual(initialPosition, advancedPosition)
    playButton.click()

    app.buttons["review-next"].click()
    XCTAssertTrue(waitForLabel(status, prefix: "待复核音符 1 / 1"))

    let stepper = app.steppers["note-pitch-stepper"]
    XCTAssertTrue(stepper.waitForExistence(timeout: 3))
    let onsetField = app.textFields["note-onset"]
    XCTAssertTrue(onsetField.waitForExistence(timeout: 3))
    onsetField.click()
    onsetField.typeKey("a", modifierFlags: .command)
    onsetField.typeText("0.350")
    onsetField.typeKey(.return, modifierFlags: [])

    let undoButton = enabledButton("undo-edit", in: app)
    XCTAssertTrue(undoButton.waitForExistence(timeout: 4))
    undoButton.click()
    let redoButton = enabledButton("redo-edit", in: app)
    XCTAssertTrue(redoButton.waitForExistence(timeout: 4))
    redoButton.click()
    XCTAssertTrue(
      enabledButton("undo-edit", in: app).waitForExistence(timeout: 4)
    )

    app.terminate()
    app.launch()
    ensureWindow(for: app)
    XCTAssertTrue(status.waitForExistence(timeout: 8))
    XCTAssertTrue(waitForLabel(status, prefix: "候选轨 UI candidate"))
    XCTAssertTrue(
      enabledButton("undo-edit", in: app).waitForExistence(timeout: 4)
    )
  }

  @MainActor
  private func ensureWindow(for app: XCUIApplication) {
    app.activate()
    if !app.windows.firstMatch.waitForExistence(timeout: 2) {
      app.typeKey("n", modifierFlags: .command)
    }
  }

  @MainActor
  private func enabledButton(
    _ identifier: String,
    in app: XCUIApplication
  ) -> XCUIElement {
    app.buttons
      .matching(identifier: identifier)
      .matching(NSPredicate(format: "enabled == true"))
      .firstMatch
  }

  @MainActor
  private func waitForLabel(
    _ element: XCUIElement,
    prefix: String,
    timeout: TimeInterval = 4
  ) -> Bool {
    let predicate = NSPredicate(
      format:
        "exists == true AND (label BEGINSWITH %@ OR value BEGINSWITH %@)",
      prefix,
      prefix
    )
    let expectation = XCTNSPredicateExpectation(
      predicate: predicate,
      object: element
    )
    return XCTWaiter.wait(
      for: [expectation],
      timeout: timeout
    ) == .completed
  }
}

private final class UITestProject {
  let root: URL

  init() throws {
    root = FileManager.default.temporaryDirectory
      .appendingPathComponent(
        "AMT Studio 界面测试 \(UUID().uuidString)",
        isDirectory: true
      )
    let audioURL = root.appendingPathComponent("audio/canonical/测试.wav")
    try FileManager.default.createDirectory(
      at: audioURL.deletingLastPathComponent(),
      withIntermediateDirectories: true
    )
    try syntheticWAV().write(to: audioURL)
    let audioHash = try sha256(audioURL)

    try writeJSON(
      [
        "schema_version": 1,
        "project_id": "ui-test-project",
        "title": "界面测试",
        "canonical_audio": [
          "path": "audio/canonical/测试.wav",
          "sha256": audioHash,
        ],
      ],
      to: root.appendingPathComponent("manifest.json")
    )

    let eventsURL = root.appendingPathComponent(
      "runs/ui/normalized/events.jsonl"
    )
    try FileManager.default.createDirectory(
      at: eventsURL.deletingLastPathComponent(),
      withIntermediateDirectories: true
    )
    let events: [[String: Any]] = [
      note(
        id: "ui-low",
        onset: 0.2,
        offset: 0.8,
        pitch: 60,
        confidence: 0.2
      ),
      note(
        id: "ui-unknown",
        onset: 1.2,
        offset: 1.8,
        pitch: 64,
        confidence: nil
      ),
    ]
    var eventData = Data()
    for event in events {
      eventData.append(
        try JSONSerialization.data(
          withJSONObject: event,
          options: [.sortedKeys]
        )
      )
      eventData.append(0x0A)
    }
    try eventData.write(to: eventsURL)
    let eventHash = try sha256(eventsURL)

    let bundleURL = root.appendingPathComponent("exports/ui-bundle")
    try FileManager.default.createDirectory(
      at: bundleURL,
      withIntermediateDirectories: true
    )
    let canonicalURL = bundleURL.appendingPathComponent(
      "canonical_project.json"
    )
    try writeJSON(
      [
        "schema_version": 1,
        "artifact_type": "amt-canonical-project",
        "project_id": "ui-test-project",
        "timeline_basis": "original_canonical_mix_seconds",
        "canonical_audio": [
          "path": "audio/canonical/测试.wav",
          "sha256": audioHash,
        ],
        "tracks": [
          [
            "track_id": "ui-candidate",
            "label": "UI candidate",
            "role": "main_melody_candidate",
            "instrument": "voice",
            "event_count": events.count,
            "source_events_path": "runs/ui/normalized/events.jsonl",
            "provenance": [
              "source_run_id": "ui-run",
              "source_model": "ui-model",
              "run_manifest_sha256": String(repeating: "a", count: 64),
              "normalized_artifact_sha256": eventHash,
            ],
          ]
        ],
        "rhythm": [
          "tempo_map": [["time_sec": 0.0, "bpm": 120.0]],
          "meter_map": [
            [
              "time_sec": 0.0,
              "numerator": 4,
              "denominator": 4,
            ]
          ],
        ],
      ],
      to: canonicalURL
    )
    let canonicalData = try Data(contentsOf: canonicalURL)
    try writeJSON(
      [
        "schema_version": 1,
        "artifact_type": "amt-canonical-bundle",
        "project_id": "ui-test-project",
        "canonical_audio_sha256": audioHash,
        "status": "succeeded",
        "outputs": [
          [
            "path": "canonical_project.json",
            "sha256": try sha256(canonicalURL),
            "size_bytes": canonicalData.count,
          ]
        ],
        "limitations": [],
      ],
      to: bundleURL.appendingPathComponent("bundle_manifest.json")
    )
  }

  func remove() {
    try? FileManager.default.removeItem(at: root)
  }

  private func note(
    id: String,
    onset: Double,
    offset: Double,
    pitch: Double,
    confidence: Double?
  ) -> [String: Any] {
    var value: [String: Any] = [
      "schema_version": 1,
      "event_id": id,
      "track_id": "native-ui",
      "instrument": "voice",
      "onset_sec": onset,
      "offset_sec": offset,
      "pitch_midi": pitch,
      "quantized_pitch_midi": Int(pitch),
      "velocity": 80,
      "is_main_melody_candidate": true,
      "source_run_id": "ui-run",
      "source_model": "ui-model",
      "source_event_ids": [id],
      "tags": [],
      "extra": [:],
    ]
    if let confidence {
      value["confidence"] = confidence
    }
    return value
  }
}

private func writeJSON(_ object: Any, to url: URL) throws {
  let data = try JSONSerialization.data(
    withJSONObject: object,
    options: [.prettyPrinted, .sortedKeys]
  )
  try data.write(to: url)
}

private func sha256(_ url: URL) throws -> String {
  SHA256.hash(data: try Data(contentsOf: url))
    .map { String(format: "%02x", $0) }
    .joined()
}

private func syntheticWAV() -> Data {
  let sampleRate: UInt32 = 44_100
  let frameCount = Int(sampleRate * 3)
  let dataSize = UInt32(frameCount * 2)
  var data = Data("RIFF".utf8)
  appendLE(36 + dataSize, to: &data)
  data.append(Data("WAVEfmt ".utf8))
  appendLE(UInt32(16), to: &data)
  appendLE(UInt16(1), to: &data)
  appendLE(UInt16(1), to: &data)
  appendLE(sampleRate, to: &data)
  appendLE(sampleRate * 2, to: &data)
  appendLE(UInt16(2), to: &data)
  appendLE(UInt16(16), to: &data)
  data.append(Data("data".utf8))
  appendLE(dataSize, to: &data)
  for frame in 0..<frameCount {
    let sample: Int16 = (frame / 220) % 2 == 0 ? 12_000 : -12_000
    appendLE(sample, to: &data)
  }
  return data
}

private func appendLE<T: FixedWidthInteger>(_ value: T, to data: inout Data) {
  var value = value.littleEndian
  withUnsafeBytes(of: &value) { data.append(contentsOf: $0) }
}
