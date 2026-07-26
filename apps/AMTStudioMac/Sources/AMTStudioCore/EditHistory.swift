import Foundation

public struct EditOperation: Codable, Hashable, Sendable, Identifiable {
  public enum Kind: String, Codable, Sendable {
    case create
    case delete
    case update
    case split
    case merge
  }

  public let id: UUID
  public let parentOperationID: UUID?
  public let createdAt: Date
  public let kind: Kind
  public let beforeEvents: [EditorNote]
  public let afterEvents: [EditorNote]

  public init(
    id: UUID = UUID(),
    parentOperationID: UUID?,
    createdAt: Date = Date(),
    kind: Kind,
    beforeEvents: [EditorNote],
    afterEvents: [EditorNote]
  ) {
    self.id = id
    self.parentOperationID = parentOperationID
    self.createdAt = createdAt
    self.kind = kind
    self.beforeEvents = beforeEvents
    self.afterEvents = afterEvents
  }
}

public struct EditorWorkspace: Codable, Sendable, Equatable {
  public let schemaVersion: Int
  public let contractVersion: String
  public let projectID: String
  public let canonicalBundleID: String
  public let canonicalProjectSHA256: String
  public let selectedTrackID: String
  public let editSessionPath: String
  public let updatedAt: Date

  public init(
    projectID: String,
    canonicalBundleID: String,
    canonicalProjectSHA256: String,
    selectedTrackID: String,
    editSessionPath: String,
    updatedAt: Date = Date()
  ) {
    schemaVersion = 1
    contractVersion = "amt-app-workspace/v1"
    self.projectID = projectID
    self.canonicalBundleID = canonicalBundleID
    self.canonicalProjectSHA256 = canonicalProjectSHA256
    self.selectedTrackID = selectedTrackID
    self.editSessionPath = editSessionPath
    self.updatedAt = updatedAt
  }
}

private struct EditSessionHeader: Codable {
  let schemaVersion: Int
  let contractVersion: String
  let projectID: String
  let baseFingerprint: String
  let selectedTrackID: String
  let headOperationID: UUID?
  let redoOperationIDs: [UUID]
  let operationCount: Int
  let updatedAt: Date
}

public struct EditorProject {
  public static let minimumDuration = 0.02

  public let snapshot: ProjectSnapshot
  public let bundleID: String
  public let selectedTrack: EditorTrack
  public private(set) var operations: [EditOperation]
  public private(set) var headOperationID: UUID?
  public private(set) var redoOperationIDs: [UUID]

  public var canUndo: Bool { headOperationID != nil }
  public var canRedo: Bool { !redoOperationIDs.isEmpty }

  public var notes: [EditorNote] {
    (try? replay()) ?? []
  }

  public func materializedNotes() throws -> [EditorNote] {
    try replay()
  }

  public var sessionDirectoryURL: URL {
    snapshot.rootURL
      .appendingPathComponent("annotations/corrections", isDirectory: true)
      .appendingPathComponent(sessionDirectoryName, isDirectory: true)
  }

  public init(
    snapshot: ProjectSnapshot,
    bundleID: String,
    selectedTrackID: String
  ) throws {
    guard
      let selectedTrack = snapshot.tracks.first(
        where: { $0.id == selectedTrackID }
      )
    else {
      throw AMTProjectError.malformedManifest(
        "找不到候选轨 \(selectedTrackID)"
      )
    }
    self.snapshot = snapshot
    self.bundleID = bundleID
    self.selectedTrack = selectedTrack
    operations = []
    headOperationID = nil
    redoOperationIDs = []
    try loadPersistedSessionIfPresent()
    _ = try replay()
  }

  public mutating func update(_ note: EditorNote) throws {
    let current = try noteForID(note.id)
    let validated = try note.validated()
    guard validated.trackID == selectedTrack.id else {
      throw AMTProjectError.invalidEvent("更新音符不能离开当前候选轨")
    }
    try append(
      kind: .update,
      before: [current],
      after: [validated]
    )
  }

