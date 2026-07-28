import Foundation
import XCTest

@testable import AMTStudioCore

final class ProjectAndEditingTests: XCTestCase {
  func testCanonicalTimelineClipsAndDropsModelSpill() {
    let notes = [
      testNote(id: "inside", onset: 8, offset: 9, pitch: 60),
      testNote(id: "crossing", onset: 9.5, offset: 11, pitch: 62),
      testNote(id: "outside", onset: 10, offset: 11, pitch: 64),
    ]

    let clipped = CanonicalTimeline.clippedNotes(notes, duration: 10)

    XCTAssertEqual(clipped.map(\.id), ["inside", "crossing"])
    XCTAssertEqual(clipped.map(\.offsetSec), [9, 10])
    XCTAssertEqual(notes[1].offsetSec, 11)
  }

  func testTrailingSustainAnalyzerIsConservative() {
    let sustainedChord = [58.0, 62.0].flatMap { pitch in
      (0..<8).map { index in
        testNote(
          id: "\(Int(pitch))-\(index)",
          onset: 8 + Double(index) * 0.25,
          offset: 8 + Double(index + 1) * 0.25,
          pitch: pitch
        )
      }
    }
    let groups = SustainFragmentAnalyzer.trailingGroups(
      notes: sustainedChord,
      timelineEnd: 10
    )
    XCTAssertEqual(groups.count, 2)
    XCTAssertEqual(groups.map(\.fragmentCount), [8, 8])

    let separatedRepeats = (0..<8).map { index in
      testNote(
        id: "repeat-\(index)",
        onset: 8 + Double(index) * 0.25,
        offset: 8.15 + Double(index) * 0.25,
        pitch: 65
      )
    }
    XCTAssertTrue(
      SustainFragmentAnalyzer.trailingGroups(
        notes: separatedRepeats,
        timelineEnd: 10
      ).isEmpty
    )
    XCTAssertTrue(
      SustainFragmentAnalyzer.trailingGroups(
        notes: sustainedChord,
        timelineEnd: 20
      ).isEmpty
    )

    let modelSpill = [58.0, 62.0].flatMap { pitch in
      (0..<16).map { index in
        testNote(
          id: "spill-\(Int(pitch))-\(index)",
          onset: 8 + Double(index) * 0.25,
          offset: 8 + Double(index + 1) * 0.25,
          pitch: pitch
        )
      }
    }
    let clamped = SustainFragmentAnalyzer.trailingGroups(
      notes: modelSpill,
      timelineEnd: 10
    )
    XCTAssertEqual(clamped.count, 2)
    XCTAssertTrue(clamped.allSatisfy { $0.offsetSec == 10 })
  }

  func testWholeTrackSustainAnalyzerFindsInteriorFragmentation() {
    let interiorFragments = (0..<8).map { index in
      testNote(
        id: "interior-\(index)",
        onset: 2 + Double(index) * 0.25,
        offset: 2 + Double(index + 1) * 0.25,
        pitch: 60
      )
    }
    let separatedRepeats = (0..<8).map { index in
      testNote(
        id: "repeat-\(index)",
        onset: 8 + Double(index) * 0.25,
        offset: 8.15 + Double(index) * 0.25,
        pitch: 64
      )
    }

    let groups = SustainFragmentAnalyzer.fragmentedGroups(
      notes: interiorFragments + separatedRepeats,
      timelineEnd: 20
    )

    XCTAssertEqual(groups.count, 1)
    XCTAssertEqual(groups[0].noteIDs, interiorFragments.map(\.id))
    XCTAssertEqual(groups[0].onsetSec, 2)
    XCTAssertEqual(groups[0].offsetSec, 4)
  }

  func testWholeTrackSustainAnalyzerPlansEveryContinuousChordVoice() {
    let chordFragments = (0..<6).flatMap { pitchIndex in
      (0..<12).map { fragmentIndex in
        testNote(
          id: "chord-\(pitchIndex)-\(fragmentIndex)",
          onset: 4 + Double(fragmentIndex) * 0.25,
          offset: 4 + Double(fragmentIndex + 1) * 0.25,
          pitch: 48 + Double(pitchIndex) * 3
        )
      }
    }

    let groups = SustainFragmentAnalyzer.fragmentedGroups(
      notes: chordFragments,
      timelineEnd: 20
    )

    XCTAssertEqual(groups.count, 6)
    XCTAssertEqual(groups.reduce(0) { $0 + $1.fragmentCount }, 72)
    XCTAssertTrue(groups.allSatisfy { $0.onsetSec == 4 })
    XCTAssertTrue(groups.allSatisfy { $0.offsetSec == 7 })
  }

  func testPercussionRepeatAnalyzerRequiresDenseTailPattern() {
    let repeatedHits = (0..<8).map { index in
      testNote(
        id: "hit-\(index)",
        onset: 8 + Double(index) * 0.25,
        offset: 8.01 + Double(index) * 0.25,
        pitch: 42
      )
    }
    let groups = PercussionRepeatAnalyzer.trailingGroups(
      notes: repeatedHits,
      timelineEnd: 10
    )
    XCTAssertEqual(groups.count, 1)
    XCTAssertEqual(groups[0].fragmentCount, 8)

    let sparseHits = (0..<5).map { index in
      testNote(
        id: "sparse-\(index)",
        onset: 5 + Double(index),
        offset: 5.01 + Double(index),
        pitch: 42
      )
    }
    XCTAssertTrue(
      PercussionRepeatAnalyzer.trailingGroups(
        notes: sparseHits,
        timelineEnd: 10
      ).isEmpty
    )
  }

