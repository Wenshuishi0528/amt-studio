import CryptoKit
import Foundation

public struct ProjectCatalog: Sendable {
  public let rootURL: URL
  public let manifest: ProjectManifest
  public let audioURL: URL
  public let bundles: [CanonicalBundleChoice]

  public init(
    rootURL: URL,
    manifest: ProjectManifest,
    audioURL: URL,
    bundles: [CanonicalBundleChoice]
  ) {
    self.rootURL = rootURL
    self.manifest = manifest
    self.audioURL = audioURL
    self.bundles = bundles
  }
}

public enum ProjectLoader {
  public static func inspect(_ projectURL: URL) throws -> ProjectCatalog {
    let rootURL = projectURL.standardizedFileURL.resolvingSymlinksInPath()
    var isDirectory: ObjCBool = false
    guard
      FileManager.default.fileExists(
        atPath: rootURL.path,
        isDirectory: &isDirectory
      ), isDirectory.boolValue
    else {
      throw AMTProjectError.missingManifest
    }
    let manifestURL = rootURL.appendingPathComponent("manifest.json")
    guard FileManager.default.fileExists(atPath: manifestURL.path) else {
      throw AMTProjectError.missingManifest
    }
    let manifest: ProjectManifest = try decodeJSON(manifestURL)
    guard manifest.schemaVersion == 1, !manifest.projectID.isEmpty else {
      throw AMTProjectError.malformedManifest("不支持的 schema 或空 project_id")
    }
    let audioURL = try resolveProjectPath(
      manifest.canonicalAudio.path,
      rootURL: rootURL
    )
    try verifyFile(
      audioURL,
      expectedSHA256: manifest.canonicalAudio.sha256,
      expectedSize: nil
    )
    let bundles = try loadBundles(rootURL: rootURL, manifest: manifest)
    return ProjectCatalog(
      rootURL: rootURL,
      manifest: manifest,
      audioURL: audioURL,
      bundles: bundles
    )
  }

  public static func open(
    _ catalog: ProjectCatalog,
    bundleID: String? = nil
  ) throws -> ProjectSnapshot {
    let choice: CanonicalBundleChoice
    if let bundleID {
      guard let selected = catalog.bundles.first(where: { $0.id == bundleID }) else {
        throw AMTProjectError.missingCanonicalBundle
      }
      choice = selected
    } else {
      guard catalog.bundles.count == 1 else {
        if catalog.bundles.isEmpty {
          throw AMTProjectError.missingCanonicalBundle
        }
        throw AMTProjectError.ambiguousCanonicalBundles
      }
      choice = catalog.bundles[0]
    }

    let canonical: CanonicalProject = try decodeJSON(choice.canonicalProjectURL)
    guard canonical.schemaVersion == 1,
      canonical.artifactType == "amt-canonical-project",
      canonical.timelineBasis == "original_canonical_mix_seconds",
      canonical.projectID == catalog.manifest.projectID,
      canonical.canonicalAudio.sha256 == catalog.manifest.canonicalAudio.sha256
    else {
      throw AMTProjectError.malformedManifest(
        "canonical project 与根项目身份不一致"
      )
    }

    var notes: [EditorNote] = []
    var eventIDs = Set<String>()
    var trackIDs = Set<String>()
    var fingerprintParts = [
      try sha256(choice.canonicalProjectURL),
      catalog.manifest.canonicalAudio.sha256,
    ]
    for track in canonical.tracks {
      guard !track.trackID.isEmpty,
        track.eventCount >= 0,
        trackIDs.insert(track.trackID).inserted
      else {
        throw AMTProjectError.malformedManifest(
          "canonical project 包含空或重复 track_id"
        )
      }
      let eventsURL = try resolveProjectPath(
        track.sourceEventsPath,
        rootURL: catalog.rootURL
      )
      try verifyFile(
        eventsURL,
        expectedSHA256: track.provenance.normalizedArtifactSHA256,
        expectedSize: nil
      )
      let records = try decodeEvents(eventsURL)
      guard records.count == track.eventCount else {
        throw AMTProjectError.malformedManifest(
          "\(track.trackID) 声明 \(track.eventCount) 个音符，实际为 \(records.count)"
        )
      }
      fingerprintParts.append(track.provenance.normalizedArtifactSHA256)
      for record in records {
        guard eventIDs.insert(record.eventID).inserted else {
          throw AMTProjectError.duplicateEventID(record.eventID)
        }
        let note = EditorNote(
          id: record.eventID,
          trackID: track.trackID,
          sourceTrackID: record.trackID,
          instrument: record.instrument ?? track.instrument,
          onsetSec: record.onsetSec,
          offsetSec: record.offsetSec,
          pitchMIDI: record.pitchMIDI,
          velocity: record.velocity,
          confidence: record.confidence,
          isMainMelodyCandidate: record.isMainMelodyCandidate,
          sourceRunID: record.sourceRunID,
          sourceModel: record.sourceModel,
          sourceEventIDs: record.sourceEventIDs,
          tags: record.tags,
          extra: record.extra
        )
        notes.append(try note.validated())
      }
    }
    let fingerprint = sha256(Data(fingerprintParts.joined(separator: "\n").utf8))
    let editorTracks = canonical.tracks.map {
      EditorTrack(
        id: $0.trackID,
        label: $0.label,
        role: $0.role,
        instrument: $0.instrument,
        eventCount: $0.eventCount
      )
    }
    return ProjectSnapshot(
      rootURL: catalog.rootURL,
      canonicalProjectURL: choice.canonicalProjectURL,
      audioURL: catalog.audioURL,
      manifest: catalog.manifest,
      canonicalProject: canonical,
      tracks: editorTracks,
      notes: notes,
      baseFingerprint: fingerprint
    )
  }

