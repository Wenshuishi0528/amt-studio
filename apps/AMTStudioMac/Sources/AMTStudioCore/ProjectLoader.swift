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
        instrument: $0.instrument
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
      result.append(
        CanonicalBundleChoice(
          id: directoryURL.lastPathComponent,
          directoryURL: directoryURL,
          canonicalProjectURL: canonicalURL,
          manifest: bundle
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