  func testSustainMergeIsOneUndoableEdit() throws {
    let fixture = try FixtureProject()
    defer { fixture.remove() }
    let snapshot = try ProjectLoader.open(projectURL: fixture.root)
    var editor = try EditorProject(
      snapshot: snapshot,
      bundleID: "bundle-a",
      selectedTrackID: "candidate-a"
    )
    let fragments = (0..<4).map { index in
      testNote(
        id: "fragment-\(index)",
        onset: 10 + Double(index) * 0.25,
        offset: 10 + Double(index + 1) * 0.25,
        pitch: 60
      )
    }
    for fragment in fragments {
      try editor.create(fragment)
    }
    let beforeMergeCount = editor.notes.count
    let merged = try editor.mergeSustainFragments([
      SustainFragmentGroup(
        pitchMIDI: 60,
        noteIDs: fragments.map(\.id),
        onsetSec: 10,
        offsetSec: 11
      )
    ])

    XCTAssertEqual(merged.count, 1)
    XCTAssertEqual(merged[0].onsetSec, 10)
    XCTAssertEqual(merged[0].offsetSec, 11)
    XCTAssertEqual(Set(merged[0].sourceEventIDs), Set(fragments.map(\.id)))
    XCTAssertEqual(editor.notes.count, beforeMergeCount - 3)
    try editor.undo()
    XCTAssertEqual(editor.notes.count, beforeMergeCount)
  }

  func testSustainMergeClampsModelSpillToSongEnd() throws {
    let fixture = try FixtureProject()
    defer { fixture.remove() }
    let snapshot = try ProjectLoader.open(projectURL: fixture.root)
    var editor = try EditorProject(
      snapshot: snapshot,
      bundleID: "bundle-a",
      selectedTrackID: "candidate-a"
    )
    let fragments = (0..<8).map { index in
      testNote(
        id: "spill-fragment-\(index)",
        onset: 9 + Double(index) * 0.25,
        offset: 9 + Double(index + 1) * 0.25,
        pitch: 60
      )
    }
    for fragment in fragments {
      try editor.create(fragment)
    }
    let merged = try editor.mergeSustainFragments([
      SustainFragmentGroup(
        pitchMIDI: 60,
        noteIDs: fragments.map(\.id),
        onsetSec: 9,
        offsetSec: 10
      )
    ])

    XCTAssertEqual(merged.count, 1)
    XCTAssertEqual(merged[0].onsetSec, 9)
    XCTAssertEqual(merged[0].offsetSec, 10)
  }

  func testSustainMergePersistsAsContinuousNotesAfterReopen() throws {
    let fixture = try FixtureProject()
    defer { fixture.remove() }
    let snapshot = try ProjectLoader.open(projectURL: fixture.root)
    var editor = try EditorProject(
      snapshot: snapshot,
      bundleID: "bundle-a",
      selectedTrackID: "candidate-a"
    )
    let fragments = (0..<12).map { index in
      testNote(
        id: "persistent-fragment-\(index)",
        onset: 4 + Double(index) * 0.25,
        offset: 4 + Double(index + 1) * 0.25,
        pitch: 60
      )
    }
    for fragment in fragments {
      try editor.create(fragment)
    }
    let merged = try editor.mergeSustainFragments([
      SustainFragmentGroup(
        pitchMIDI: 60,
        noteIDs: fragments.map(\.id),
        onsetSec: 4,
        offsetSec: 7
      )
    ])
    try editor.save()

    let reopened = try EditorProject(
      snapshot: snapshot,
      bundleID: "bundle-a",
      selectedTrackID: "candidate-a"
    )
    let mergedID = try XCTUnwrap(merged.first?.id)
    let persisted = try XCTUnwrap(
      reopened.notes.first(where: { $0.id == mergedID })
    )
    XCTAssertEqual(persisted.onsetSec, 4)
    XCTAssertEqual(persisted.offsetSec, 7)
    XCTAssertTrue(
      Set(reopened.notes.map(\.id)).isDisjoint(
        with: Set(fragments.map(\.id))
      )
    )
  }

  func testPercussionRepeatCollapseKeepsOneHitAndIsUndoable() throws {
    let fixture = try FixtureProject()
    defer { fixture.remove() }
    let snapshot = try ProjectLoader.open(projectURL: fixture.root)
    var editor = try EditorProject(
      snapshot: snapshot,
      bundleID: "bundle-a",
      selectedTrackID: "candidate-a"
    )
    let hits = (0..<5).map { index in
      testNote(
        id: "drum-hit-\(index)",
        onset: 8 + Double(index) * 0.25,
        offset: 8.01 + Double(index) * 0.25,
        pitch: 42
      )
    }
    for hit in hits {
      try editor.create(hit)
    }
    let beforeCount = editor.notes.count
    let collapsed = try editor.collapsePercussionRepeats([
      SustainFragmentGroup(
        pitchMIDI: 42,
        noteIDs: hits.map(\.id),
        onsetSec: 8,
        offsetSec: 9.01
      )
    ])

    XCTAssertEqual(collapsed.count, 1)
    XCTAssertEqual(collapsed[0].onsetSec, 8)
    XCTAssertEqual(collapsed[0].offsetSec, 8.01)
    XCTAssertTrue(
      collapsed[0].tags.contains("app-percussion-repeat-collapse")
    )
    XCTAssertEqual(editor.notes.count, beforeCount - 4)
    try editor.undo()
    XCTAssertEqual(editor.notes.count, beforeCount)
  }

  func testLegacyAppSustainOverflowRepairIsUndoable() throws {
    let fixture = try FixtureProject()
    defer { fixture.remove() }
    let snapshot = try ProjectLoader.open(projectURL: fixture.root)
    var editor = try EditorProject(
      snapshot: snapshot,
      bundleID: "bundle-a",
      selectedTrackID: "candidate-a"
    )
    let overflow = testNote(
      id: "legacy-sustain",
      onset: 9,
      offset: 12,
      pitch: 60
    )
    var taggedOverflow = overflow
    taggedOverflow.tags = ["app-sustain-merge"]
    try editor.create(taggedOverflow)

    XCTAssertEqual(
      try editor.repairLegacySustainOverflow(timelineEnd: 10),
      1
    )
    XCTAssertEqual(
      editor.notes.first(where: { $0.id == overflow.id })?.offsetSec,
      10
    )
    try editor.undo()
    XCTAssertEqual(
      editor.notes.first(where: { $0.id == overflow.id })?.offsetSec,
      12
    )
  }