  public static func open(
    projectURL: URL,
    bundleID: String? = nil
  ) throws -> ProjectSnapshot {
    try open(inspect(projectURL), bundleID: bundleID)
  }

  public static func sha256(_ url: URL) throws -> String {
    let handle = try FileHandle(forReadingFrom: url)
    defer { try? handle.close() }
    var hasher = SHA256()
    while true {
      let data = try handle.read(upToCount: 1_048_576) ?? Data()
      if data.isEmpty {
        break
      }
      hasher.update(data: data)
    }
    return hasher.finalize().map { String(format: "%02x", $0) }.joined()
  }

  private static func sha256(_ data: Data) -> String {
    SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
  }

  private static func loadBundles(
    rootURL: URL,
    manifest: ProjectManifest
  ) throws -> [CanonicalBundleChoice] {
    let exportsURL = rootURL.appendingPathComponent("exports", isDirectory: true)
    guard
      let children = try? FileManager.default.contentsOfDirectory(
        at: exportsURL,
        includingPropertiesForKeys: [.isDirectoryKey, .isSymbolicLinkKey],
        options: [.skipsHiddenFiles]
      )
    else {
      return []
    }
    var result: [CanonicalBundleChoice] = []
    for directoryURL in children.sorted(by: { $0.lastPathComponent < $1.lastPathComponent }) {
      let values = try directoryURL.resourceValues(
        forKeys: [.isDirectoryKey, .isSymbolicLinkKey]
      )
      guard values.isDirectory == true, values.isSymbolicLink != true else {
        continue
      }
      let manifestURL = directoryURL.appendingPathComponent("bundle_manifest.json")
      guard FileManager.default.fileExists(atPath: manifestURL.path) else {
        continue
      }
      let bundle: BundleManifest = try decodeJSON(manifestURL)
      guard bundle.schemaVersion == 1,
        bundle.artifactType == "amt-canonical-bundle",
        bundle.status == "succeeded",
        bundle.projectID == manifest.projectID,
        bundle.canonicalAudioSHA256 == manifest.canonicalAudio.sha256
      else {
        throw AMTProjectError.malformedManifest(
          "bundle \(directoryURL.lastPathComponent) 身份或状态无效"
        )
      }
      for output in bundle.outputs {
        let outputURL = try resolveBundlePath(
          output.path,
          bundleURL: directoryURL
        )
        try verifyFile(
          outputURL,
          expectedSHA256: output.sha256,
          expectedSize: output.sizeBytes
        )
      }
      guard
        let canonicalRecord = bundle.outputs.first(
          where: { $0.path == "canonical_project.json" }
        )
      else {
        throw AMTProjectError.missingArtifact(
          "\(directoryURL.lastPathComponent)/canonical_project.json"
        )
      }
      let canonicalURL = try resolveBundlePath(
        canonicalRecord.path,
        bundleURL: directoryURL
      )
      let canonical: CanonicalProject = try decodeJSON(canonicalURL)
      let automaticAdmissionDecision: String?
      if case .string(let decision)? =
        bundle.claims?["automatic_candidate_admission"]
      {
        automaticAdmissionDecision = decision
      } else {
        automaticAdmissionDecision = nil
      }
      let defaultAssessment = MainMelodyDefaultPolicy.assess(
        trackCounts: Dictionary(
          canonical.tracks.map {
            ($0.trackID, $0.eventCount)
          },
          uniquingKeysWith: { first, _ in first }
        ),
        automaticAdmissionDecision: automaticAdmissionDecision
      )
      result.append(
        CanonicalBundleChoice(
          id: directoryURL.lastPathComponent,
          directoryURL: directoryURL,
          canonicalProjectURL: canonicalURL,
          manifest: bundle,
          tracks: canonical.tracks.map {
            EditorTrack(
              id: $0.trackID,
              label: $0.label,
              role: $0.role,
              instrument: $0.instrument,
              eventCount: $0.eventCount
            )
          },
          modifiedAt: (try? manifestURL.resourceValues(
            forKeys: [.contentModificationDateKey]
          ).contentModificationDate) ?? .distantPast,
          isDefaultEligible: defaultAssessment.isEligible,
          defaultExclusionReason: defaultAssessment.reason
        )
      )
    }
    return result
  }