  public mutating func move(
    noteID: String,
    onsetSec: Double,
    pitchMIDI: Double
  ) throws {
    var note = try noteForID(noteID)
    let duration = note.offsetSec - note.onsetSec
    note.onsetSec = max(0, onsetSec)
    note.offsetSec = note.onsetSec + duration
    note.pitchMIDI = min(127, max(0, pitchMIDI))
    try update(note)
  }

  public mutating func resize(
    noteID: String,
    onsetSec: Double? = nil,
    offsetSec: Double? = nil
  ) throws {
    var note = try noteForID(noteID)
    if let onsetSec {
      note.onsetSec = max(0, min(onsetSec, note.offsetSec - Self.minimumDuration))
    }
    if let offsetSec {
      note.offsetSec = max(note.onsetSec + Self.minimumDuration, offsetSec)
    }
    try update(note)
  }

  public mutating func delete(noteID: String) throws {
    try append(
      kind: .delete,
      before: [try noteForID(noteID)],
      after: []
    )
  }

  public mutating func create(_ note: EditorNote) throws {
    guard note.trackID == selectedTrack.id else {
      throw AMTProjectError.invalidEvent(
        "新音符必须属于当前候选轨"
      )
    }
    guard try !materializedNotes().contains(where: { $0.id == note.id }) else {
      throw AMTProjectError.duplicateEventID(note.id)
    }
    try append(
      kind: .create,
      before: [],
      after: [try note.validated()]
    )
  }

  public mutating func split(noteID: String, at timeSec: Double) throws {
    let original = try noteForID(noteID)
    guard timeSec >= original.onsetSec + Self.minimumDuration,
      timeSec <= original.offsetSec - Self.minimumDuration
    else {
      throw AMTProjectError.invalidEvent("切分点离音符边界太近")
    }
    var left = original
    left = EditorNote(
      id: "\(original.id):split-a:\(UUID().uuidString)",
      trackID: original.trackID,
      sourceTrackID: original.sourceTrackID,
      instrument: original.instrument,
      onsetSec: original.onsetSec,
      offsetSec: timeSec,
      pitchMIDI: original.pitchMIDI,
      velocity: original.velocity,
      confidence: original.confidence,
      isMainMelodyCandidate: original.isMainMelodyCandidate,
      sourceRunID: original.sourceRunID,
      sourceModel: original.sourceModel,
      sourceEventIDs: [original.id] + original.sourceEventIDs,
      tags: original.tags + ["app-split"],
      extra: original.extra
    )
    let right = EditorNote(
      id: "\(original.id):split-b:\(UUID().uuidString)",
      trackID: original.trackID,
      sourceTrackID: original.sourceTrackID,
      instrument: original.instrument,
      onsetSec: timeSec,
      offsetSec: original.offsetSec,
      pitchMIDI: original.pitchMIDI,
      velocity: original.velocity,
      confidence: original.confidence,
      isMainMelodyCandidate: original.isMainMelodyCandidate,
      sourceRunID: original.sourceRunID,
      sourceModel: original.sourceModel,
      sourceEventIDs: [original.id] + original.sourceEventIDs,
      tags: original.tags + ["app-split"],
      extra: original.extra
    )
    try append(kind: .split, before: [original], after: [left, right])
  }

  public mutating func undo() throws {
    guard let headOperationID,
      let head = operations.first(where: { $0.id == headOperationID })
    else {
      return
    }
    redoOperationIDs.append(head.id)
    self.headOperationID = head.parentOperationID
    _ = try replay()
  }

  public mutating func redo() throws {
    guard let operationID = redoOperationIDs.popLast(),
      let operation = operations.first(where: { $0.id == operationID }),
      operation.parentOperationID == headOperationID
    else {
      return
    }
    headOperationID = operation.id
    _ = try replay()
  }