  func testRhythmTimelineUsesDetectedBeatsAndLabelsReviewIssues() throws {
    var events: [[String: Any]] = []
    for index in 0..<12 {
      let event: [String: Any] = [
        "time_sec": Double(index) * 0.5,
        "beat_number": index % 4 + 1,
        "is_downbeat": index % 4 == 0,
      ]
      events.append(event)
    }
    let tempoMap: [[String: Any]] = [
      ["time_sec": 0.0, "bpm": 118.0],
      ["time_sec": 0.5, "bpm": 120.0],
      ["time_sec": 1.0, "bpm": 122.0],
    ]
    let meterMap: [[String: Any]] = [
      [
        "time_sec": 0.0,
        "numerator": 4,
        "denominator": 4,
        "status": "inferred",
      ]
    ]
    let rhythmJSON: [String: Any] = [
      "source_run_id": "beat-run",
      "source_model": "final0",
      "events": events,
      "tempo_map": tempoMap,
      "meter_map": meterMap,
      "uncertainty": ["event_confidence_available": false],
    ]
    let rhythm = try JSONDecoder().decode(
      RhythmMap.self,
      from: JSONSerialization.data(
        withJSONObject: rhythmJSON,
        options: [.sortedKeys]
      )
    )

    XCTAssertTrue(rhythm.isModelEstimated)
    XCTAssertEqual(RhythmTimeline.representativeBPM(rhythm), 120)
    let position = RhythmTimeline.position(
      at: 2.6,
      duration: 8,
      rhythm: rhythm
    )
    XCTAssertEqual(position.bar, 2)
    XCTAssertEqual(position.beat, 2)
    XCTAssertEqual(position.beatFraction, 0.2, accuracy: 0.001)
    XCTAssertEqual(position.displayLabel, "第 2 小节 · 第 2 拍")

    let issues = ProjectReviewAnalyzer.issues(
      notes: [
        EditorNote(
          id: "short-low",
          trackID: "voice",
          sourceTrackID: "voice",
          instrument: "voice",
          onsetSec: 2,
          offsetSec: 2.02,
          pitchMIDI: 64,
          velocity: 80,
          confidence: 0.2,
          isMainMelodyCandidate: true,
          sourceRunID: "run",
          sourceModel: "model",
          sourceEventIDs: [],
          tags: [],
          extra: [:]
        )
      ]
    )
    XCTAssertEqual(Set(issues.map(\.kind)), [.lowConfidence, .veryShort])
  }

  func testOptionalEventFieldsDefaultAndFutureSchemaIsRejected() throws {
    let minimal: [String: Any] = [
      "schema_version": 1,
      "event_id": "minimal-note",
      "track_id": "minimal-track",
      "onset_sec": 0.0,
      "offset_sec": 0.5,
      "pitch_midi": 60.0,
      "source_run_id": "minimal-run",
      "source_model": "minimal-model",
    ]
    let record = try JSONDecoder().decode(
      NoteEventRecord.self,
      from: JSONSerialization.data(
        withJSONObject: minimal,
        options: [.sortedKeys]
      )
    )
    XCTAssertFalse(record.isMainMelodyCandidate)
    XCTAssertEqual(record.sourceEventIDs, [])
    XCTAssertEqual(record.tags, [])
    XCTAssertEqual(record.extra, [:])

    var future = minimal
    future["schema_version"] = 2
    XCTAssertThrowsError(
      try JSONDecoder().decode(
        NoteEventRecord.self,
        from: JSONSerialization.data(
          withJSONObject: future,
          options: [.sortedKeys]
        )
      )
    )
  }