  private static func decodeJSON<Value: Decodable>(_ url: URL) throws -> Value {
    do {
      return try JSONDecoder().decode(Value.self, from: Data(contentsOf: url))
    } catch {
      throw AMTProjectError.malformedManifest(
        "\(url.lastPathComponent): \(error.localizedDescription)"
      )
    }
  }

  private static func decodeEvents(_ url: URL) throws -> [NoteEventRecord] {
    let text: String
    do {
      text = try String(contentsOf: url, encoding: .utf8)
    } catch {
      throw AMTProjectError.invalidEvent(
        "\(url.lastPathComponent): \(error.localizedDescription)"
      )
    }
    var records: [NoteEventRecord] = []
    for (index, line) in text.split(whereSeparator: \.isNewline).enumerated() {
      do {
        records.append(
          try JSONDecoder().decode(
            NoteEventRecord.self,
            from: Data(line.utf8)
          )
        )
      } catch {
        throw AMTProjectError.invalidEvent(
          "\(url.lastPathComponent):\(index + 1): \(error.localizedDescription)"
        )
      }
    }
    return records
  }

  private static func resolveProjectPath(
    _ relative: String,
    rootURL: URL
  ) throws -> URL {
    try resolveRelativePath(relative, baseURL: rootURL)
  }

  private static func resolveBundlePath(
    _ relative: String,
    bundleURL: URL
  ) throws -> URL {
    try resolveRelativePath(relative, baseURL: bundleURL)
  }

  private static func resolveRelativePath(
    _ relative: String,
    baseURL: URL
  ) throws -> URL {
    guard !relative.isEmpty,
      !relative.hasPrefix("/"),
      !relative.contains("\\")
    else {
      throw AMTProjectError.unsafePath(relative)
    }
    let components = relative.split(separator: "/", omittingEmptySubsequences: false)
    guard components.allSatisfy({ !$0.isEmpty && $0 != "." && $0 != ".." }) else {
      throw AMTProjectError.unsafePath(relative)
    }
    var candidate = baseURL
    for component in components {
      candidate.appendPathComponent(String(component))
      if FileManager.default.fileExists(atPath: candidate.path) {
        let values = try candidate.resourceValues(forKeys: [.isSymbolicLinkKey])
        if values.isSymbolicLink == true {
          throw AMTProjectError.unsafePath(relative)
        }
      }
    }
    let standardized = candidate.standardizedFileURL
    let basePath = baseURL.standardizedFileURL.path
    guard
      standardized.path == basePath
        || standardized.path.hasPrefix(basePath + "/")
    else {
      throw AMTProjectError.unsafePath(relative)
    }
    return standardized
  }

  private static func verifyFile(
    _ url: URL,
    expectedSHA256: String,
    expectedSize: Int?
  ) throws {
    let values: URLResourceValues
    do {
      values = try url.resourceValues(
        forKeys: [.isRegularFileKey, .isSymbolicLinkKey, .fileSizeKey]
      )
    } catch {
      throw AMTProjectError.missingArtifact(url.path)
    }
    guard values.isRegularFile == true, values.isSymbolicLink != true else {
      throw AMTProjectError.missingArtifact(url.path)
    }
    if let expectedSize, values.fileSize != expectedSize {
      throw AMTProjectError.malformedManifest(
        "\(url.lastPathComponent) 文件大小与 manifest 不一致"
      )
    }
    let observed = try sha256(url)
    guard observed == expectedSHA256 else {
      throw AMTProjectError.malformedManifest(
        "\(url.lastPathComponent) SHA-256 与 manifest 不一致"
      )
    }
  }
}