  public mutating func save() throws {
    let currentNotes = try materializedNotes()
    let safeSessionDirectoryURL = try checkedProjectDirectory(
      rootURL: snapshot.rootURL,
      components: [
        "annotations",
        "corrections",
        sessionDirectoryName,
      ],
      create: true
    )
    let encoder = JSONEncoder()
    encoder.outputFormatting = [.sortedKeys]
    encoder.dateEncodingStrategy = .iso8601

    let operationURL = safeSessionDirectoryURL.appendingPathComponent(
      "operations.jsonl"
    )
    try checkProjectFile(
      operationURL,
      rootURL: snapshot.rootURL,
      requireExisting: false
    )
    let encodedOperations =
      try operations
      .map { try encoder.encode($0) + Data([0x0A]) }
      .reduce(into: Data()) { $0.append($1) }
    try writeAtomically(encodedOperations, to: operationURL)

    let header = EditSessionHeader(
      schemaVersion: 1,
      contractVersion: "amt-note-edit-session/v1",
      projectID: snapshot.manifest.projectID,
      baseFingerprint: snapshot.baseFingerprint,
      selectedTrackID: selectedTrack.id,
      headOperationID: headOperationID,
      redoOperationIDs: redoOperationIDs,
      operationCount: operations.count,
      updatedAt: Date()
    )
    let materialized =
      try currentNotes
      .sorted(by: noteOrdering)
      .map { try encoder.encode($0) + Data([0x0A]) }
      .reduce(into: Data()) { $0.append($1) }
    let currentEventsURL = safeSessionDirectoryURL.appendingPathComponent(
      "current_events.jsonl"
    )
    try checkProjectFile(
      currentEventsURL,
      rootURL: snapshot.rootURL,
      requireExisting: false
    )
    try writeAtomically(
      materialized,
      to: currentEventsURL
    )
    let sessionURL = safeSessionDirectoryURL.appendingPathComponent(
      "session.json"
    )
    try checkProjectFile(
      sessionURL,
      rootURL: snapshot.rootURL,
      requireExisting: false
    )
    try writeAtomically(
      encoder.encode(header),
      to: sessionURL
    )
    let workspace = EditorWorkspace(
      projectID: snapshot.manifest.projectID,
      canonicalBundleID: bundleID,
      canonicalProjectSHA256: try ProjectLoader.sha256(
        snapshot.canonicalProjectURL
      ),
      selectedTrackID: selectedTrack.id,
      editSessionPath: relativePath(
        safeSessionDirectoryURL,
        from: snapshot.rootURL
      ) + "/session.json"
    )
    let appDirectoryURL = try checkedProjectDirectory(
      rootURL: snapshot.rootURL,
      components: ["app"],
      create: true
    )
    let workspaceURL = appDirectoryURL.appendingPathComponent(
      "workspace.json"
    )
    try checkProjectFile(
      workspaceURL,
      rootURL: snapshot.rootURL,
      requireExisting: false
    )
    try writeAtomically(
      encoder.encode(workspace),
      to: workspaceURL
    )
  }

  public static func loadWorkspace(projectURL: URL) throws -> EditorWorkspace? {
    let rootURL = projectURL.standardizedFileURL.resolvingSymlinksInPath()
    let appDirectoryURL = try checkedProjectDirectory(
      rootURL: rootURL,
      components: ["app"],
      create: false
    )
    let url = appDirectoryURL.appendingPathComponent("workspace.json")
    guard FileManager.default.fileExists(atPath: url.path) else {
      return nil
    }
    try checkProjectFile(url, rootURL: rootURL, requireExisting: true)
    let decoder = JSONDecoder()
    decoder.dateDecodingStrategy = .iso8601
    let workspace = try decoder.decode(
      EditorWorkspace.self,
      from: Data(contentsOf: url)
    )
    guard workspace.schemaVersion == 1,
      workspace.contractVersion == "amt-app-workspace/v1"
    else {
      throw AMTProjectError.malformedManifest("不支持的 app workspace")
    }
    return workspace
  }

