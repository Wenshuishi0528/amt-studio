import AMTStudioCore
import Foundation
import XCTest

@testable import AMTStudioUI

@MainActor
final class AppModelTests: XCTestCase {
  func testMissingProjectProducesActionableErrorWithoutStartingAJob() {
    let defaults = UserDefaults(
      suiteName: "AMTStudioUITests.\(UUID().uuidString)"
    )!
    let model = AppModel(defaults: defaults, restoreRecent: false)
    model.openProject(
      URL(fileURLWithPath: "/missing/AMT Studio project")
    )
    XCTAssertNotNil(model.errorMessage)
    XCTAssertEqual(model.statusMessage, "操作失败")
    XCTAssertNil(model.editor)
  }

  func testFreshModelDoesNotRestoreOrRunAnythingWhenDisabled() {
    let defaults = UserDefaults(
      suiteName: "AMTStudioUITests.\(UUID().uuidString)"
    )!
    defaults.set("/private/should-not-open", forKey: "AMTStudio.recentProjectPath")
    let model = AppModel(defaults: defaults, restoreRecent: false)
    XCTAssertNil(model.catalog)
    XCTAssertNil(model.snapshot)
    XCTAssertNil(model.editor)
    XCTAssertEqual(model.statusMessage, "请选择一个已有 AMT Studio 项目")
  }

  func testTransportErrorsAreVisibleAndShortNotesKeepMoveHitArea() {
    let transport = AudioTransport()
    let missingAudio = URL(
      fileURLWithPath: "/missing/AMT Studio audio.wav"
    )
    transport.load(audioURL: missingAudio)
    XCTAssertEqual(transport.errorMessages.count, 1)
    XCTAssertTrue(
      transport.errorMessages[0].contains("原曲无法加载")
    )
    transport.loadMIDI(
      url: URL(fileURLWithPath: "/missing/AMT Studio preview.mid")
    )
    XCTAssertEqual(transport.errorMessages.count, 2)
    XCTAssertGreaterThan(PianoRollLayout.minimumMoveHitWidth, 0)
    XCTAssertGreaterThanOrEqual(
      PianoRollLayout.minimumMoveHitWidth,
      12
    )

    let shortNote = EditorNote(
      id: "short-note",
      trackID: "track",
      sourceTrackID: "source-track",
      instrument: "voice",
      onsetSec: 1,
      offsetSec: 1.1,
      pitchMIDI: 60,
      velocity: 64,
      confidence: nil,
      isMainMelodyCandidate: true,
      sourceRunID: "run",
      sourceModel: "model",
      sourceEventIDs: [],
      tags: [],
      extra: [:]
    )
    let moved = NoteGestureProjection.move(
      shortNote,
      translation: CGSize(width: 28, height: -14),
      pointsPerSecond: 28,
      pointsPerSemitone: 14
    )
    XCTAssertEqual(moved.onsetSec, 2, accuracy: 0.000_001)
    XCTAssertEqual(moved.offsetSec, 2.1, accuracy: 0.000_001)
    XCTAssertEqual(moved.pitchMIDI, 61)
    let resized = NoteGestureProjection.resizeRight(
      shortNote,
      translation: CGSize(width: 14, height: 0),
      pointsPerSecond: 28
    )
    XCTAssertEqual(resized.offsetSec, 1.6, accuracy: 0.000_001)
  }

  func testOpenEditUndoRedoExportAndRestart() throws {
    let fixture = try AppFixtureProject()
    defer { fixture.remove() }
    let suiteName = "AMTStudioUITests.\(UUID().uuidString)"
    let defaults = try XCTUnwrap(UserDefaults(suiteName: suiteName))
    defer { defaults.removePersistentDomain(forName: suiteName) }

    let model = AppModel(
      defaults: defaults,
      initialProjectURL: fixture.root,
      restoreRecent: false
    )
    XCTAssertNil(model.catalog)
    model.openInitialProjectIfNeeded()
    XCTAssertEqual(model.bundleChoices.map(\.id), ["bundle-ui"])
    XCTAssertEqual(model.editor?.selectedTrack.id, "candidate-ui")
    let original = try XCTUnwrap(model.notes.first)
    let originalEvents = try Data(contentsOf: fixture.eventsURL)

    let moved = NoteGestureProjection.move(
      original,
      translation: CGSize(width: 5.6, height: -28),
      pointsPerSecond: 28,
      pointsPerSemitone: 14
    )
    model.commit(moved)
    XCTAssertEqual(model.notes.first?.pitchMIDI, original.pitchMIDI + 2)
    XCTAssertEqual(model.editor?.canUndo, true)
    model.undo()
    XCTAssertEqual(model.notes.first, original)
    model.redo()
    XCTAssertEqual(model.notes.first, moved)

    let midiURL = fixture.root.appendingPathComponent(
      "exports/ui-performance.mid"
    )
    let report = try XCTUnwrap(model.exportMIDI(to: midiURL))
    XCTAssertEqual(report.noteCount, 1)
    XCTAssertEqual(
      String(
        data: try Data(contentsOf: midiURL).prefix(4),
        encoding: .ascii
      ),
      "MThd"
    )
    XCTAssertEqual(try Data(contentsOf: fixture.eventsURL), originalEvents)

    let reopened = AppModel(defaults: defaults, restoreRecent: true)
    XCTAssertNil(reopened.catalog)
    reopened.openInitialProjectIfNeeded()
    XCTAssertEqual(reopened.editor?.selectedTrack.id, "candidate-ui")
    XCTAssertEqual(reopened.notes.first, moved)
  }
}

