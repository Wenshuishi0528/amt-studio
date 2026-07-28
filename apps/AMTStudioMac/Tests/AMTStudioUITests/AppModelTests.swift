import AMTStudioCore
import Foundation
import XCTest

@testable import AMTStudioUI

@MainActor
final class AppModelTests: XCTestCase {
  func testHyakWallTimePolicyExtendsAndEscalatesLongSongs() {
    XCTAssertEqual(
      HyakWallTimePolicy.automaticHours(durationSeconds: 7 * 60),
      1
    )
    XCTAssertEqual(
      HyakWallTimePolicy.automaticHours(durationSeconds: 7 * 60 + 0.1),
      2
    )
    XCTAssertEqual(
      HyakWallTimePolicy.automaticHours(durationSeconds: 14 * 60),
      2
    )
    XCTAssertEqual(
      HyakWallTimePolicy.automaticHours(durationSeconds: 14 * 60 + 0.1),
      3
    )
    XCTAssertEqual(
      HyakWallTimePolicy.automaticHours(durationSeconds: 21 * 60),
      3
    )
    XCTAssertNil(
      HyakWallTimePolicy.automaticHours(durationSeconds: 21 * 60 + 0.1)
    )
    XCTAssertEqual(
      HyakWallTimePolicy.automaticHours(
        durationSeconds: 60,
        configuredMinimum: 6
      ),
      6
    )
    XCTAssertEqual(
      HyakWallTimePolicy.suggestedManualHours(
        durationSeconds: 30 * 60,
        configuredMinimum: 1
      ),
      5
    )
  }

  func testPrivateBackendRestoresPackageManagerToolsForGUIProcess() {
    let environment = PrivateBetaBackend.processEnvironment(
      base: [
        "PATH": "/usr/bin:/bin:/usr/local/bin",
        "LANG": "zh_CN.UTF-8",
      ],
      uvURL: URL(fileURLWithPath: "/custom/tools/uv")
    )

    XCTAssertEqual(
      environment["PATH"],
      [
        "/custom/tools",
        "/opt/homebrew/bin",
        "/usr/local/bin",
        "/usr/bin",
        "/bin",
        "/usr/sbin",
        "/sbin",
      ].joined(separator: ":")
    )
    XCTAssertEqual(environment["LANG"], "zh_CN.UTF-8")
  }

  func testSustainRepairSummaryExplainsTheActualReplacement() {
    let summary = TrailingCleanupSummary(
      kind: .sustain,
      groupCount: 162,
      fragmentCount: 3_076
    )
    XCTAssertEqual(summary.badgeLabel, "连续音碎片 3076 → 162")
  }

  func testPrivateBackendResponseCarriesFailureAndEmptyRecoveryDetails()
    throws
  {
    let data = Data(
      """
      {
        "ok": true,
        "status": "failed",
        "failure_reason": "bounded worker failure",
        "recovered_candidate_note_count": 0
      }
      """.utf8
    )
    let response = try JSONDecoder().decode(
      PrivateBetaResponse.self,
      from: data
    )
    XCTAssertEqual(response.failureReason, "bounded worker failure")
    XCTAssertEqual(response.recoveredCandidateNoteCount, 0)
  }

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
    if let duration =
      model.snapshot?.manifest.canonicalAudio.metadata?.durationSec
    {
      XCTAssertEqual(model.canonicalTimelineDuration, duration)
      XCTAssertTrue(model.melodyGaps.allSatisfy { $0.endSec <= duration })
    }
    if let expectedTrack = ProcessInfo.processInfo.environment[
      "AMT_STUDIO_REAL_TRACK"
    ] {
      XCTAssertEqual(model.editor?.selectedTrack.id, expectedTrack)
    }
    if let expectedBundle = ProcessInfo.processInfo.environment[
      "AMT_STUDIO_REAL_EXPECT_BUNDLE"
    ] {
      XCTAssertEqual(model.selectedBundleID, expectedBundle)
    }
    if let expectedNoteText = ProcessInfo.processInfo.environment[
      "AMT_STUDIO_REAL_EXPECT_NOTE_COUNT"
    ], let expectedNoteCount = Int(expectedNoteText) {
      XCTAssertEqual(model.editor?.notes.count, expectedNoteCount)
    }
    if let cleanupTrack = ProcessInfo.processInfo.environment[
      "AMT_STUDIO_REAL_CLEANUP_TRACK"
    ] {
      let summary = try XCTUnwrap(
        model.trailingCleanupSummaries[cleanupTrack]
      )
      if let groupText = ProcessInfo.processInfo.environment[
        "AMT_STUDIO_REAL_CLEANUP_GROUPS"
      ], let expectedGroups = Int(groupText) {
        XCTAssertEqual(summary.groupCount, expectedGroups)
      }
      if let fragmentText = ProcessInfo.processInfo.environment[
        "AMT_STUDIO_REAL_CLEANUP_FRAGMENTS"
      ], let expectedFragments = Int(fragmentText) {
        XCTAssertEqual(summary.fragmentCount, expectedFragments)
      }
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
    XCTAssertEqual(model.appearanceMode, .precision)
    XCTAssertTrue(RecognitionMode.gameVocal.detail.contains("GAME large"))
  }

