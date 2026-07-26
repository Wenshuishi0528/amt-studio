import AMTStudioCore
import Foundation
import XCTest

@testable import AMTStudioUI

@MainActor
final class AppModelTests: XCTestCase {
  func testConfiguredRealProjectOpensWithoutBlockingMainActor() async throws {
    guard
      let projectPath = ProcessInfo.processInfo.environment[
        "AMT_STUDIO_REAL_PROJECT"
      ]
    else {
      throw XCTSkip("Set AMT_STUDIO_REAL_PROJECT for private integration.")
    }
    let model = AppModel(
      initialProjectURL: URL(fileURLWithPath: projectPath),
      restoreRecent: false,
      persistRecentProject: false
    )
    let start = ContinuousClock.now
    model.openInitialProjectIfNeeded()
    let returnLatency = start.duration(to: .now)
    XCTAssertLessThan(returnLatency, .milliseconds(100))

    await model.waitForProjectLoadForTesting()

    XCTAssertEqual(model.catalog?.rootURL.path, projectPath)
    XCTAssertNotNil(model.snapshot)
    XCTAssertNotNil(model.editor)
    if let expectedTrack = ProcessInfo.processInfo.environment[
      "AMT_STUDIO_REAL_TRACK"
    ] {
      XCTAssertEqual(model.editor?.selectedTrack.id, expectedTrack)
    }

    let output = FileManager.default.temporaryDirectory.appendingPathComponent(
      "AMTStudio-real-version-\(UUID().uuidString).mid"
    )
    defer { try? FileManager.default.removeItem(at: output) }
    let report = try XCTUnwrap(model.exportArrangementMIDI(to: output))
    XCTAssertGreaterThan(report.trackCount, 0)
    XCTAssertGreaterThan(report.noteCount, 0)
    XCTAssertEqual(
      String(
        data: try Data(contentsOf: output).prefix(4),
        encoding: .ascii
      ),
      "MThd"
    )
  }

  func testConfiguredBetaProjectAutomaticallyRefreshesJobState() async throws {
    guard
      let projectPath = ProcessInfo.processInfo.environment[
        "AMT_STUDIO_BETA_PROJECT"
      ]
    else {
      throw XCTSkip("Set AMT_STUDIO_BETA_PROJECT for live Hyak integration.")
    }
    let model = AppModel(
      initialProjectURL: URL(fileURLWithPath: projectPath),
      restoreRecent: false,
      persistRecentProject: false
    )
    model.openInitialProjectIfNeeded()
    await model.waitForProjectLoadForTesting()
    XCTAssertEqual(model.betaProjectURL?.path, projectPath)
    try await Task.sleep(for: .seconds(22))
    XCTAssertNotNil(model.betaJobID)
    XCTAssertNotNil(model.betaSlurmState)
    XCTAssertNotEqual(model.betaSlurmState, "PENDING")
  }