public enum TrackArrangementBuilder {
  private struct WorkingTrack {
    let id: String
    let label: String
    let role: String
    let instrument: String?
    let notes: [EditorNote]
  }

  public static func derive(
    catalog: ProjectCatalog,
    targetBundleID: String,
    action: TrackArrangementAction
  ) throws -> TrackArrangementResult {
    guard
      let targetChoice = catalog.bundles.first(where: {
        $0.id == targetBundleID && $0.isDefaultEligible
      })
    else {
      throw AMTProjectError.missingCanonicalBundle
    }
    let targetSnapshot = try ProjectLoader.open(
      catalog,
      bundleID: targetBundleID
    )
    var workingTracks = try materializedTracks(
      snapshot: targetSnapshot,
      bundleID: targetBundleID
    )
    let actionDescription: [String: Any]
    let selectedTrackID: String

    switch action {
    case .copy(let sourceBundleID, let sourceTrackID):
      guard sourceBundleID != targetBundleID,
        let sourceChoice = catalog.bundles.first(where: {
          $0.id == sourceBundleID && $0.isDefaultEligible
        }),
        sourceChoice.tracks.contains(where: { $0.id == sourceTrackID })
      else {
        throw AMTProjectError.invalidEvent("请选择另一个产品版本中的有效音轨")
      }
      let sourceSnapshot = try ProjectLoader.open(
        catalog,
        bundleID: sourceBundleID
      )
      let sourceTracks = try materializedTracks(
        snapshot: sourceSnapshot,
        bundleID: sourceBundleID
      )
      guard let source = sourceTracks.first(where: { $0.id == sourceTrackID })
      else {
        throw AMTProjectError.invalidEvent("找不到要复制的来源音轨")
      }
      let copiedID = uniqueTrackID(
        base: "\(source.id)-copy",
        existing: Set(workingTracks.map(\.id))
      )
      let copiedNotes = source.notes.map {
        derivedNote(
          $0,
          trackID: copiedID,
          operation: "copy",
          sourceBundleID: sourceBundleID,
          instrument: $0.instrument
        )
      }
      workingTracks.append(
        WorkingTrack(
          id: copiedID,
          label: "\(source.label)（复制）",
          role: source.role,
          instrument: source.instrument,
          notes: copiedNotes
        )
      )
      selectedTrackID = copiedID
      actionDescription = [
        "action": "copy",
        "source_bundle_id": sourceBundleID,
        "source_track_id": sourceTrackID,
        "result_track_id": copiedID,
      ]

    case .merge(let trackIDs, let instrumentSourceTrackID):
      guard trackIDs.count >= 2,
        trackIDs.contains(instrumentSourceTrackID)
      else {
        throw AMTProjectError.invalidEvent("合并至少需要两条音轨，并指定其中一条的乐器")
      }
      let available = Set(workingTracks.map(\.id))
      guard trackIDs.isSubset(of: available),
        let instrumentSource = workingTracks.first(where: {
          $0.id == instrumentSourceTrackID
        })
      else {
        throw AMTProjectError.invalidEvent("合并音轨或乐器来源不属于当前版本")
      }
      let mergedID = uniqueTrackID(
        base: "merged-\(instrumentSource.instrument ?? "track")",
        existing: available
      )
      let sourceTracks = workingTracks.filter { trackIDs.contains($0.id) }
      let mergedNotes =
        sourceTracks
        .flatMap(\.notes)
        .map {
          derivedNote(
            $0,
            trackID: mergedID,
            operation: "merge",
            sourceBundleID: targetBundleID,
            instrument: instrumentSource.instrument
          )
        }
        .sorted(by: noteComesBefore)
      let insertionIndex =
        workingTracks.indices.first(where: {
          trackIDs.contains(workingTracks[$0].id)
        }) ?? workingTracks.endIndex
      workingTracks.removeAll { trackIDs.contains($0.id) }
      workingTracks.insert(
        WorkingTrack(
          id: mergedID,
          label: "合并音轨 · \(instrumentSource.label)",
          role: instrumentSource.role,
          instrument: instrumentSource.instrument,
          notes: mergedNotes
        ),
        at: min(insertionIndex, workingTracks.endIndex)
      )
      selectedTrackID = mergedID
      actionDescription = [
        "action": "merge",
        "source_track_ids": trackIDs.sorted(),
        "instrument_source_track_id": instrumentSourceTrackID,
        "result_track_id": mergedID,
      ]

    case .delete(let trackID):
      guard workingTracks.count > 1,
        workingTracks.contains(where: { $0.id == trackID })
      else {
        throw AMTProjectError.invalidEvent("不能删除不存在的音轨或版本中的最后一条音轨")
      }
      workingTracks.removeAll { $0.id == trackID }
      guard let replacement = workingTracks.first else {
        throw AMTProjectError.invalidEvent("识别版本至少需要保留一条音轨")
      }
      selectedTrackID = replacement.id
      actionDescription = [
        "action": "delete",
        "source_track_id": trackID,
      ]
    }

    return try commitDerivedBundle(
      catalog: catalog,
      targetChoice: targetChoice,
      targetSnapshot: targetSnapshot,
      workingTracks: workingTracks,
      selectedTrackID: selectedTrackID,
      actionDescription: actionDescription
    )
  }