  func testConfiguredRealProjectOpensWithExplicitSelection() throws {
    let environment = ProcessInfo.processInfo.environment
    guard let projectPath = environment["AMT_STUDIO_REAL_PROJECT"],
      let bundleID = environment["AMT_STUDIO_REAL_BUNDLE"],
      let trackID = environment["AMT_STUDIO_REAL_TRACK"]
    else {
      throw XCTSkip(
        "Set AMT_STUDIO_REAL_PROJECT/BUNDLE/TRACK for private integration."
      )
    }

    let catalog = try ProjectLoader.inspect(
      URL(fileURLWithPath: projectPath)
    )
    XCTAssertGreaterThanOrEqual(catalog.bundles.count, 1)
    if catalog.bundles.count > 1 {
      XCTAssertThrowsError(try ProjectLoader.open(catalog))
    } else {
      XCTAssertNoThrow(try ProjectLoader.open(catalog))
    }
    let snapshot = try ProjectLoader.open(catalog, bundleID: bundleID)
    let selectedTrack = try XCTUnwrap(
      snapshot.tracks.first(where: { $0.id == trackID })
    )
    let sourceNotes = snapshot.notes.filter {
      $0.trackID == selectedTrack.id
    }
    XCTAssertGreaterThan(sourceNotes.count, 0)

    let editor = try EditorProject(
      snapshot: snapshot,
      bundleID: bundleID,
      selectedTrackID: trackID
    )
    XCTAssertGreaterThan(editor.notes.count, 0)
    if environment["AMT_STUDIO_REAL_EXPECT_MIGRATED"] == "1" {
      XCTAssertTrue(editor.restoredFromCompatibleVersion)
      XCTAssertNotNil(editor.persistedUpdatedAt)
    }
    if let expectedGroupText = environment[
      "AMT_STUDIO_REAL_SUSTAIN_GROUPS"
    ], let expectedGroups = Int(expectedGroupText) {
      let timelineEnd = try XCTUnwrap(
        snapshot.manifest.canonicalAudio.metadata?.durationSec
      )
      let groups = SustainFragmentAnalyzer.trailingGroups(
        notes: sourceNotes,
        timelineEnd: timelineEnd
      )
      XCTAssertEqual(groups.count, expectedGroups)
      XCTAssertTrue(
        groups.allSatisfy { $0.offsetSec <= timelineEnd }
      )
      if let expectedFragmentText = environment[
        "AMT_STUDIO_REAL_SUSTAIN_FRAGMENTS"
      ], let expectedFragments = Int(expectedFragmentText) {
        XCTAssertEqual(
          groups.reduce(0) { $0 + $1.fragmentCount },
          expectedFragments
        )
      }
    }
    let configuredOutput = environment["AMT_STUDIO_REAL_MIDI_OUTPUT"]
    let output =
      configuredOutput.map(URL.init(fileURLWithPath:))
      ?? FileManager.default.temporaryDirectory.appendingPathComponent(
        "AMTStudio-real-\(UUID().uuidString).mid"
      )
    defer {
      if configuredOutput == nil {
        try? FileManager.default.removeItem(at: output)
      }
    }
    let report = try MIDIExporter.export(project: editor, to: output)
    let productNotes = CanonicalTimeline.clippedNotes(
      editor.notes,
      duration:
        snapshot.manifest.canonicalAudio.metadata?.durationSec
        ?? .infinity
    )
    XCTAssertEqual(report.noteCount, productNotes.count)
    XCTAssertEqual(
      String(
        data: try Data(contentsOf: output).prefix(4),
        encoding: .ascii
      ),
      "MThd"
    )

    let arrangementOutput = output.deletingLastPathComponent()
      .appendingPathComponent("AMTStudio-real-arrangement-\(UUID().uuidString).mid")
    defer { try? FileManager.default.removeItem(at: arrangementOutput) }
    let arrangement = try MIDIExporter.exportArrangement(
      snapshot: snapshot,
      bundleID: bundleID,
      to: arrangementOutput
    )
    XCTAssertEqual(arrangement.trackCount, snapshot.tracks.count)
    XCTAssertGreaterThan(arrangement.noteCount, 0)
    XCTAssertEqual(
      String(
        data: try Data(contentsOf: arrangementOutput).prefix(4),
        encoding: .ascii
      ),
      "MThd"
    )
  }

  func testUnicodeProjectOpensWithoutChoosingModelsOrRunningInference() throws {
    let fixture = try FixtureProject()
    defer { fixture.remove() }

    let catalog = try ProjectLoader.inspect(fixture.root)
    XCTAssertEqual(catalog.manifest.projectID, "项目-unicode")
    XCTAssertEqual(catalog.bundles.map(\.id), ["bundle-a"])

    let snapshot = try ProjectLoader.open(catalog)
    XCTAssertEqual(snapshot.tracks.map(\.id), ["candidate-a"])
    XCTAssertEqual(snapshot.notes.count, 2)
    XCTAssertEqual(snapshot.notes[0].sourceTrackID, "native:voice")
    XCTAssertEqual(
      snapshot.notes[0].extra["nested"],
      .object(["kept": .bool(true)])
    )
  }

  func testMultipleBundlesRequireExplicitSelection() throws {
    let fixture = try FixtureProject(bundleIDs: ["bundle-a", "bundle-b"])
    defer { fixture.remove() }

    let catalog = try ProjectLoader.inspect(fixture.root)
    XCTAssertEqual(catalog.bundles.count, 2)
    XCTAssertThrowsError(try ProjectLoader.open(catalog)) { error in
      XCTAssertEqual(
        error as? AMTProjectError,
        .ambiguousCanonicalBundles
      )
    }
    let snapshot = try ProjectLoader.open(catalog, bundleID: "bundle-b")
    XCTAssertEqual(snapshot.canonicalProject.projectID, "项目-unicode")
  }