private final class AppFixtureProject {
  let root: URL
  let eventsURL: URL

  init() throws {
    root = FileManager.default.temporaryDirectory
      .appendingPathComponent("AMT Studio UI \(UUID().uuidString)")
    eventsURL = root.appendingPathComponent(
      "runs/ui/normalized/events.jsonl"
    )
    try FileManager.default.createDirectory(
      at: eventsURL.deletingLastPathComponent(),
      withIntermediateDirectories: true
    )
    let audioURL = root.appendingPathComponent("audio/canonical/mix.wav")
    try FileManager.default.createDirectory(
      at: audioURL.deletingLastPathComponent(),
      withIntermediateDirectories: true
    )
    try silentWAV().write(to: audioURL)
    let audioHash = try ProjectLoader.sha256(audioURL)
    try writeFixtureJSON(
      [
        "schema_version": 1,
        "project_id": "ui-project",
        "title": "UI fixture",
        "canonical_audio": [
          "path": "audio/canonical/mix.wav",
          "sha256": audioHash,
        ],
      ],
      to: root.appendingPathComponent("manifest.json")
    )

    let note: [String: Any] = [
      "schema_version": 1,
      "event_id": "ui-note",
      "track_id": "native-ui",
      "instrument": "voice",
      "onset_sec": 0.02,
      "offset_sec": 0.08,
      "pitch_midi": 60.0,
      "quantized_pitch_midi": 60,
      "velocity": 80,
      "confidence": 0.9,
      "is_main_melody_candidate": true,
      "source_run_id": "ui-run",
      "source_model": "ui-model",
      "source_event_ids": ["native-ui-note"],
      "tags": [],
      "extra": [:],
    ]
    var eventData = try JSONSerialization.data(
      withJSONObject: note,
      options: [.sortedKeys]
    )
    eventData.append(0x0A)
    try eventData.write(to: eventsURL)
    let eventHash = try ProjectLoader.sha256(eventsURL)

    let bundleURL = root.appendingPathComponent("exports/bundle-ui")
    try FileManager.default.createDirectory(
      at: bundleURL,
      withIntermediateDirectories: true
    )
    let canonicalURL = bundleURL.appendingPathComponent(
      "canonical_project.json"
    )
    try writeFixtureJSON(
      [
        "schema_version": 1,
        "artifact_type": "amt-canonical-project",
        "project_id": "ui-project",
        "timeline_basis": "original_canonical_mix_seconds",
        "canonical_audio": [
          "path": "audio/canonical/mix.wav",
          "sha256": audioHash,
        ],
        "tracks": [
          [
            "track_id": "candidate-ui",
            "label": "UI candidate",
            "role": "main_melody_candidate",
            "instrument": "voice",
            "event_count": 1,
            "source_events_path":
              "runs/ui/normalized/events.jsonl",
            "provenance": [
              "source_run_id": "ui-run",
              "source_model": "ui-model",
              "run_manifest_sha256":
                String(repeating: "a", count: 64),
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
    try writeFixtureJSON(
      [
        "schema_version": 1,
        "artifact_type": "amt-canonical-bundle",
        "project_id": "ui-project",
        "canonical_audio_sha256": audioHash,
        "status": "succeeded",
        "outputs": [
          [
            "path": "canonical_project.json",
            "sha256": try ProjectLoader.sha256(canonicalURL),
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
}

private func writeFixtureJSON(_ object: Any, to url: URL) throws {
  let data = try JSONSerialization.data(
    withJSONObject: object,
    options: [.prettyPrinted, .sortedKeys]
  )
  try data.write(to: url)
}

private func silentWAV() -> Data {
  let sampleRate: UInt32 = 44_100
  let frameCount: UInt32 = 4_410
  let dataSize = frameCount * 2
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
  data.append(Data(repeating: 0, count: Int(dataSize)))
  return data
}

private func appendLE<T: FixedWidthInteger>(_ value: T, to data: inout Data) {
  var value = value.littleEndian
  withUnsafeBytes(of: &value) { data.append(contentsOf: $0) }
}