  func testMissingProjectProducesActionableErrorWithoutStartingAJob() async {
    let defaults = UserDefaults(
      suiteName: "AMTStudioUITests.\(UUID().uuidString)"
    )!
    let model = AppModel(defaults: defaults, restoreRecent: false)
    model.openProject(
      URL(fileURLWithPath: "/missing/AMT Studio project")
    )
    await model.waitForProjectLoadForTesting()
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

  func testWaveformReadsPCMAndConfidenceQueueExcludesUnknownValues() async throws {
    let waveformURL = FileManager.default.temporaryDirectory
      .appendingPathComponent("AMT Studio 波形 \(UUID().uuidString).wav")
    defer { try? FileManager.default.removeItem(at: waveformURL) }
    try pcmWAV(samples: [0, 0, 0, 0, .max, .min, 0, 0])
      .write(to: waveformURL)
    let waveform = try await AudioWaveformLoader.load(
      url: waveformURL,
      binCount: 4
    )
    XCTAssertEqual(waveform.count, 4)
    XCTAssertEqual(waveform[0], 0, accuracy: 0.000_001)
    XCTAssertGreaterThan(waveform[2], 0.99)

    let queue = ConfidenceReviewQueue.notes(
      from: [
        reviewNote(id: "unknown", onset: 0, confidence: nil),
        reviewNote(id: "lowest", onset: 8, confidence: 0.1),
        reviewNote(id: "tie-later", onset: 4, confidence: 0.2),
        reviewNote(id: "tie-earlier", onset: 2, confidence: 0.2),
        reviewNote(id: "high", onset: 1, confidence: 0.9),
      ],
      threshold: 0.5
    )
    XCTAssertEqual(
      queue.map(\.id),
      ["lowest", "tie-earlier", "tie-later"]
    )
    XCTAssertEqual(
      WaveformLayout.audioWidth(
        viewWidth: 1_000,
        audioDuration: 100,
        timelineDuration: 125
      ),
      800,
      accuracy: 0.000_001
    )

    let transport = AudioTransport()
    transport.load(audioURL: waveformURL)
    transport.seek(to: 0.000_05)
    transport.load(audioURL: waveformURL)
    XCTAssertEqual(transport.currentTime, 0.000_05, accuracy: 0.000_001)
  }

  func testMelodyCoverageReportsLongVoiceGapsWithoutCallingThemErrors() {
    let voice = [
      reviewNote(
        id: "voice-a",
        trackID: "voice",
        onset: 5,
        offset: 7
      ),
      reviewNote(
        id: "voice-b",
        trackID: "voice",
        onset: 12,
        offset: 13
      ),
    ]
    let accompaniment = [
      reviewNote(
        id: "guitar-a",
        trackID: "guitar",
        onset: 0,
        offset: 6
      ),
      reviewNote(
        id: "piano-a",
        trackID: "piano",
        onset: 8,
        offset: 18
      ),
    ]
    let gaps = MelodyCoverageAnalyzer.gaps(
      voiceNotes: voice,
      allNotes: voice + accompaniment,
      voiceTrackID: "voice",
      duration: 20
    )

    XCTAssertEqual(
      gaps.map { [$0.startSec, $0.endSec] },
      [[0, 5], [7, 12], [13, 20]]
    )
    XCTAssertEqual(gaps.map(\.otherTrackCount), [1, 1, 1])
    XCTAssertEqual(gaps.map(\.otherNoteCount), [1, 1, 1])
  }

  func testEnhancedVoiceIsPreferredAndVariantsNeverStack() throws {
    let tracks = [
      EditorTrack(
        id: "voice_raw",
        label: "raw",
        role: "candidate",
        instrument: "voice",
        eventCount: 10
      ),
      EditorTrack(
        id: "voice_gap_candidate",
        label: "gap",
        role: "candidate",
        instrument: "voice",
        eventCount: 4
      ),
      EditorTrack(
        id: "voice_enhanced",
        label: "enhanced",
        role: "owner_approved_candidate",
        instrument: "voice",
        eventCount: 14
      ),
      EditorTrack(
        id: "voice_auto_enhanced",
        label: "automatic enhanced",
        role: "automatic_candidate",
        instrument: "voice",
        eventCount: 13
      ),
      EditorTrack(
        id: "piano",
        label: "piano",
        role: "candidate",
        instrument: "acoustic_piano",
        eventCount: 20
      ),
    ]

    XCTAssertEqual(
      MelodyTrackSelector.preferred(in: tracks)?.id,
      "voice_enhanced"
    )
    XCTAssertEqual(
      MelodyTrackSelector.resolveExclusiveVariant(
        from: Set(tracks.map(\.id)),
        tracks: tracks,
        selectedTrackID: "voice_enhanced"
      ),
      Set(["voice_enhanced", "piano"])
    )
    let automaticTracks = tracks.filter { $0.id != "voice_enhanced" }
    XCTAssertEqual(
      MelodyTrackSelector.preferred(in: automaticTracks)?.id,
      "voice_auto_enhanced"
    )
    XCTAssertEqual(
      MelodyTrackSelector.resolveExclusiveVariant(
        from: Set(automaticTracks.map(\.id)),
        tracks: automaticTracks,
        selectedTrackID: "voice_auto_enhanced"
      ),
      Set(["voice_auto_enhanced", "piano"])
    )
    XCTAssertEqual(
      MelodyTrackSelector.resolveExclusiveVariant(
        from: Set(tracks.map(\.id)),
        tracks: tracks,
        selectedTrackID: "voice_raw"
      ),
      Set(["voice_raw", "piano"])
    )
    XCTAssertEqual(
      MelodyTrackSelector.resolveExclusiveVariant(
        from: Set(["voice_raw", "voice_gap_candidate", "piano"]),
        tracks: tracks,
        selectedTrackID: "voice_enhanced"
      ),
      Set(["piano"])
    )
    XCTAssertEqual(
      MelodyTrackSelector.resolveExclusiveVariant(
        from: Set(["voice_raw"]),
        tracks: tracks,
        selectedTrackID: nil
      ),
      Set(["voice_raw"])
    )
  }

  func testLocalProjectLibraryFindsPreviousSongsWithoutOpeningThem() throws {
    let root = FileManager.default.temporaryDirectory
      .appendingPathComponent("AMT Studio library \(UUID().uuidString)")
    defer { try? FileManager.default.removeItem(at: root) }
    let project = root.appendingPathComponent("以前的歌")
    try FileManager.default.createDirectory(
      at: project,
      withIntermediateDirectories: true
    )
    try writeFixtureJSON(
      [
        "schema_version": 1,
        "project_id": "previous-song",
        "title": "以前的歌",
        "canonical_audio": [
          "path": "audio/canonical/mix.flac",
          "sha256": String(repeating: "a", count: 64),
        ],
      ],
      to: project.appendingPathComponent("manifest.json")
    )

    let items = try LocalProjectLibrary.scan(rootURL: root)

    XCTAssertEqual(items.count, 1)
    XCTAssertEqual(items[0].title, "以前的歌")
    XCTAssertEqual(items[0].stateLabel, "尚无结果")
  }

  func testOpenEditUndoRedoExportAndRestart() async throws {
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
    await model.waitForProjectLoadForTesting()
    XCTAssertEqual(model.bundleChoices.map(\.id), ["bundle-ui"])
    XCTAssertEqual(model.editor?.selectedTrack.id, "candidate-ui")
    model.chooseTrack("candidate-ui")
    await model.waitForSelectionLoadForTesting()
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

    XCTAssertEqual(model.selectedBundleID, "bundle-ui")
    let arrangementURL = fixture.root.appendingPathComponent(
      "exports/ui-full-arrangement.mid"
    )
    let arrangement = try XCTUnwrap(
      model.exportArrangementMIDI(to: arrangementURL)
    )
    XCTAssertEqual(arrangement.trackCount, 1)
    XCTAssertEqual(arrangement.noteCount, 1)
    XCTAssertEqual(
      String(
        data: try Data(contentsOf: arrangementURL).prefix(4),
        encoding: .ascii
      ),
      "MThd"
    )

    let reopened = AppModel(defaults: defaults, restoreRecent: true)
    XCTAssertNil(reopened.catalog)
    reopened.openInitialProjectIfNeeded()
    await reopened.waitForProjectLoadForTesting()
    XCTAssertEqual(reopened.editor?.selectedTrack.id, "candidate-ui")
    XCTAssertEqual(reopened.notes.first, moved)
  }

  func testMixerControlsAndSettingsPersistAcrossRestart() async throws {
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
    model.openInitialProjectIfNeeded()
    await model.waitForProjectLoadForTesting()

    XCTAssertEqual(model.midiPlaybackMode, .mix)
    XCTAssertEqual(model.audibleTrackCount, 1)
    XCTAssertEqual(model.trackChoices.first?.eventCount, 1)
    model.toggleMute("candidate-ui")
    XCTAssertEqual(model.audibleTrackCount, 0)
    model.enableAllTracks()
    model.setTrackVolume(0.25, trackID: "candidate-ui")
    model.setOriginalVolume(0.2)
    model.setMIDIMasterVolume(0.6)
    model.listenToSelectedTrack()

    let reopened = AppModel(defaults: defaults, restoreRecent: true)
    reopened.openInitialProjectIfNeeded()
    await reopened.waitForProjectLoadForTesting()
    XCTAssertEqual(reopened.midiPlaybackMode, .currentTrack)
    XCTAssertEqual(
      reopened.volume(for: "candidate-ui"),
      0.25,
      accuracy: 0.000_001
    )
    XCTAssertEqual(reopened.audibleTrackIDs, Set(["candidate-ui"]))
    XCTAssertEqual(reopened.transport.originalVolume, 0.2, accuracy: 0.000_001)
    XCTAssertEqual(reopened.midiMasterVolume, 0.6, accuracy: 0.000_001)
  }

  func testCompletedBetaProjectRestoresWithoutBlockingNewSubmission() async throws {
    let fixture = try AppFixtureProject()
    defer { fixture.remove() }
    try fixture.writePrivateBetaState(
      jobID: "fixture-job",
      slurmState: "COMPLETED"
    )
    let suiteName = "AMTStudioUITests.\(UUID().uuidString)"
    let defaults = try XCTUnwrap(UserDefaults(suiteName: suiteName))
    defer { defaults.removePersistentDomain(forName: suiteName) }
    defaults.set(
      fixture.root.path,
      forKey: "AMTStudio.activeBetaProjectPath"
    )

    let model = AppModel(defaults: defaults, restoreRecent: true)
    model.openInitialProjectIfNeeded()
    await model.waitForProjectLoadForTesting()

    XCTAssertEqual(model.catalog?.rootURL.path, fixture.root.path)
    XCTAssertEqual(model.betaJobID, "fixture-job")
    XCTAssertEqual(model.betaSlurmState, "COMPLETED")
    XCTAssertFalse(model.hasActiveBetaJob)
    XCTAssertNil(
      defaults.string(forKey: "AMTStudio.activeBetaProjectPath")
    )
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

  func writePrivateBetaState(
    jobID: String,
    slurmState: String
  ) throws {
    try FileManager.default.createDirectory(
      at: root.appendingPathComponent("app"),
      withIntermediateDirectories: true
    )
    try writeFixtureJSON(
      [
        "schema_version": 1,
        "job_id": jobID,
        "slurm_state": slurmState,
      ],
      to: root.appendingPathComponent("app/private_beta_job.json")
    )
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
  pcmWAV(samples: Array(repeating: 0, count: 4_410))
}

private func pcmWAV(
  samples: [Int16],
  sampleRate: UInt32 = 44_100
) -> Data {
  let frameCount = UInt32(samples.count)
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
  for sample in samples {
    appendLE(sample, to: &data)
  }
  return data
}

private func reviewNote(
  id: String,
  trackID: String = "candidate",
  onset: Double,
  offset: Double? = nil,
  confidence: Double? = nil
) -> EditorNote {
  EditorNote(
    id: id,
    trackID: trackID,
    sourceTrackID: "source",
    instrument: "voice",
    onsetSec: onset,
    offsetSec: offset ?? onset + 0.5,
    pitchMIDI: 60,
    velocity: 80,
    confidence: confidence,
    isMainMelodyCandidate: true,
    sourceRunID: "run",
    sourceModel: "model",
    sourceEventIDs: [],
    tags: [],
    extra: [:]
  )
}

private func appendLE<T: FixedWidthInteger>(_ value: T, to data: inout Data) {
  var value = value.littleEndian
  withUnsafeBytes(of: &value) { data.append(contentsOf: $0) }
}