  func testTrackArrangementCopyMergeAndDeleteCreateDerivedBundles() throws {
    let fixture = try FixtureProject(bundleIDs: ["bundle-a", "bundle-b"])
    defer { fixture.remove() }
    let sourceCatalog = try ProjectLoader.inspect(fixture.root)
    let sourceA = try Data(
      contentsOf: fixture.root.appendingPathComponent(
        "exports/bundle-a/canonical_project.json"
      )
    )
    let sourceB = try Data(
      contentsOf: fixture.root.appendingPathComponent(
        "exports/bundle-b/canonical_project.json"
      )
    )

    let copied = try TrackArrangementBuilder.derive(
      catalog: sourceCatalog,
      targetBundleID: "bundle-a",
      action: .copy(
        sourceBundleID: "bundle-b",
        sourceTrackID: "candidate-a"
      )
    )
    var catalog = try ProjectLoader.inspect(fixture.root)
    let copiedSnapshot = try ProjectLoader.open(
      catalog,
      bundleID: copied.bundleID
    )
    XCTAssertEqual(copiedSnapshot.tracks.count, 2)
    XCTAssertEqual(copiedSnapshot.notes.count, 4)
    XCTAssertEqual(
      copiedSnapshot.tracks.last?.id,
      copied.selectedTrackID
    )
    XCTAssertTrue(
      copiedSnapshot.notes
        .filter { $0.trackID == copied.selectedTrackID }
        .allSatisfy {
          $0.tags.contains("app-track-copy")
            && !$0.sourceEventIDs.isEmpty
        }
    )

    let merged = try TrackArrangementBuilder.derive(
      catalog: catalog,
      targetBundleID: copied.bundleID,
      action: .merge(
        trackIDs: Set(copiedSnapshot.tracks.map(\.id)),
        instrumentSourceTrackID: copied.selectedTrackID
      )
    )
    catalog = try ProjectLoader.inspect(fixture.root)
    let mergedSnapshot = try ProjectLoader.open(
      catalog,
      bundleID: merged.bundleID
    )
    XCTAssertEqual(mergedSnapshot.tracks.count, 1)
    XCTAssertEqual(mergedSnapshot.notes.count, 4)
    XCTAssertEqual(mergedSnapshot.tracks[0].instrument, "voice")
    XCTAssertTrue(
      mergedSnapshot.notes.allSatisfy { $0.instrument == "voice" }
    )
    XCTAssertTrue(
      mergedSnapshot.notes.allSatisfy {
        $0.tags.contains("app-track-merge")
      }
    )
    let mergedMIDI = fixture.root.appendingPathComponent(
      "exports/merged-arrangement.mid"
    )
    let exportReport = try MIDIExporter.exportArrangement(
      snapshot: mergedSnapshot,
      bundleID: merged.bundleID,
      to: mergedMIDI,
      includedTrackIDs: Set(mergedSnapshot.tracks.map(\.id))
    )
    XCTAssertEqual(exportReport.trackCount, 1)
    XCTAssertEqual(exportReport.noteCount, 4)
    XCTAssertEqual(
      String(
        data: try Data(contentsOf: mergedMIDI).prefix(4),
        encoding: .ascii
      ),
      "MThd"
    )

    let deleted = try TrackArrangementBuilder.derive(
      catalog: catalog,
      targetBundleID: copied.bundleID,
      action: .delete(trackID: "candidate-a")
    )
    catalog = try ProjectLoader.inspect(fixture.root)
    let deletedSnapshot = try ProjectLoader.open(
      catalog,
      bundleID: deleted.bundleID
    )
    XCTAssertEqual(deletedSnapshot.tracks.count, 1)
    XCTAssertEqual(deletedSnapshot.tracks[0].id, copied.selectedTrackID)
    XCTAssertThrowsError(
      try TrackArrangementBuilder.derive(
        catalog: catalog,
        targetBundleID: deleted.bundleID,
        action: .delete(trackID: copied.selectedTrackID)
      )
    )

    XCTAssertEqual(
      try Data(
        contentsOf: fixture.root.appendingPathComponent(
          "exports/bundle-a/canonical_project.json"
        )
      ),
      sourceA
    )
    XCTAssertEqual(
      try Data(
        contentsOf: fixture.root.appendingPathComponent(
          "exports/bundle-b/canonical_project.json"
        )
      ),
      sourceB
    )
  }

  func testDuplicateCanonicalTrackIDsAreRejectedBeforeMixingNotes() throws {
    let fixture = try FixtureProject()
    defer { fixture.remove() }
    var canonical = try jsonObject(fixture.canonicalURL)
    var tracks = canonical["tracks"] as! [[String: Any]]
    tracks.append(tracks[0])
    canonical["tracks"] = tracks
    try writeJSON(canonical, to: fixture.canonicalURL)
    try fixture.refreshBundleManifest()

    XCTAssertThrowsError(
      try ProjectLoader.open(
        ProjectLoader.inspect(fixture.root),
        bundleID: "bundle-a"
      )
    ) { error in
      guard case .malformedManifest = error as? AMTProjectError else {
        return XCTFail("Expected malformedManifest, got \(error)")
      }
    }
  }

  func testTamperedEventAndEscapingPathAreRejected() throws {
    let fixture = try FixtureProject()
    defer { fixture.remove() }
    try Data("tampered\n".utf8).write(to: fixture.eventsURL)
    XCTAssertThrowsError(
      try ProjectLoader.open(
        ProjectLoader.inspect(fixture.root),
        bundleID: "bundle-a"
      )
    )

    let unsafe = try FixtureProject()
    defer { unsafe.remove() }
    var canonical = try jsonObject(unsafe.canonicalURL)
    var tracks = canonical["tracks"] as! [[String: Any]]
    tracks[0]["source_events_path"] = "../escape.jsonl"
    canonical["tracks"] = tracks
    try writeJSON(canonical, to: unsafe.canonicalURL)
    try unsafe.refreshBundleManifest()
    XCTAssertThrowsError(
      try ProjectLoader.open(
        ProjectLoader.inspect(unsafe.root),
        bundleID: "bundle-a"
      )
    ) { error in
      XCTAssertEqual(
        error as? AMTProjectError,
        .unsafePath("../escape.jsonl")
      )
    }
  }