  private var sessionDirectoryName: String {
    let raw = "amt-studio-\(bundleID)-\(selectedTrack.id)"
    return raw.map {
      $0.isLetter || $0.isNumber || "-._".contains($0) ? $0 : "-"
    }.reduce(into: "") { $0.append($1) }
  }

  private var baseNotes: [EditorNote] {
    snapshot.notes.filter { $0.trackID == selectedTrack.id }
  }

  private mutating func append(
    kind: EditOperation.Kind,
    before: [EditorNote],
    after: [EditorNote]
  ) throws {
    for note in after {
      _ = try note.validated()
    }
    let current = Dictionary(
      uniqueKeysWithValues: try materializedNotes().map { ($0.id, $0) }
    )
    for note in before where current[note.id] != note {
      throw AMTProjectError.invalidEvent(
        "编辑基线已变化，请重新选择音符"
      )
    }
    let operation = EditOperation(
      parentOperationID: headOperationID,
      kind: kind,
      beforeEvents: before,
      afterEvents: after
    )
    operations.append(operation)
    headOperationID = operation.id
    redoOperationIDs = []
    _ = try replay()
  }

  private func noteForID(_ id: String) throws -> EditorNote {
    guard let note = try materializedNotes().first(where: { $0.id == id }) else {
      throw AMTProjectError.invalidEvent("找不到音符 \(id)")
    }
    return note
  }

  private func replay() throws -> [EditorNote] {
    var chain: [EditOperation] = []
    var cursor = headOperationID
    var visited = Set<UUID>()
    while let operationID = cursor {
      guard visited.insert(operationID).inserted,
        let operation = operations.first(where: { $0.id == operationID })
      else {
        throw AMTProjectError.malformedManifest("编辑历史包含断链或循环")
      }
      chain.append(operation)
      cursor = operation.parentOperationID
    }
    var current = Dictionary(uniqueKeysWithValues: baseNotes.map { ($0.id, $0) })
    for operation in chain.reversed() {
      for note in operation.beforeEvents {
        guard current.removeValue(forKey: note.id) == note else {
          throw AMTProjectError.invalidEvent(
            "操作 \(operation.id) 的 before_events 不匹配"
          )
        }
      }
      for note in operation.afterEvents {
        guard current[note.id] == nil else {
          throw AMTProjectError.duplicateEventID(note.id)
        }
        current[note.id] = try note.validated()
      }
    }
    return current.values.sorted(by: noteOrdering)
  }

  private mutating func loadPersistedSessionIfPresent() throws {
    let safeSessionDirectoryURL = try checkedProjectDirectory(
      rootURL: snapshot.rootURL,
      components: [
        "annotations",
        "corrections",
        sessionDirectoryName,
      ],
      create: false
    )
    let headerURL = safeSessionDirectoryURL.appendingPathComponent(
      "session.json"
    )
    let operationsURL = safeSessionDirectoryURL.appendingPathComponent(
      "operations.jsonl"
    )
    guard FileManager.default.fileExists(atPath: headerURL.path) else {
      return
    }
    try checkProjectFile(
      headerURL,
      rootURL: snapshot.rootURL,
      requireExisting: true
    )
    let decoder = JSONDecoder()
    decoder.dateDecodingStrategy = .iso8601
    let header = try decoder.decode(
      EditSessionHeader.self,
      from: Data(contentsOf: headerURL)
    )
    guard header.schemaVersion == 1,
      header.contractVersion == "amt-note-edit-session/v1",
      header.projectID == snapshot.manifest.projectID,
      header.baseFingerprint == snapshot.baseFingerprint,
      header.selectedTrackID == selectedTrack.id
    else {
      throw AMTProjectError.editSessionMismatch
    }
    var loaded: [EditOperation] = []
    if FileManager.default.fileExists(atPath: operationsURL.path) {
      try checkProjectFile(
        operationsURL,
        rootURL: snapshot.rootURL,
        requireExisting: true
      )
      let text = try String(contentsOf: operationsURL, encoding: .utf8)
      for (index, line) in text.split(whereSeparator: \.isNewline).enumerated() {
        do {
          loaded.append(
            try decoder.decode(
              EditOperation.self,
              from: Data(line.utf8)
            )
          )
        } catch {
          throw AMTProjectError.malformedManifest(
            "operations.jsonl:\(index + 1): \(error.localizedDescription)"
          )
        }
      }
    }
    guard loaded.count >= header.operationCount,
      Set(loaded.map(\.id)).count == loaded.count
    else {
      throw AMTProjectError.malformedManifest("编辑操作数量或 ID 无效")
    }
    operations = loaded
    headOperationID = header.headOperationID
    redoOperationIDs = header.redoOperationIDs
  }
}