  public static func copyAcrossProjects(
    sourceCatalog: ProjectCatalog,
    sourceBundleID: String,
    sourceTrackID: String,
    targetCatalog: ProjectCatalog,
    targetBundleID: String
  ) throws -> TrackArrangementResult {
    let sourceRoot =
      sourceCatalog.rootURL.standardizedFileURL.resolvingSymlinksInPath()
    let targetRoot =
      targetCatalog.rootURL.standardizedFileURL.resolvingSymlinksInPath()
    guard sourceRoot.path != targetRoot.path,
      sourceCatalog.manifest.projectID != targetCatalog.manifest.projectID
    else {
      throw AMTProjectError.invalidEvent("跨歌曲复制必须选择另一个独立歌曲项目")
    }
    guard
      let sourceChoice = sourceCatalog.bundles.first(where: {
        $0.id == sourceBundleID && $0.isDefaultEligible
      }),
      sourceChoice.tracks.contains(where: { $0.id == sourceTrackID }),
      let targetChoice = targetCatalog.bundles.first(where: {
        $0.id == targetBundleID && $0.isDefaultEligible
      })
    else {
      throw AMTProjectError.invalidEvent("来源音轨或目标识别版本不可用")
    }
    let sourceSnapshot = try ProjectLoader.open(
      sourceCatalog,
      bundleID: sourceBundleID
    )
    let targetSnapshot = try ProjectLoader.open(
      targetCatalog,
      bundleID: targetBundleID
    )
    let sourceTracks = try materializedTracks(
      snapshot: sourceSnapshot,
      bundleID: sourceBundleID
    )
    guard let source = sourceTracks.first(where: { $0.id == sourceTrackID })
    else {
      throw AMTProjectError.invalidEvent("找不到要复制的来源音轨")
    }
    var workingTracks = try materializedTracks(
      snapshot: targetSnapshot,
      bundleID: targetBundleID
    )
    let copiedID = uniqueTrackID(
      base: "\(source.id)-import",
      existing: Set(workingTracks.map(\.id))
    )
    let copiedNotes = source.notes.map {
      derivedNote(
        $0,
        trackID: copiedID,
        operation: "cross-project-copy",
        sourceBundleID: sourceBundleID,
        sourceProjectID: sourceCatalog.manifest.projectID,
        instrument: $0.instrument
      )
    }
    guard !copiedNotes.isEmpty else {
      throw AMTProjectError.invalidEvent("来源音轨在目标歌曲时间范围内没有可复制的音符")
    }
    workingTracks.append(
      WorkingTrack(
        id: copiedID,
        label:
          "\(source.label)（来自 "
          + "\(sourceCatalog.manifest.title ?? sourceCatalog.manifest.projectID)）",
        role: source.role,
        instrument: source.instrument,
        notes: copiedNotes
      )
    )
    return try commitDerivedBundle(
      catalog: targetCatalog,
      targetChoice: targetChoice,
      targetSnapshot: targetSnapshot,
      workingTracks: workingTracks,
      selectedTrackID: copiedID,
      actionDescription: [
        "action": "copy_from_project",
        "source_project_id": sourceCatalog.manifest.projectID,
        "source_project_title":
          sourceCatalog.manifest.title ?? sourceCatalog.manifest.projectID,
        "source_bundle_id": sourceBundleID,
        "source_track_id": sourceTrackID,
        "result_track_id": copiedID,
        "source_note_count": source.notes.count,
        "imported_note_count": copiedNotes.count,
        "timeline_policy": "source_absolute_seconds_preserved",
      ]
    )
  }