  func testEditUndoRedoAndRestartPreserveBaseJSONL() throws {
    let fixture = try FixtureProject()
    defer { fixture.remove() }
    let originalEvents = try Data(contentsOf: fixture.eventsURL)
    let snapshot = try ProjectLoader.open(projectURL: fixture.root)
    var editor = try EditorProject(
      snapshot: snapshot,
      bundleID: "bundle-a",
      selectedTrackID: "candidate-a"
    )
    let original = try XCTUnwrap(editor.notes.first)

    try editor.move(
      noteID: original.id,
      onsetSec: original.onsetSec + 0.25,
      pitchMIDI: original.pitchMIDI + 2
    )
    try editor.resize(
      noteID: original.id,
      offsetSec: original.offsetSec + 0.5
    )
    XCTAssertEqual(editor.notes.first?.pitchMIDI, original.pitchMIDI + 2)
    XCTAssertEqual(editor.operations.count, 2)

    try editor.undo()
    XCTAssertEqual(
      editor.notes.first?.offsetSec,
      original.offsetSec + 0.25
    )
    try editor.redo()
    XCTAssertEqual(
      try XCTUnwrap(editor.notes.first?.offsetSec),
      original.offsetSec + 0.5,
      accuracy: 0.000_001
    )
    try editor.save()
    XCTAssertEqual(try Data(contentsOf: fixture.eventsURL), originalEvents)

    let reopenedSnapshot = try ProjectLoader.open(projectURL: fixture.root)
    let reopened = try EditorProject(
      snapshot: reopenedSnapshot,
      bundleID: "bundle-a",
      selectedTrackID: "candidate-a"
    )
    XCTAssertEqual(reopened.operations.count, 2)
    XCTAssertEqual(reopened.notes, editor.notes)
    XCTAssertTrue(
      FileManager.default.fileExists(
        atPath: fixture.root
          .appendingPathComponent("app/workspace.json").path
      )
    )

    let operationsURL = reopened.sessionDirectoryURL
      .appendingPathComponent("operations.jsonl")
    let decoder = JSONDecoder()
    decoder.dateDecodingStrategy = .iso8601
    let operationLines = try String(
      contentsOf: operationsURL,
      encoding: .utf8
    ).split(whereSeparator: \.isNewline)
    XCTAssertEqual(operationLines.count, reopened.operations.count)
    for line in operationLines {
      _ = try decoder.decode(
        EditOperation.self,
        from: Data(line.utf8)
      )
    }
  }

  func testCompatibleEditsFollowAnUnchangedTrackIntoANewerBundle() throws {
    let fixture = try FixtureProject(bundleIDs: ["bundle-a", "bundle-b"])
    defer { fixture.remove() }
    let catalog = try ProjectLoader.inspect(fixture.root)
    let oldSnapshot = try ProjectLoader.open(catalog, bundleID: "bundle-a")
    var oldEditor = try EditorProject(
      snapshot: oldSnapshot,
      bundleID: "bundle-a",
      selectedTrackID: "candidate-a"
    )
    let original = try XCTUnwrap(oldEditor.notes.first)
    try oldEditor.move(
      noteID: original.id,
      onsetSec: original.onsetSec + 0.2,
      pitchMIDI: original.pitchMIDI + 1
    )
    try oldEditor.save()

    let newerCanonical = fixture.root.appendingPathComponent(
      "exports/bundle-b/canonical_project.json"
    )
    var value = try jsonObject(newerCanonical)
    var rhythm = value["rhythm"] as! [String: Any]
    rhythm["tempo_map"] = [["time_sec": 0.0, "bpm": 121.0]]
    value["rhythm"] = rhythm
    try writeJSON(value, to: newerCanonical)
    try fixture.refreshBundleManifest(bundleID: "bundle-b")

    let refreshedCatalog = try ProjectLoader.inspect(fixture.root)
    let newSnapshot = try ProjectLoader.open(
      refreshedCatalog,
      bundleID: "bundle-b"
    )
    XCTAssertNotEqual(oldSnapshot.baseFingerprint, newSnapshot.baseFingerprint)
    var newEditor = try EditorProject(
      snapshot: newSnapshot,
      bundleID: "bundle-b",
      selectedTrackID: "candidate-a"
    )

    XCTAssertTrue(newEditor.restoredFromCompatibleVersion)
    XCTAssertEqual(newEditor.notes.first?.pitchMIDI, original.pitchMIDI + 1)
    XCTAssertEqual(
      try XCTUnwrap(newEditor.notes.first?.onsetSec),
      original.onsetSec + 0.2,
      accuracy: 0.000_001
    )
    try newEditor.save()

    let reopened = try EditorProject(
      snapshot: newSnapshot,
      bundleID: "bundle-b",
      selectedTrackID: "candidate-a"
    )
    XCTAssertFalse(reopened.restoredFromCompatibleVersion)
    XCTAssertEqual(reopened.notes, newEditor.notes)
  }

  func testEditorRefusesSymlinkedWriteDirectories() throws {
    let fixture = try FixtureProject()
    defer { fixture.remove() }
    let outside = FileManager.default.temporaryDirectory
      .appendingPathComponent("AMT-outside-\(UUID().uuidString)")
    try FileManager.default.createDirectory(
      at: outside,
      withIntermediateDirectories: true
    )
    defer { try? FileManager.default.removeItem(at: outside) }
    try FileManager.default.createSymbolicLink(
      at: fixture.root.appendingPathComponent("annotations"),
      withDestinationURL: outside
    )
    let snapshot = try ProjectLoader.open(projectURL: fixture.root)

    XCTAssertThrowsError(
      try EditorProject(
        snapshot: snapshot,
        bundleID: "bundle-a",
        selectedTrackID: "candidate-a"
      )
    ) { error in
      guard case .unsafePath = error as? AMTProjectError else {
        return XCTFail("Expected unsafePath, got \(error)")
      }
    }
    XCTAssertEqual(
      try FileManager.default.contentsOfDirectory(atPath: outside.path),
      []
    )
  }

  func testPerformanceMIDIExportHasConductorAndSelectedTrack() throws {
    let fixture = try FixtureProject()
    defer { fixture.remove() }
    let snapshot = try ProjectLoader.open(projectURL: fixture.root)
    let editor = try EditorProject(
      snapshot: snapshot,
      bundleID: "bundle-a",
      selectedTrackID: "candidate-a"
    )
    let output = fixture.root.appendingPathComponent(
      "exports/app-selected.performance.mid"
    )
    let report = try MIDIExporter.export(project: editor, to: output)
    let data = try Data(contentsOf: output)

    XCTAssertEqual(report.noteCount, 2)
    XCTAssertEqual(report.trackCount, 1)
    XCTAssertEqual(String(data: data.prefix(4), encoding: .ascii), "MThd")
    XCTAssertEqual(readUInt16(data, at: 8), 1)
    XCTAssertEqual(readUInt16(data, at: 10), 2)
    XCTAssertEqual(readUInt16(data, at: 12), 960)
    XCTAssertEqual(countOccurrences(of: Data("MTrk".utf8), in: data), 2)
  }