private func noteOrdering(_ lhs: EditorNote, _ rhs: EditorNote) -> Bool {
  (lhs.onsetSec, lhs.pitchMIDI, lhs.id) < (rhs.onsetSec, rhs.pitchMIDI, rhs.id)
}

private func writeAtomically(_ data: Data, to url: URL) throws {
  try data.write(to: url, options: [.atomic])
}

private func checkedProjectDirectory(
  rootURL: URL,
  components: [String],
  create: Bool
) throws -> URL {
  let fileManager = FileManager.default
  let rootURL = rootURL.standardizedFileURL.resolvingSymlinksInPath()
  var currentURL = rootURL
  for (index, component) in components.enumerated() {
    guard !component.isEmpty,
      component != ".",
      component != "..",
      !component.contains("/"),
      !component.contains("\\")
    else {
      throw AMTProjectError.unsafePath(components.joined(separator: "/"))
    }
    let candidateURL = currentURL.appendingPathComponent(
      component,
      isDirectory: true
    )
    if isSymbolicLink(candidateURL) {
      throw AMTProjectError.unsafePath(
        components.prefix(index + 1).joined(separator: "/")
      )
    }
    var isDirectory: ObjCBool = false
    if fileManager.fileExists(
      atPath: candidateURL.path,
      isDirectory: &isDirectory
    ) {
      guard isDirectory.boolValue else {
        throw AMTProjectError.unsafePath(
          components.prefix(index + 1).joined(separator: "/")
        )
      }
    } else if create {
      try fileManager.createDirectory(
        at: candidateURL,
        withIntermediateDirectories: false
      )
    } else {
      return components.dropFirst(index + 1).reduce(candidateURL) {
        $0.appendingPathComponent(String($1), isDirectory: true)
      }
    }
    currentURL = candidateURL
  }
  return currentURL
}

private func checkProjectFile(
  _ url: URL,
  rootURL: URL,
  requireExisting: Bool
) throws {
  let rootPath = rootURL.standardizedFileURL.resolvingSymlinksInPath().path
  let path = url.standardizedFileURL.path
  guard path.hasPrefix(rootPath + "/"), !isSymbolicLink(url) else {
    throw AMTProjectError.unsafePath(path)
  }
  var isDirectory: ObjCBool = false
  let exists = FileManager.default.fileExists(
    atPath: path,
    isDirectory: &isDirectory
  )
  if requireExisting, !exists {
    throw AMTProjectError.missingArtifact(path)
  }
  if exists {
    let values = try url.resourceValues(forKeys: [.isRegularFileKey])
    guard !isDirectory.boolValue, values.isRegularFile == true else {
      throw AMTProjectError.unsafePath(path)
    }
  }
}

private func isSymbolicLink(_ url: URL) -> Bool {
  (try? FileManager.default.destinationOfSymbolicLink(atPath: url.path))
    != nil
}

private func relativePath(_ url: URL, from rootURL: URL) -> String {
  let root = rootURL.standardizedFileURL.path
  let path = url.standardizedFileURL.path
  guard path.hasPrefix(root + "/") else {
    return url.lastPathComponent
  }
  return String(path.dropFirst(root.count + 1))
}