  private static func commitDerivedBundle(
    catalog: ProjectCatalog,
    targetChoice: CanonicalBundleChoice,
    targetSnapshot: ProjectSnapshot,
    workingTracks: [WorkingTrack],
    selectedTrackID: String,
    actionDescription: [String: Any]
  ) throws -> TrackArrangementResult {
    let bundleID = makeBundleID()
    let exportsURL = try checkedExportsDirectory(catalog.rootURL)
    let temporaryURL = exportsURL.appendingPathComponent(
      ".\(bundleID).\(UUID().uuidString).tmp",
      isDirectory: true
    )
    let finalURL = exportsURL.appendingPathComponent(
      bundleID,
      isDirectory: true
    )
    guard !FileManager.default.fileExists(atPath: finalURL.path) else {
      throw AMTProjectError.invalidEvent("自定义版本 ID 冲突，请重试")
    }
    try FileManager.default.createDirectory(
      at: temporaryURL,
      withIntermediateDirectories: false
    )
    do {
      try writeBundle(
        rootURL: catalog.rootURL,
        temporaryURL: temporaryURL,
        finalBundleID: bundleID,
        baseChoice: targetChoice,
        baseSnapshot: targetSnapshot,
        tracks: workingTracks,
        actionDescription: actionDescription
      )
      try FileManager.default.moveItem(at: temporaryURL, to: finalURL)
      do {
        let refreshed = try ProjectLoader.inspect(catalog.rootURL)
        _ = try ProjectLoader.open(refreshed, bundleID: bundleID)
      } catch {
        try? FileManager.default.removeItem(at: finalURL)
        throw error
      }
    } catch {
      try? FileManager.default.removeItem(at: temporaryURL)
      throw error
    }
    return TrackArrangementResult(
      bundleID: bundleID,
      selectedTrackID: selectedTrackID,
      trackCount: workingTracks.count,
      noteCount: workingTracks.reduce(0) { $0 + $1.notes.count }
    )
  }

  private static func materializedTracks(
    snapshot: ProjectSnapshot,
    bundleID: String
  ) throws -> [WorkingTrack] {
    try snapshot.tracks.map { track in
      let editor = try EditorProject(
        snapshot: snapshot,
        bundleID: bundleID,
        selectedTrackID: track.id
      )
      return WorkingTrack(
        id: track.id,
        label: track.label,
        role: track.role,
        instrument: track.instrument,
        notes: editor.notes
      )
    }
  }

  private static func derivedNote(
    _ note: EditorNote,
    trackID: String,
    operation: String,
    sourceBundleID: String,
    sourceProjectID: String? = nil,
    instrument: String?
  ) -> EditorNote {
    var extra = note.extra
    extra["arrangement_source_bundle_id"] = .string(sourceBundleID)
    extra["arrangement_source_track_id"] = .string(note.trackID)
    if let sourceProjectID {
      extra["arrangement_source_project_id"] = .string(sourceProjectID)
    }
    return EditorNote(
      id: "app-\(operation)-\(UUID().uuidString.lowercased())",
      trackID: trackID,
      sourceTrackID: note.sourceTrackID,
      instrument: instrument,
      onsetSec: note.onsetSec,
      offsetSec: note.offsetSec,
      pitchMIDI: note.pitchMIDI,
      velocity: note.velocity,
      confidence: note.confidence,
      isMainMelodyCandidate: note.isMainMelodyCandidate,
      sourceRunID: "amt-studio-track-arrangement",
      sourceModel: "amt-studio/manual-arrangement",
      sourceEventIDs: Set([note.id] + note.sourceEventIDs).sorted(),
      tags: Set(note.tags + ["app-track-\(operation)"]).sorted(),
      extra: extra
    )
  }