  func testArrangementPreviewHonorsTrackSelectionAndVolume() throws {
    let fixture = try FixtureProject()
    defer { fixture.remove() }
    let snapshot = try ProjectLoader.open(projectURL: fixture.root)
    let output = fixture.root.appendingPathComponent(
      "exports/app-mix.performance.mid"
    )
    let report = try MIDIExporter.exportArrangement(
      snapshot: snapshot,
      bundleID: "bundle-a",
      to: output,
      includedTrackIDs: Set(["candidate-a"]),
      trackVolumes: ["candidate-a": 0.5]
    )
    let data = try Data(contentsOf: output)

    XCTAssertEqual(report.trackCount, 1)
    XCTAssertEqual(report.noteCount, 2)
    XCTAssertNotNil(data.range(of: Data([0xB0, 0x07, 0x40])))

    XCTAssertThrowsError(
      try MIDIExporter.exportArrangement(
        snapshot: snapshot,
        bundleID: "bundle-a",
        to: output,
        includedTrackIDs: []
      )
    )
    XCTAssertThrowsError(
      try MIDIExporter.exportArrangement(
        snapshot: snapshot,
        bundleID: "bundle-a",
        to: output,
        includedTrackIDs: Set(["missing-track"])
      )
    )
  }

  func testMIDIExportRejectsHugeTimesWithoutIntegerTrap() throws {
    let fixture = try FixtureProject()
    defer { fixture.remove() }
    let snapshot = try ProjectLoader.open(projectURL: fixture.root)
    var editor = try EditorProject(
      snapshot: snapshot,
      bundleID: "bundle-a",
      selectedTrackID: "candidate-a"
    )
    var note = try XCTUnwrap(editor.notes.first)
    note.onsetSec = 1_000_000_000
    note.offsetSec = 1_000_000_001
    try editor.update(note)

    XCTAssertThrowsError(
      try MIDIExporter.export(
        project: editor,
        to: fixture.root.appendingPathComponent("huge.mid")
      )
    ) { error in
      guard case .malformedManifest = error as? AMTProjectError else {
        return XCTFail("Expected malformedManifest, got \(error)")
      }
    }
  }

  func testMIDIExportRejectsUnrepresentableTempoWithoutIntegerTrap() throws {
    let fixture = try FixtureProject()
    defer { fixture.remove() }
    var canonical = try jsonObject(fixture.canonicalURL)
    var rhythm = canonical["rhythm"] as! [String: Any]
    rhythm["tempo_map"] = [["time_sec": 0.0, "bpm": 1e-300]]
    canonical["rhythm"] = rhythm
    try writeJSON(canonical, to: fixture.canonicalURL)
    try fixture.refreshBundleManifest()
    let snapshot = try ProjectLoader.open(projectURL: fixture.root)
    let editor = try EditorProject(
      snapshot: snapshot,
      bundleID: "bundle-a",
      selectedTrackID: "candidate-a"
    )

    XCTAssertThrowsError(
      try MIDIExporter.export(
        project: editor,
        to: fixture.root.appendingPathComponent("bad-tempo.mid")
      )
    ) { error in
      guard case .malformedManifest = error as? AMTProjectError else {
        return XCTFail("Expected malformedManifest, got \(error)")
      }
    }
  }

  func testCreateDeleteAndSplitAreLosslessAndUndoable() throws {
    let fixture = try FixtureProject()
    defer { fixture.remove() }
    let snapshot = try ProjectLoader.open(projectURL: fixture.root)
    var editor = try EditorProject(
      snapshot: snapshot,
      bundleID: "bundle-a",
      selectedTrackID: "candidate-a"
    )
    let original = try XCTUnwrap(editor.notes.first)
    try editor.split(
      noteID: original.id,
      at: (original.onsetSec + original.offsetSec) / 2
    )
    XCTAssertEqual(editor.notes.count, 3)
    try editor.undo()
    XCTAssertEqual(editor.notes.count, 2)
    try editor.delete(noteID: original.id)
    XCTAssertEqual(editor.notes.count, 1)
    try editor.undo()
    XCTAssertEqual(editor.notes.count, 2)

    var wrongTrack = original
    wrongTrack.trackID = "another-track"
    XCTAssertThrowsError(try editor.create(wrongTrack))
  }
}

private func testNote(
  id: String,
  onset: Double,
  offset: Double,
  pitch: Double
) -> EditorNote {
  EditorNote(
    id: id,
    trackID: "candidate-a",
    sourceTrackID: "candidate-a",
    instrument: "clean_electric_guitar",
    onsetSec: onset,
    offsetSec: offset,
    pitchMIDI: pitch,
    velocity: 80,
    confidence: nil,
    isMainMelodyCandidate: false,
    sourceRunID: "fixture-run",
    sourceModel: "fixture-model",
    sourceEventIDs: [],
    tags: [],
    extra: [:]
  )
}

private func countOccurrences(of needle: Data, in haystack: Data) -> Int {
  guard !needle.isEmpty, haystack.count >= needle.count else { return 0 }
  return (0...haystack.count - needle.count).reduce(into: 0) {
    count, offset in
    if haystack[offset..<offset + needle.count] == needle[...] {
      count += 1
    }
  }
}

private final class FixtureProject {
  let root: URL
  let eventsURL: URL
  let canonicalURL: URL
  private let bundleIDs: [String]