  func testAppearanceModePersistsWithoutChangingProjectState() throws {
    let suiteName = "AMTStudioUITests.\(UUID().uuidString)"
    let defaults = try XCTUnwrap(UserDefaults(suiteName: suiteName))
    defer { defaults.removePersistentDomain(forName: suiteName) }
    let model = AppModel(defaults: defaults, restoreRecent: false)

    model.setAppearanceMode(.spectrum)

    XCTAssertEqual(model.appearanceMode, .spectrum)
    XCTAssertNil(model.catalog)
    XCTAssertNil(model.betaJobID)
    let reopened = AppModel(defaults: defaults, restoreRecent: false)
    XCTAssertEqual(reopened.appearanceMode, .spectrum)
    XCTAssertNil(reopened.catalog)
    XCTAssertNil(reopened.betaJobID)
  }

  func testComputeModePersistsAndPlansLocalWithoutStartingWork() throws {
    let suiteName = "AMTStudioUITests.\(UUID().uuidString)"
    let defaults = try XCTUnwrap(UserDefaults(suiteName: suiteName))
    defer { defaults.removePersistentDomain(forName: suiteName) }
    let model = AppModel(defaults: defaults, restoreRecent: false)
    XCTAssertEqual(model.computeMode, .hyak)
    XCTAssertEqual(model.recognitionMode, .multitrack)
    XCTAssertEqual(model.hyakTimeLimitHours, 1)

    model.setComputeMode(.localGPU)
    model.setHyakTimeLimitHours(6)

    XCTAssertEqual(model.computeMode, .localGPU)
    XCTAssertEqual(model.hyakTimeLimitHours, 6)
    XCTAssertNil(model.betaJobID)
    XCTAssertNil(model.betaProjectURL)
    let reopened = AppModel(defaults: defaults, restoreRecent: false)
    XCTAssertEqual(reopened.computeMode, .localGPU)
    XCTAssertEqual(reopened.hyakTimeLimitHours, 6)
    XCTAssertNil(reopened.betaJobID)

    let arguments = PrivateBetaBackend.startArguments(
      audioURL: URL(fileURLWithPath: "/tmp/song.mp3"),
      computeMode: .localGPU,
      hyakTimeLimitHours: 6,
      recognitionMode: .multitrack,
      repositoryRoot: URL(fileURLWithPath: "/tmp/repository"),
      localProjectsRoot: URL(fileURLWithPath: "/tmp/projects")
    )
    XCTAssertTrue(arguments.contains("start-local"))
    XCTAssertTrue(arguments.contains("mps"))
    XCTAssertFalse(arguments.contains("start"))
    XCTAssertFalse(arguments.contains("--time-limit-hours"))

    model.setRecognitionMode(.gameVocal)
    XCTAssertEqual(model.recognitionMode, .gameVocal)
    XCTAssertEqual(model.computeMode, .hyak)
    model.setComputeMode(.localCPU)
    XCTAssertEqual(model.computeMode, .hyak)
    let reopenedWithGame = AppModel(
      defaults: defaults,
      restoreRecent: false
    )
    XCTAssertEqual(reopenedWithGame.recognitionMode, .gameVocal)
    XCTAssertEqual(reopenedWithGame.computeMode, .hyak)

    let gameArguments = PrivateBetaBackend.startArguments(
      audioURL: URL(fileURLWithPath: "/tmp/song.mp3"),
      computeMode: .hyak,
      hyakTimeLimitHours: 6,
      recognitionMode: .gameVocal,
      repositoryRoot: URL(fileURLWithPath: "/tmp/repository"),
      localProjectsRoot: URL(fileURLWithPath: "/tmp/projects")
    )
    XCTAssertTrue(gameArguments.contains("--recognition-mode"))
    XCTAssertTrue(gameArguments.contains("game_vocal"))
    XCTAssertTrue(gameArguments.contains("6"))

    let existingGameArguments = PrivateBetaBackend.gameVocalArguments(
      projectURL: URL(fileURLWithPath: "/tmp/projects/song"),
      hyakTimeLimitHours: 6,
      repositoryRoot: URL(fileURLWithPath: "/tmp/repository")
    )
    XCTAssertTrue(existingGameArguments.contains("start-game-vocal"))
    XCTAssertTrue(existingGameArguments.contains("/tmp/projects/song"))

    let recoveryArguments = PrivateBetaBackend.gapRecoveryArguments(
      projectURL: URL(fileURLWithPath: "/tmp/projects/song"),
      sourceBundleID: "source-bundle",
      sourceTrackID: "clean_electric_guitar",
      gaps: [
        MelodyGap(
          startSec: 10,
          endSec: 30,
          otherTrackCount: 2,
          otherNoteCount: 20
        ),
        MelodyGap(
          startSec: 80,
          endSec: 100,
          otherTrackCount: 3,
          otherNoteCount: 30
        ),
      ],
      computeMode: .hyak,
      hyakTimeLimitHours: 6,
      repositoryRoot: URL(fileURLWithPath: "/tmp/repository")
    )
    XCTAssertTrue(recoveryArguments.contains("start-gap-recovery"))
    XCTAssertTrue(recoveryArguments.contains("clean_electric_guitar"))
    XCTAssertEqual(
      recoveryArguments.filter { $0 == "--gap" }.count,
      2
    )
    XCTAssertTrue(recoveryArguments.contains("10.000000:30.000000"))
    XCTAssertFalse(recoveryArguments.contains("mps"))
    XCTAssertTrue(recoveryArguments.contains("--time-limit-hours"))
    XCTAssertTrue(recoveryArguments.contains("6"))
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

  func testAllTrackOverviewFitsTimeAndPitchIntoEachLane() {
    XCTAssertEqual(
      MultiTrackRollLayout.normalizedTime(-2, duration: 10),
      0,
      accuracy: 0.000_001
    )
    XCTAssertEqual(
      MultiTrackRollLayout.normalizedTime(5, duration: 10),
      0.5,
      accuracy: 0.000_001
    )
    XCTAssertEqual(
      MultiTrackRollLayout.normalizedTime(12, duration: 10),
      1,
      accuracy: 0.000_001
    )
    XCTAssertEqual(
      MultiTrackRollLayout.normalizedPitch(
        60,
        minimumPitch: 48,
        maximumPitch: 72
      ),
      0.5,
      accuracy: 0.000_001
    )

    let frame = MultiTrackRollLayout.noteFrame(
      onset: 2,
      offset: 3,
      pitch: 60,
      duration: 10,
      size: CGSize(width: 1_000, height: 66),
      minimumPitch: 48,
      maximumPitch: 72
    )
    XCTAssertEqual(frame.origin.x, 200, accuracy: 0.000_001)
    XCTAssertEqual(frame.origin.y, 31, accuracy: 0.000_001)
    XCTAssertEqual(frame.width, 100, accuracy: 0.000_001)
    XCTAssertEqual(frame.height, 4, accuracy: 0.000_001)
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

  func testGapRecoveryComparisonStagesAreIndependentlyAudible() {
    let stages = [
      EditorTrack(
        id: "gap_raw_candidate",
        label: "raw",
        role: "diagnostic_candidate",
        instrument: "voice",
        eventCount: 864
      ),
      EditorTrack(
        id: "gap_accompaniment_filtered",
        label: "filtered",
        role: "diagnostic_candidate",
        instrument: "voice",
        eventCount: 234
      ),
      EditorTrack(
        id: "gap_monophonic_candidate",
        label: "monophonic",
        role: "diagnostic_candidate",
        instrument: "voice",
        eventCount: 161
      ),
    ]

    XCTAssertEqual(
      MelodyTrackSelector.preferred(in: stages)?.id,
      "gap_monophonic_candidate"
    )
    XCTAssertEqual(
      MelodyTrackSelector.resolveExclusiveVariant(
        from: Set(stages.map(\.id)),
        tracks: stages,
        selectedTrackID: "gap_raw_candidate"
      ),
      Set(["gap_raw_candidate"])
    )
    XCTAssertEqual(
      MelodyTrackSelector.resolveExclusiveVariant(
        from: Set(stages.map(\.id)),
        tracks: stages,
        selectedTrackID: "gap_accompaniment_filtered"
      ),
      Set(["gap_accompaniment_filtered"])
    )
    XCTAssertEqual(
      MelodyTrackSelector.displayLabel(for: stages[2]),
      "补漏 3/3 · 单旋律约束后"
    )
  }

  func testRawRecoveryHasNoCountCapButLegacyRejectionStaysDiagnostic() {
    let small = MainMelodyDefaultPolicy.assess(
      trackCounts: [
        "voice_raw": 322,
        "voice_auto_enhanced": 338,
      ]
    )
    let uncapped = MainMelodyDefaultPolicy.assess(
      trackCounts: [
        "voice_raw": 322,
        "voice_auto_enhanced": 1_179,
      ]
    )
    let ownerSelectedRaw = MainMelodyDefaultPolicy.assess(
      trackCounts: [
        "voice_raw": 322,
        "voice_auto_enhanced": 1_186,
      ],
      automaticAdmissionDecision: "accepted_owner_selected_raw_generation"
    )
    let ownerApproved = MainMelodyDefaultPolicy.assess(
      trackCounts: [
        "voice_raw": 322,
        "voice_auto_enhanced": 1_179,
        "voice_enhanced": 400,
      ]
    )
    let cumulativeAccepted = MainMelodyDefaultPolicy.assess(
      trackCounts: [
        "voice_raw": 322,
        "voice_auto_enhanced": 358,
      ],
      automaticAdmissionDecision: "accepted_conservative_voice_growth"
    )
    let explicitRejected = MainMelodyDefaultPolicy.assess(
      trackCounts: ["voice": 338, "target_gap_candidate": 841],
      automaticAdmissionDecision: "rejected_excessive_voice_growth"
    )

    XCTAssertTrue(small.isEligible)
    XCTAssertTrue(uncapped.isEligible)
    XCTAssertNil(uncapped.maximumAddedNoteCount)
    XCTAssertTrue(ownerSelectedRaw.isEligible)
    XCTAssertTrue(ownerApproved.isEligible)
    XCTAssertTrue(cumulativeAccepted.isEligible)
    XCTAssertFalse(explicitRejected.isEligible)
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
    let activeProject = root.appendingPathComponent("正在识别的歌")
    try FileManager.default.createDirectory(
      at: activeProject.appendingPathComponent("app"),
      withIntermediateDirectories: true
    )
    try writeFixtureJSON(
      [
        "schema_version": 1,
        "project_id": "active-song",
        "title": "正在识别的歌",
        "canonical_audio": [
          "path": "audio/canonical/mix.flac",
          "sha256": String(repeating: "b", count: 64),
        ],
      ],
      to: activeProject.appendingPathComponent("manifest.json")
    )
    try writeFixtureJSON(
      [
        "job_id": "fixture-job",
        "slurm_state": "RUNNING",
        "pipeline_stage": "full_transcription",
      ],
      to: activeProject.appendingPathComponent("app/private_beta_job.json")
    )

    let items = try LocalProjectLibrary.scan(rootURL: root)

    XCTAssertEqual(items.count, 2)
    XCTAssertEqual(items[0].title, "正在识别的歌")
    XCTAssertTrue(items[0].hasActiveJob)
    XCTAssertFalse(items[0].canMoveToTrash)
    XCTAssertEqual(items[1].title, "以前的歌")
    XCTAssertEqual(items[1].stateLabel, "尚无结果")
    XCTAssertTrue(items[1].canMoveToTrash)
    XCTAssertEqual(
      try LocalProjectLibrary.validatedTrashTarget(
        items[1],
        rootURL: root
      ).path,
      project.path
    )

    let outside = LocalProjectItem(
      projectID: items[1].projectID,
      title: items[1].title,
      url: root.deletingLastPathComponent(),
      modifiedAt: .distantPast,
      hasResults: false,
      jobState: nil
    )
    XCTAssertThrowsError(
      try LocalProjectLibrary.validatedTrashTarget(outside, rootURL: root)
    )
    XCTAssertThrowsError(
      try LocalProjectLibrary.validatedTrashTarget(items[0], rootURL: root)
    )
    let staleCompletedView = LocalProjectItem(
      projectID: items[0].projectID,
      title: items[0].title,
      url: items[0].url,
      modifiedAt: items[0].modifiedAt,
      hasResults: false,
      jobState: "COMPLETED"
    )
    XCTAssertTrue(staleCompletedView.canMoveToTrash)
    XCTAssertThrowsError(
      try LocalProjectLibrary.validatedTrashTarget(
        staleCompletedView,
        rootURL: root
      )
    )
    try writeFixtureJSON(
      [
        "job_id": "fixture-job",
        "slurm_state": "SUSPENDED",
        "pipeline_stage": "queued",
      ],
      to: activeProject.appendingPathComponent("app/private_beta_job.json")
    )
    XCTAssertThrowsError(
      try LocalProjectLibrary.validatedTrashTarget(
        staleCompletedView,
        rootURL: root
      )
    )
    try Data("not-json".utf8).write(
      to: activeProject.appendingPathComponent("app/private_beta_job.json")
    )
    XCTAssertThrowsError(
      try LocalProjectLibrary.validatedTrashTarget(
        staleCompletedView,
        rootURL: root
      )
    )
    try writeFixtureJSON(
      [
        "job_id": "fixture-job",
        "slurm_state": "TIMEOUT",
        "pipeline_stage": "failed",
      ],
      to: activeProject.appendingPathComponent("app/private_beta_job.json")
    )
    XCTAssertEqual(
      try LocalProjectLibrary.validatedTrashTarget(
        staleCompletedView,
        rootURL: root
      ).path,
      activeProject.path
    )
    let failedWithResults = LocalProjectItem(
      projectID: "failed-rerun",
      title: "失败重算",
      url: project,
      modifiedAt: .distantPast,
      hasResults: true,
      jobState: "TIMEOUT"
    )
    XCTAssertTrue(failedWithResults.hasFailedJob)
    XCTAssertFalse(failedWithResults.hasActiveJob)
    XCTAssertEqual(failedWithResults.stateLabel, "任务失败")
    let suspendedItem = LocalProjectItem(
      projectID: "suspended",
      title: "暂停任务",
      url: project,
      modifiedAt: .distantPast,
      hasResults: true,
      jobState: "SUSPENDED"
    )
    XCTAssertTrue(suspendedItem.hasActiveJob)
    XCTAssertFalse(suspendedItem.canMoveToTrash)
    XCTAssertEqual(suspendedItem.stateLabel, "任务状态待确认")
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
    XCTAssertEqual(model.canonicalTimelineDuration, 20)
    model.chooseTrack("candidate-ui")
    await model.waitForSelectionLoadForTesting()
    XCTAssertEqual(model.editor?.selectedTrack.id, "candidate-ui")
    XCTAssertEqual(model.melodyGaps.count, 1)
    XCTAssertEqual(model.selectedMelodyGaps.count, 1)
    let selectedGap = try XCTUnwrap(model.melodyGaps.first)
    XCTAssertEqual(selectedGap.endSec, 20)
    model.clearGapSelection()
    XCTAssertTrue(model.selectedMelodyGaps.isEmpty)
    model.setGapSelected(selectedGap, selected: true)
    XCTAssertEqual(model.selectedMelodyGaps, [selectedGap])
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

    model.transport.seek(to: 0.05)
    model.createNoteAtPlayhead()
    XCTAssertEqual(model.notes.count, 2)
    let created = try XCTUnwrap(
      model.notes.first(where: { $0.tags.contains("app-created") })
    )
    XCTAssertEqual(created.onsetSec, 0.05, accuracy: 0.001)
    XCTAssertEqual(created.offsetSec - created.onsetSec, 0.5, accuracy: 0.001)
    XCTAssertEqual(model.selectedNoteID, created.id)
    model.undo()
    XCTAssertEqual(model.notes, [moved])

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

  func testDiagnosticBundlesAreHiddenAndTrackCopyOpensCustomVersion() async throws {
    let fixture = try AppFixtureProject()
    defer { fixture.remove() }
    try fixture.duplicateBundle(as: "bundle-ui-2")
    try fixture.duplicateBundle(
      as: "bundle-diagnostic",
      claims: [
        "automatic_candidate_admission":
          "rejected_excessive_voice_growth"
      ]
    )
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

    XCTAssertEqual(
      Set(model.bundleChoices.map(\.id)),
      Set(["bundle-ui", "bundle-ui-2"])
    )
    XCTAssertFalse(
      model.bundleChoices.contains { $0.id == "bundle-diagnostic" }
    )
    model.chooseBundle("bundle-ui")
    await model.waitForSelectionLoadForTesting()
    model.copyTrack(
      from: "bundle-ui-2",
      trackID: "candidate-ui"
    )
    await model.waitForTrackManagementForTesting()

    let customID = try XCTUnwrap(model.selectedBundleID)
    XCTAssertTrue(customID.hasPrefix("custom-"))
    XCTAssertEqual(model.snapshot?.tracks.count, 2)
    XCTAssertEqual(model.snapshot?.notes.count, 2)
    XCTAssertEqual(model.editor?.selectedTrack.id, "candidate-ui-copy")
    XCTAssertEqual(model.bundleChoices.count, 3)
    XCTAssertFalse(model.isManagingTracks)
    let untouchedSource = try ProjectLoader.open(
      try ProjectLoader.inspect(fixture.root),
      bundleID: "bundle-ui"
    )
    XCTAssertEqual(untouchedSource.tracks.count, 1)
    XCTAssertEqual(untouchedSource.notes.count, 1)
  }

  func testLastVisibleProductTrackCannotBeDeleted() async throws {
    let fixture = try AppFixtureProject()
    defer { fixture.remove() }
    let model = AppModel(
      initialProjectURL: fixture.root,
      restoreRecent: false,
      persistRecentProject: false
    )
    model.openInitialProjectIfNeeded()
    await model.waitForProjectLoadForTesting()

    XCTAssertEqual(model.visibleTrackChoices.map(\.id), ["candidate-ui"])
    XCTAssertFalse(model.canDeleteTrack("candidate-ui"))
    model.deleteTrack("candidate-ui")
    XCTAssertEqual(model.statusMessage, "当前版本至少需要保留一条可见产品音轨")
    XCTAssertFalse(model.isManagingTracks)
  }

  func testTrackCopyCannotReopenAProjectTheUserLeft() async throws {
    let first = try AppFixtureProject()
    let second = try AppFixtureProject()
    defer {
      first.remove()
      second.remove()
    }
    try first.duplicateBundle(as: "bundle-ui-2")
    let model = AppModel(
      initialProjectURL: first.root,
      restoreRecent: false,
      persistRecentProject: false
    )
    model.openInitialProjectIfNeeded()
    await model.waitForProjectLoadForTesting()

    model.copyTrack(
      from: "bundle-ui-2",
      trackID: "candidate-ui"
    )
    model.openProject(second.root)
    await model.waitForTrackManagementForTesting()
    await model.waitForProjectLoadForTesting()

    XCTAssertEqual(
      model.catalog?.rootURL.standardizedFileURL.path,
      second.root.standardizedFileURL.path
    )
    XCTAssertFalse(model.isManagingTracks)
  }

  func testCrossProjectTrackCopyOpensDerivedTargetVersion() async throws {
    let source = try AppFixtureProject(
      projectID: "source-ui-project",
      title: "来源歌曲"
    )
    let target = try AppFixtureProject(
      projectID: "target-ui-project",
      title: "目标歌曲"
    )
    defer {
      source.remove()
      target.remove()
    }
    let model = AppModel(
      initialProjectURL: source.root,
      restoreRecent: false,
      persistRecentProject: false
    )
    model.openInitialProjectIfNeeded()
    await model.waitForProjectLoadForTesting()
    let destination = LocalProjectItem(
      projectID: "target-ui-project",
      title: "目标歌曲",
      url: target.root,
      modifiedAt: Date(),
      hasResults: true,
      jobState: "COMPLETED"
    )

    model.copySelectedTrack(
      to: destination,
      targetBundleID: "bundle-ui"
    )
    await model.waitForTrackManagementForTesting()
    await model.waitForProjectLoadForTesting()
    await model.waitForSelectionLoadForTesting()

    XCTAssertEqual(
      model.catalog?.manifest.projectID,
      "target-ui-project"
    )
    XCTAssertTrue(model.selectedBundleID?.hasPrefix("custom-") == true)
    XCTAssertEqual(model.snapshot?.tracks.count, 2)
    XCTAssertEqual(
      model.editor?.selectedTrack.id,
      "candidate-ui-import"
    )
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
      slurmState: "COMPLETED",
      gpuType: "a100",
      partition: "ckpt",
      preemptible: true,
      selectionReason: "fixture auto selection",
      estimatedWaitSeconds: 0
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
    XCTAssertEqual(model.betaGPUType, "a100")
    XCTAssertEqual(model.betaPartition, "ckpt")
    XCTAssertTrue(model.betaGPUPreemptible)
    XCTAssertEqual(
      model.betaGPUSelectionReason,
      "fixture auto selection"
    )
    XCTAssertEqual(model.betaGPUEstimatedWaitSeconds, 0)
    XCTAssertFalse(model.hasActiveBetaJob)
    XCTAssertNil(
      defaults.string(forKey: "AMTStudio.activeBetaProjectPath")
    )
  }

  func testMultipleSongsQueueWhileActiveAndFreezeTheirSettings() async throws {
    let fixture = try AppFixtureProject()
    defer { fixture.remove() }
    try fixture.writePrivateBetaState(
      jobID: "active-job",
      slurmState: "RUNNING",
      pipelineStage: "full_transcription",
      backend: "hyak",
      taskKind: "full_transcription"
    )
    let suiteName = "AMTStudioUITests.\(UUID().uuidString)"
    let defaults = try XCTUnwrap(UserDefaults(suiteName: suiteName))
    defer { defaults.removePersistentDomain(forName: suiteName) }
    let model = AppModel(
      defaults: defaults,
      initialProjectURL: fixture.root,
      restoreRecent: false,
      persistRecentProject: false
    )
    model.openInitialProjectIfNeeded()
    await model.waitForProjectLoadForTesting()
    XCTAssertTrue(model.hasActiveBetaJob)

    model.setComputeMode(.localCPU)
    model.setHyakTimeLimitHours(7)
    model.enqueueSongs([
      URL(fileURLWithPath: "/tmp/第一首歌.mp3"),
      URL(fileURLWithPath: "/tmp/第二首歌.wav"),
    ])

    XCTAssertEqual(model.songQueue.map(\.title), ["第一首歌", "第二首歌"])
    XCTAssertEqual(model.songQueue.map(\.state), [.waiting, .waiting])
    XCTAssertTrue(model.songQueue.allSatisfy { $0.computeMode == .localCPU })
    XCTAssertTrue(
      model.songQueue.allSatisfy { $0.recognitionMode == .multitrack }
    )
    XCTAssertTrue(
      model.songQueue.allSatisfy { $0.hyakTimeLimitHours == 7 }
    )

    model.setRecognitionMode(.gameVocal)
    model.enqueueSongs([
      URL(fileURLWithPath: "/tmp/第三首歌.flac")
    ])
    XCTAssertEqual(model.songQueue.last?.recognitionMode, .gameVocal)
    XCTAssertEqual(model.songQueue.last?.computeMode, .hyak)
    XCTAssertEqual(model.songQueue.first?.computeMode, .localCPU)

    let reopened = AppModel(defaults: defaults, restoreRecent: false)
    XCTAssertEqual(reopened.songQueue, model.songQueue)
    XCTAssertEqual(reopened.songQueue.count, 3)
  }

  func testHyakQueueCanSubmitWhileAnotherTaskIsActiveButLocalWaits() {
    let hyakItem = SongQueueItem(
      id: UUID(),
      title: "Hyak",
      audioURL: URL(fileURLWithPath: "/tmp/hyak.mp3"),
      computeMode: .hyak,
      recognitionMode: .multitrack,
      hyakTimeLimitHours: 1,
      state: .waiting,
      failureMessage: nil,
      bookmarkData: nil
    )
    let localItem = SongQueueItem(
      id: UUID(),
      title: "Local",
      audioURL: URL(fileURLWithPath: "/tmp/local.mp3"),
      computeMode: .localGPU,
      recognitionMode: .multitrack,
      hyakTimeLimitHours: 1,
      state: .waiting,
      failureMessage: nil,
      bookmarkData: nil
    )

    XCTAssertTrue(
      SongQueuePolicy.canSubmit(
        hyakItem,
        hasActiveProjectTask: true
      )
    )
    XCTAssertFalse(
      SongQueuePolicy.canSubmit(
        localItem,
        hasActiveProjectTask: true
      )
    )
    XCTAssertTrue(
      SongQueuePolicy.canSubmit(
        localItem,
        hasActiveProjectTask: false
      )
    )
  }

  func testMultipleActiveProjectPathsRestoreAsOneBackgroundFleet() throws {
    let first = try AppFixtureProject(projectID: "active-one")
    let second = try AppFixtureProject(projectID: "active-two")
    defer {
      first.remove()
      second.remove()
    }
    let suiteName = "AMTStudioUITests.\(UUID().uuidString)"
    let defaults = try XCTUnwrap(UserDefaults(suiteName: suiteName))
    defer { defaults.removePersistentDomain(forName: suiteName) }
    defaults.set(
      [first.root.path, second.root.path],
      forKey: "AMTStudio.activeBetaProjectPaths.v1"
    )

    let model = AppModel(defaults: defaults, restoreRecent: false)

    XCTAssertEqual(model.activeProjectTaskCount, 2)
    XCTAssertNil(model.betaProjectURL)

    model.forgetActiveProjectForTesting(first.root)

    XCTAssertEqual(model.activeProjectTaskCount, 1)
    XCTAssertEqual(
      Set(
        defaults.stringArray(
          forKey: "AMTStudio.activeBetaProjectPaths.v1"
        ) ?? []
      ),
      Set([
        second.root.standardizedFileURL.resolvingSymlinksInPath().path
      ])
    )
  }

  func testInterruptedSubmissionRequiresManualRetryToAvoidDuplicateJob() throws {
    let suiteName = "AMTStudioUITests.\(UUID().uuidString)"
    let defaults = try XCTUnwrap(UserDefaults(suiteName: suiteName))
    defer { defaults.removePersistentDomain(forName: suiteName) }
    let item = SongQueueItem(
      id: UUID(),
      title: "未确认提交",
      audioURL: URL(fileURLWithPath: "/tmp/interrupted.mp3"),
      computeMode: .hyak,
      recognitionMode: .multitrack,
      hyakTimeLimitHours: 1,
      state: .submitting,
      failureMessage: nil,
      bookmarkData: nil
    )
    defaults.set(
      try JSONEncoder().encode([item]),
      forKey: "AMTStudio.songQueue.v1"
    )

    let model = AppModel(defaults: defaults, restoreRecent: false)

    XCTAssertEqual(model.songQueue.count, 1)
    XCTAssertEqual(model.songQueue[0].state, .failed)
    XCTAssertTrue(
      model.songQueue[0].failureMessage?.contains("避免重复任务") == true
    )
    XCTAssertNil(model.betaJobID)
    XCTAssertNil(model.betaProjectURL)
  }

  func testActiveGameProjectOpensProgressAndCanReturnToExistingResult() async throws {
    let fixture = try AppFixtureProject()
    defer { fixture.remove() }
    try fixture.writePrivateBetaState(
      jobID: "game-job",
      slurmState: "RUNNING",
      pipelineStage: "game_vocal_transcription",
      backend: "hyak",
      taskKind: "game_vocal_transcription"
    )
    let defaults = try XCTUnwrap(
      UserDefaults(suiteName: "AMTStudioUITests.\(UUID().uuidString)")
    )
    let model = AppModel(
      defaults: defaults,
      initialProjectURL: fixture.root,
      restoreRecent: false,
      persistRecentProject: false
    )

    model.openInitialProjectIfNeeded()
    await model.waitForProjectLoadForTesting()

    XCTAssertNotNil(model.editor)
    XCTAssertTrue(model.hasActiveBetaJob)
    XCTAssertTrue(model.isShowingJobProgress)
    XCTAssertTrue(model.shouldShowJobProgress)

    model.showCurrentResult()
    XCTAssertFalse(model.isShowingJobProgress)
    XCTAssertFalse(model.shouldShowJobProgress)

    model.showJobProgress()
    XCTAssertTrue(model.shouldShowJobProgress)
  }
}

private final class AppFixtureProject {
  let root: URL
  let eventsURL: URL

  init(
    projectID: String = "ui-project",
    title: String = "UI fixture"
  ) throws {
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
        "project_id": projectID,
        "title": title,
        "canonical_audio": [
          "path": "audio/canonical/mix.wav",
          "sha256": audioHash,
          "metadata": [
            "duration_sec": 20.0
          ],
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
        "project_id": projectID,
        "timeline_basis": "original_canonical_mix_seconds",
        "canonical_audio": [
          "path": "audio/canonical/mix.wav",
          "sha256": audioHash,
          "metadata": [
            "duration_sec": 20.0
          ],
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
        "project_id": projectID,
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

  func duplicateBundle(
    as bundleID: String,
    claims: [String: Any]? = nil
  ) throws {
    let source = root.appendingPathComponent("exports/bundle-ui")
    let destination = root.appendingPathComponent("exports/\(bundleID)")
    try FileManager.default.copyItem(at: source, to: destination)
    guard let claims else { return }
    let manifestURL = destination.appendingPathComponent(
      "bundle_manifest.json"
    )
    guard
      var manifest = try JSONSerialization.jsonObject(
        with: Data(contentsOf: manifestURL)
      ) as? [String: Any]
    else {
      throw CocoaError(.fileReadCorruptFile)
    }
    manifest["claims"] = claims
    try writeFixtureJSON(manifest, to: manifestURL)
  }

  func remove() {
    try? FileManager.default.removeItem(at: root)
  }

  func writePrivateBetaState(
    jobID: String,
    slurmState: String,
    pipelineStage: String? = nil,
    backend: String? = nil,
    taskKind: String? = nil,
    gpuType: String? = nil,
    partition: String? = nil,
    preemptible: Bool? = nil,
    selectionReason: String? = nil,
    estimatedWaitSeconds: Int? = nil
  ) throws {
    try FileManager.default.createDirectory(
      at: root.appendingPathComponent("app"),
      withIntermediateDirectories: true
    )
    var state: [String: Any] = [
      "schema_version": 1,
      "job_id": jobID,
      "slurm_state": slurmState,
    ]
    state["slurm_gpu_type"] = gpuType
    state["pipeline_stage"] = pipelineStage
    state["backend"] = backend
    state["task_kind"] = taskKind
    state["slurm_partition"] = partition
    state["gpu_preemptible"] = preemptible
    state["gpu_selection_reason"] = selectionReason
    state["gpu_estimated_wait_seconds"] = estimatedWaitSeconds
    try writeFixtureJSON(
      state,
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