  private static func writeBundle(
    rootURL: URL,
    temporaryURL: URL,
    finalBundleID: String,
    baseChoice: CanonicalBundleChoice,
    baseSnapshot: ProjectSnapshot,
    tracks: [WorkingTrack],
    actionDescription: [String: Any]
  ) throws {
    let tracksURL = temporaryURL.appendingPathComponent(
      "tracks",
      isDirectory: true
    )
    try FileManager.default.createDirectory(
      at: tracksURL,
      withIntermediateDirectories: false
    )
    let arrangementManifestURL = temporaryURL.appendingPathComponent(
      "arrangement_manifest.json"
    )
    let arrangementManifest: [String: Any] = [
      "schema_version": 1,
      "artifact_type": "amt-track-arrangement",
      "project_id": baseSnapshot.manifest.projectID,
      "base_bundle_id": baseChoice.id,
      "created_at": ISO8601DateFormatter().string(from: Date()),
      "operation": actionDescription,
      "source_bundle_overwritten": false,
    ]
    try writeJSON(arrangementManifest, to: arrangementManifestURL)
    let arrangementHash = try ProjectLoader.sha256(arrangementManifestURL)

    var canonicalObject = try readJSONObject(
      baseSnapshot.canonicalProjectURL
    )
    var canonicalTracks: [[String: Any]] = []
    var outputRecords: [[String: Any]] = []
    for (index, track) in tracks.enumerated() {
      let fileName =
        String(format: "%02d", index + 1)
        + "-"
        + safeComponent(track.id)
        + ".jsonl"
      let relativeBundlePath = "tracks/\(fileName)"
      let eventsURL = temporaryURL.appendingPathComponent(relativeBundlePath)
      try writeNotes(track.notes, trackID: track.id, to: eventsURL)
      let eventsHash = try ProjectLoader.sha256(eventsURL)
      let projectRelativePath =
        "exports/\(finalBundleID)/\(relativeBundlePath)"
      var trackObject: [String: Any] = [
        "track_id": track.id,
        "label": track.label,
        "role": track.role,
        "event_count": track.notes.count,
        "source_events_path": projectRelativePath,
        "provenance": [
          "source_run_id": "amt-studio-track-arrangement",
          "source_model": "amt-studio/manual-arrangement",
          "run_manifest_sha256": arrangementHash,
          "normalized_artifact_sha256": eventsHash,
        ],
      ]
      trackObject["instrument"] = track.instrument
      canonicalTracks.append(trackObject)
      outputRecords.append(
        try outputRecord(
          path: relativeBundlePath,
          url: eventsURL
        )
      )
    }
    canonicalObject["tracks"] = canonicalTracks
    var canonicalClaims =
      canonicalObject["claims"] as? [String: Any] ?? [:]
    canonicalClaims["app_derived_arrangement"] = true
    canonicalClaims["arrangement_base_bundle_id"] = baseChoice.id
    canonicalClaims["source_bundle_overwritten"] = false
    canonicalObject["claims"] = canonicalClaims
    canonicalObject["exports"] = [:]
    let canonicalURL = temporaryURL.appendingPathComponent(
      "canonical_project.json"
    )
    try writeJSON(canonicalObject, to: canonicalURL)
    outputRecords.insert(
      try outputRecord(
        path: "canonical_project.json",
        url: canonicalURL
      ),
      at: 0
    )
    outputRecords.insert(
      try outputRecord(
        path: "arrangement_manifest.json",
        url: arrangementManifestURL
      ),
      at: 1
    )

    var claims =
      baseChoice.manifest.claims.map { foundationObject($0) }
      ?? [:]
    claims["app_derived_arrangement"] = true
    claims["arrangement_base_bundle_id"] = baseChoice.id
    claims["source_bundle_overwritten"] = false
    let bundleManifest: [String: Any] = [
      "schema_version": 1,
      "artifact_type": "amt-canonical-bundle",
      "bundle_id": finalBundleID,
      "project_id": baseSnapshot.manifest.projectID,
      "canonical_audio_sha256":
        baseSnapshot.manifest.canonicalAudio.sha256,
      "status": "succeeded",
      "outputs": outputRecords,
      "claims": claims,
      "limitations": [
        "This is a user-created arrangement derived from verified bundles.",
        "Copy, merge, and delete operations do not overwrite model outputs.",
        "Merged tracks preserve every source note and do not automatically deduplicate overlaps.",
      ],
    ]
    try writeJSON(
      bundleManifest,
      to: temporaryURL.appendingPathComponent("bundle_manifest.json")
    )
  }