  init(bundleIDs: [String] = ["bundle-a"]) throws {
    self.bundleIDs = bundleIDs
    root = FileManager.default.temporaryDirectory
      .appendingPathComponent("AMT Studio 测试 \(UUID().uuidString)")
    eventsURL = root.appendingPathComponent(
      "runs/run-a/normalized/events.jsonl"
    )
    canonicalURL = root.appendingPathComponent(
      "exports/\(bundleIDs[0])/canonical_project.json"
    )
    try FileManager.default.createDirectory(
      at: eventsURL.deletingLastPathComponent(),
      withIntermediateDirectories: true
    )
    try FileManager.default.createDirectory(
      at: root.appendingPathComponent("audio/canonical"),
      withIntermediateDirectories: true
    )
    let audioURL = root.appendingPathComponent("audio/canonical/mix.flac")
    try Data("fixture-audio".utf8).write(to: audioURL)
    let audioHash = try ProjectLoader.sha256(audioURL)
    try writeJSON(
      [
        "schema_version": 1,
        "project_id": "项目-unicode",
        "title": "测试 歌曲",
        "canonical_audio": [
          "path": "audio/canonical/mix.flac",
          "sha256": audioHash,
        ],
      ],
      to: root.appendingPathComponent("manifest.json")
    )

    let events = [
      noteJSON(
        id: "note-1",
        onset: 0.25,
        offset: 0.75,
        pitch: 60.25
      ),
      noteJSON(
        id: "note-2",
        onset: 1.0,
        offset: 1.5,
        pitch: 64
      ),
    ]
    let eventData =
      try events
      .map { try JSONSerialization.data(withJSONObject: $0, options: [.sortedKeys]) }
      .map { $0 + Data([0x0A]) }
      .reduce(into: Data()) { $0.append($1) }
    try eventData.write(to: eventsURL)
    let eventHash = try ProjectLoader.sha256(eventsURL)
    let canonical: [String: Any] = [
      "schema_version": 1,
      "artifact_type": "amt-canonical-project",
      "project_id": "项目-unicode",
      "timeline_basis": "original_canonical_mix_seconds",
      "canonical_audio": [
        "path": "audio/canonical/mix.flac",
        "sha256": audioHash,
      ],
      "worker_results": [],
      "tracks": [
        [
          "track_id": "candidate-a",
          "label": "候选 A",
          "role": "candidate",
          "instrument": "voice",
          "event_count": 2,
          "source_events_path": "runs/run-a/normalized/events.jsonl",
          "provenance": [
            "source_run_id": "run-a",
            "source_model": "fixture/model",
            "run_manifest_sha256": String(repeating: "1", count: 64),
            "normalized_artifact_sha256": eventHash,
          ],
        ]
      ],
      "rhythm": [
        "tempo_map": [
          ["time_sec": 0.0, "bpm": 120.0]
        ],
        "meter_map": [
          [
            "time_sec": 0.0,
            "numerator": 4,
            "denominator": 4,
          ]
        ],
      ],
      "exports": [:],
      "claims": [
        "preferred_candidate_selected": false
      ],
    ]
    for bundleID in bundleIDs {
      let bundleDirectory = root.appendingPathComponent(
        "exports/\(bundleID)"
      )
      try FileManager.default.createDirectory(
        at: bundleDirectory,
        withIntermediateDirectories: true
      )
      try writeJSON(
        canonical,
        to: bundleDirectory.appendingPathComponent(
          "canonical_project.json"
        )
      )
      try refreshBundleManifest(bundleID: bundleID)
    }
  }

  func refreshBundleManifest(bundleID: String? = nil) throws {
    for id in bundleID.map({ [$0] }) ?? bundleIDs {
      let directory = root.appendingPathComponent("exports/\(id)")
      let canonical = directory.appendingPathComponent(
        "canonical_project.json"
      )
      let audioHash = try ProjectLoader.sha256(
        root.appendingPathComponent("audio/canonical/mix.flac")
      )
      let size = try canonical.resourceValues(
        forKeys: [.fileSizeKey]
      ).fileSize!
      try writeJSON(
        [
          "schema_version": 1,
          "artifact_type": "amt-canonical-bundle",
          "project_id": "项目-unicode",
          "canonical_audio_sha256": audioHash,
          "status": "succeeded",
          "outputs": [
            [
              "path": "canonical_project.json",
              "sha256": try ProjectLoader.sha256(canonical),
              "size_bytes": size,
            ]
          ],
          "limitations": ["fixture"],
        ],
        to: directory.appendingPathComponent(
          "bundle_manifest.json"
        )
      )
    }
  }

  func remove() {
    try? FileManager.default.removeItem(at: root)
  }
}

private func noteJSON(
  id: String,
  onset: Double,
  offset: Double,
  pitch: Double
) -> [String: Any] {
  [
    "schema_version": 1,
    "event_id": id,
    "track_id": "native:voice",
    "instrument": "voice",
    "onset_sec": onset,
    "offset_sec": offset,
    "pitch_midi": pitch,
    "quantized_pitch_midi": Int(pitch.rounded()),
    "velocity": 64,
    "confidence": NSNull(),
    "is_main_melody_candidate": true,
    "source_run_id": "run-a",
    "source_model": "fixture/model",
    "source_event_ids": ["source-\(id)"],
    "tags": ["candidate"],
    "extra": [
      "nested": ["kept": true]
    ],
  ]
}

private func writeJSON(_ value: [String: Any], to url: URL) throws {
  try FileManager.default.createDirectory(
    at: url.deletingLastPathComponent(),
    withIntermediateDirectories: true
  )
  try JSONSerialization.data(
    withJSONObject: value,
    options: [.prettyPrinted, .sortedKeys]
  ).write(to: url, options: [.atomic])
}

private func jsonObject(_ url: URL) throws -> [String: Any] {
  try JSONSerialization.jsonObject(
    with: Data(contentsOf: url)
  ) as! [String: Any]
}

private func readUInt16(_ data: Data, at offset: Int) -> UInt16 {
  UInt16(data[offset]) << 8 | UInt16(data[offset + 1])
}