  private static func writeNotes(
    _ notes: [EditorNote],
    trackID: String,
    to url: URL
  ) throws {
    var data = Data()
    for note in notes.sorted(by: noteComesBefore) {
      var object: [String: Any] = [
        "schema_version": 1,
        "event_id": note.id,
        "track_id": trackID,
        "onset_sec": note.onsetSec,
        "offset_sec": note.offsetSec,
        "pitch_midi": note.pitchMIDI,
        "is_main_melody_candidate": note.isMainMelodyCandidate,
        "source_run_id": note.sourceRunID,
        "source_model": note.sourceModel,
        "source_event_ids": note.sourceEventIDs,
        "tags": note.tags,
        "extra": foundationObject(note.extra),
      ]
      object["instrument"] = note.instrument
      object["velocity"] = note.velocity
      object["confidence"] = note.confidence
      let line = try JSONSerialization.data(
        withJSONObject: object,
        options: [.sortedKeys]
      )
      data.append(line)
      data.append(0x0A)
    }
    try data.write(to: url, options: [.atomic])
  }

  private static func checkedExportsDirectory(_ rootURL: URL) throws -> URL {
    let root = rootURL.standardizedFileURL.resolvingSymlinksInPath()
    let exports = root.appendingPathComponent("exports", isDirectory: true)
    let values = try exports.resourceValues(
      forKeys: [.isDirectoryKey, .isSymbolicLinkKey]
    )
    guard values.isDirectory == true, values.isSymbolicLink != true,
      exports.deletingLastPathComponent().path == root.path
    else {
      throw AMTProjectError.unsafePath("exports")
    }
    return exports
  }

  private static func uniqueTrackID(
    base: String,
    existing: Set<String>
  ) -> String {
    let safe = safeComponent(base)
    if !existing.contains(safe) {
      return safe
    }
    var index = 2
    while existing.contains("\(safe)-\(index)") {
      index += 1
    }
    return "\(safe)-\(index)"
  }

  private static func safeComponent(_ value: String) -> String {
    let mapped = value.map {
      $0.isLetter || $0.isNumber || "-._".contains($0) ? $0 : "-"
    }
    let result = String(mapped).trimmingCharacters(in: CharacterSet(charactersIn: ".-"))
    return result.isEmpty ? "track" : String(result.prefix(80))
  }

  private static func makeBundleID() -> String {
    let formatter = DateFormatter()
    formatter.locale = Locale(identifier: "en_US_POSIX")
    formatter.timeZone = TimeZone(secondsFromGMT: 0)
    formatter.dateFormat = "yyyyMMdd'T'HHmmss'Z'"
    return
      "custom-\(formatter.string(from: Date()))-"
      + UUID().uuidString.prefix(8).lowercased()
  }

  private static func outputRecord(
    path: String,
    url: URL
  ) throws -> [String: Any] {
    let size =
      try url.resourceValues(forKeys: [.fileSizeKey]).fileSize
      ?? Int(Data(contentsOf: url).count)
    return [
      "path": path,
      "sha256": try ProjectLoader.sha256(url),
      "size_bytes": size,
    ]
  }

  private static func readJSONObject(_ url: URL) throws -> [String: Any] {
    guard
      let object = try JSONSerialization.jsonObject(
        with: Data(contentsOf: url)
      ) as? [String: Any]
    else {
      throw AMTProjectError.malformedManifest(
        "\(url.lastPathComponent) 不是 JSON 对象"
      )
    }
    return object
  }

  private static func writeJSON(
    _ object: [String: Any],
    to url: URL
  ) throws {
    let data = try JSONSerialization.data(
      withJSONObject: object,
      options: [.prettyPrinted, .sortedKeys]
    )
    try data.write(to: url, options: [.atomic])
  }

  private static func foundationObject(
    _ values: [String: JSONValue]
  ) -> [String: Any] {
    values.mapValues(foundationObject)
  }

  private static func foundationObject(_ value: JSONValue) -> Any {
    switch value {
    case .null: NSNull()
    case .bool(let value): value
    case .number(let value): value
    case .string(let value): value
    case .array(let values): values.map(foundationObject)
    case .object(let values): foundationObject(values)
    }
  }

  private static func noteComesBefore(
    _ first: EditorNote,
    _ second: EditorNote
  ) -> Bool {
    (first.onsetSec, first.pitchMIDI, first.id)
      < (second.onsetSec, second.pitchMIDI, second.id)
  }
}
