import Foundation

public enum AMTProjectError: Error, LocalizedError, Equatable, Sendable {
  case missingManifest
  case malformedManifest(String)
  case missingCanonicalBundle
  case ambiguousCanonicalBundles
  case unsafePath(String)
  case missingArtifact(String)
  case invalidEvent(String)
  case duplicateEventID(String)
  case editSessionMismatch
  case noNotesToExport

  public var errorDescription: String? {
    switch self {
    case .missingManifest:
      "所选文件夹不是 AMT Studio 项目：缺少 manifest.json。"
    case .malformedManifest(let detail):
      "项目文件无法读取：\(detail)"
    case .missingCanonicalBundle:
      "项目还没有 canonical_project.json；可以打开项目，但目前没有可编辑音符。"
    case .ambiguousCanonicalBundles:
      "项目包含多个 canonical bundle，请明确选择一个版本。"
    case .unsafePath(let path):
      "项目引用了目录之外的路径，已拒绝读取：\(path)"
    case .missingArtifact(let path):
      "项目所需文件不存在：\(path)"
    case .invalidEvent(let detail):
      "音符事件无效：\(detail)"
    case .duplicateEventID(let eventID):
      "项目包含重复音符 ID：\(eventID)"
    case .editSessionMismatch:
      "保存的编辑记录不属于当前基础音符版本，未自动套用。"
    case .noNotesToExport:
      "当前没有可以导出的音符。"
    }
  }
}

public struct ProjectManifest: Decodable, Sendable, Equatable {
  public struct AudioRecord: Decodable, Sendable, Equatable {
    public let path: String
    public let sha256: String
  }

  public let schemaVersion: Int
  public let projectID: String
  public let title: String?
  public let canonicalAudio: AudioRecord

  enum CodingKeys: String, CodingKey {
    case schemaVersion = "schema_version"
    case projectID = "project_id"
    case title
    case canonicalAudio = "canonical_audio"
  }
}

public struct CanonicalProject: Decodable, Sendable, Equatable {
  public let schemaVersion: Int
  public let artifactType: String
  public let projectID: String
  public let timelineBasis: String
  public let canonicalAudio: ProjectManifest.AudioRecord
  public let tracks: [CanonicalTrack]
  public let rhythm: RhythmMap

  enum CodingKeys: String, CodingKey {
    case schemaVersion = "schema_version"
    case artifactType = "artifact_type"
    case projectID = "project_id"
    case timelineBasis = "timeline_basis"
    case canonicalAudio = "canonical_audio"
    case tracks
    case rhythm
  }
}

public struct CanonicalTrack: Decodable, Sendable, Equatable, Identifiable {
  public let trackID: String
  public let label: String
  public let role: String
  public let instrument: String?
  public let eventCount: Int
  public let sourceEventsPath: String
  public let provenance: TrackProvenance

  public var id: String { trackID }

  enum CodingKeys: String, CodingKey {
    case trackID = "track_id"
    case label
    case role
    case instrument
    case eventCount = "event_count"
    case sourceEventsPath = "source_events_path"
    case provenance
  }
}

public struct TrackProvenance: Decodable, Sendable, Equatable {
  public let sourceRunID: String
  public let sourceModel: String
  public let runManifestSHA256: String
  public let normalizedArtifactSHA256: String

  enum CodingKeys: String, CodingKey {
    case sourceRunID = "source_run_id"
    case sourceModel = "source_model"
    case runManifestSHA256 = "run_manifest_sha256"
    case normalizedArtifactSHA256 = "normalized_artifact_sha256"
  }
}

public struct RhythmMap: Decodable, Sendable, Equatable {
  public let tempoMap: [TempoPoint]
  public let meterMap: [MeterPoint]

  enum CodingKeys: String, CodingKey {
    case tempoMap = "tempo_map"
    case meterMap = "meter_map"
  }
}

public struct TempoPoint: Codable, Sendable, Equatable {
  public let timeSec: Double
  public let bpm: Double

  public init(timeSec: Double, bpm: Double) {
    self.timeSec = timeSec
    self.bpm = bpm
  }

  enum CodingKeys: String, CodingKey {
    case timeSec = "time_sec"
    case bpm
  }
}

public struct MeterPoint: Codable, Sendable, Equatable {
  public let timeSec: Double
  public let numerator: Int
  public let denominator: Int

  public init(timeSec: Double, numerator: Int, denominator: Int) {
    self.timeSec = timeSec
    self.numerator = numerator
    self.denominator = denominator
  }

  enum CodingKeys: String, CodingKey {
    case timeSec = "time_sec"
    case numerator
    case denominator
  }
}

public enum JSONValue: Codable, Hashable, Sendable {
  case null
  case bool(Bool)
  case number(Double)
  case string(String)
  case array([JSONValue])
  case object([String: JSONValue])

  public init(from decoder: Decoder) throws {
    let container = try decoder.singleValueContainer()
    if container.decodeNil() {
      self = .null
    } else if let value = try? container.decode(Bool.self) {
      self = .bool(value)
    } else if let value = try? container.decode(Double.self) {
      self = .number(value)
    } else if let value = try? container.decode(String.self) {
      self = .string(value)
    } else if let value = try? container.decode([JSONValue].self) {
      self = .array(value)
    } else {
      self = .object(try container.decode([String: JSONValue].self))
    }
  }

  public func encode(to encoder: Encoder) throws {
    var container = encoder.singleValueContainer()
    switch self {
    case .null:
      try container.encodeNil()
    case .bool(let value):
      try container.encode(value)
    case .number(let value):
      try container.encode(value)
    case .string(let value):
      try container.encode(value)
    case .array(let value):
      try container.encode(value)
    case .object(let value):
      try container.encode(value)
    }
  }
}

struct NoteEventRecord: Decodable {
  let schemaVersion: Int
  let eventID: String
  let trackID: String
  let instrument: String?
  let onsetSec: Double
  let offsetSec: Double
  let pitchMIDI: Double
  let quantizedPitchMIDI: Int?
  let velocity: Int?
  let confidence: Double?
  let isMainMelodyCandidate: Bool
  let sourceRunID: String
  let sourceModel: String
  let sourceEventIDs: [String]
  let tags: [String]
  let extra: [String: JSONValue]

  enum CodingKeys: String, CodingKey {
    case schemaVersion = "schema_version"
    case eventID = "event_id"
    case trackID = "track_id"
    case instrument
    case onsetSec = "onset_sec"
    case offsetSec = "offset_sec"
    case pitchMIDI = "pitch_midi"
    case quantizedPitchMIDI = "quantized_pitch_midi"
    case velocity
    case confidence
    case isMainMelodyCandidate = "is_main_melody_candidate"
    case sourceRunID = "source_run_id"
    case sourceModel = "source_model"
    case sourceEventIDs = "source_event_ids"
    case tags
    case extra
  }

  init(from decoder: Decoder) throws {
    let container = try decoder.container(keyedBy: CodingKeys.self)
    schemaVersion = try container.decode(Int.self, forKey: .schemaVersion)
    guard schemaVersion == 1 else {
      throw DecodingError.dataCorruptedError(
        forKey: .schemaVersion,
        in: container,
        debugDescription: "Unsupported note event schema_version"
      )
    }
    eventID = try container.decode(String.self, forKey: .eventID)
    trackID = try container.decode(String.self, forKey: .trackID)
    instrument = try container.decodeIfPresent(
      String.self,
      forKey: .instrument
    )
    onsetSec = try container.decode(Double.self, forKey: .onsetSec)
    offsetSec = try container.decode(Double.self, forKey: .offsetSec)
    pitchMIDI = try container.decode(Double.self, forKey: .pitchMIDI)
    quantizedPitchMIDI = try container.decodeIfPresent(
      Int.self,
      forKey: .quantizedPitchMIDI
    )
    if let quantizedPitchMIDI,
      !(0...127).contains(quantizedPitchMIDI)
    {
      throw DecodingError.dataCorruptedError(
        forKey: .quantizedPitchMIDI,
        in: container,
        debugDescription: "quantized_pitch_midi must be in 0...127"
      )
    }
    velocity = try container.decodeIfPresent(Int.self, forKey: .velocity)
    confidence = try container.decodeIfPresent(
      Double.self,
      forKey: .confidence
    )
    isMainMelodyCandidate =
      try container.decodeIfPresent(
        Bool.self,
        forKey: .isMainMelodyCandidate
      ) ?? false
    sourceRunID = try container.decode(String.self, forKey: .sourceRunID)
    sourceModel = try container.decode(String.self, forKey: .sourceModel)
    sourceEventIDs =
      try container.decodeIfPresent(
        [String].self,
        forKey: .sourceEventIDs
      ) ?? []
    tags = try container.decodeIfPresent([String].self, forKey: .tags) ?? []
    extra =
      try container.decodeIfPresent(
        [String: JSONValue].self,
        forKey: .extra
      ) ?? [:]
  }
}

public struct EditorNote: Codable, Hashable, Sendable, Identifiable {
  public let id: String
  public var trackID: String
  public let sourceTrackID: String
  public var instrument: String?
  public var onsetSec: Double
  public var offsetSec: Double
  public var pitchMIDI: Double
  public var velocity: Int?
  public let confidence: Double?
  public let isMainMelodyCandidate: Bool
  public let sourceRunID: String
  public let sourceModel: String
  public let sourceEventIDs: [String]
  public var tags: [String]
  public let extra: [String: JSONValue]

  public init(
    id: String,
    trackID: String,
    sourceTrackID: String,
    instrument: String?,
    onsetSec: Double,
    offsetSec: Double,
    pitchMIDI: Double,
    velocity: Int?,
    confidence: Double?,
    isMainMelodyCandidate: Bool,
    sourceRunID: String,
    sourceModel: String,
    sourceEventIDs: [String],
    tags: [String],
    extra: [String: JSONValue]
  ) {
    self.id = id
    self.trackID = trackID
    self.sourceTrackID = sourceTrackID
    self.instrument = instrument
    self.onsetSec = onsetSec
    self.offsetSec = offsetSec
    self.pitchMIDI = pitchMIDI
    self.velocity = velocity
    self.confidence = confidence
    self.isMainMelodyCandidate = isMainMelodyCandidate
    self.sourceRunID = sourceRunID
    self.sourceModel = sourceModel
    self.sourceEventIDs = sourceEventIDs
    self.tags = tags
    self.extra = extra
  }

  public func validated() throws -> EditorNote {
    guard !id.isEmpty, !trackID.isEmpty, !sourceRunID.isEmpty, !sourceModel.isEmpty else {
      throw AMTProjectError.invalidEvent("ID、轨道和来源不能为空")
    }
    guard onsetSec.isFinite, onsetSec >= 0 else {
      throw AMTProjectError.invalidEvent("\(id) 的起始时间无效")
    }
    guard offsetSec.isFinite, offsetSec > onsetSec else {
      throw AMTProjectError.invalidEvent("\(id) 的结束时间必须晚于起始时间")
    }
    guard pitchMIDI.isFinite, (0...127).contains(pitchMIDI) else {
      throw AMTProjectError.invalidEvent("\(id) 的 MIDI 音高超出 0...127")
    }
    if let velocity, !(0...127).contains(velocity) {
      throw AMTProjectError.invalidEvent("\(id) 的力度超出 0...127")
    }
    if let confidence, !confidence.isFinite || !(0...1).contains(confidence) {
      throw AMTProjectError.invalidEvent("\(id) 的置信度超出 0...1")
    }
    return self
  }
}

public struct EditorTrack: Codable, Sendable, Equatable, Identifiable {
  public let id: String
  public let label: String
  public let role: String
  public let instrument: String?

  public init(id: String, label: String, role: String, instrument: String?) {
    self.id = id
    self.label = label
    self.role = role
    self.instrument = instrument
  }
}

public struct ProjectSnapshot: Sendable {
  public let rootURL: URL
  public let canonicalProjectURL: URL
  public let audioURL: URL
  public let manifest: ProjectManifest
  public let canonicalProject: CanonicalProject
  public let tracks: [EditorTrack]
  public let notes: [EditorNote]
  public let baseFingerprint: String

  public init(
    rootURL: URL,
    canonicalProjectURL: URL,
    audioURL: URL,
    manifest: ProjectManifest,
    canonicalProject: CanonicalProject,
    tracks: [EditorTrack],
    notes: [EditorNote],
    baseFingerprint: String
  ) {
    self.rootURL = rootURL
    self.canonicalProjectURL = canonicalProjectURL
    self.audioURL = audioURL
    self.manifest = manifest
    self.canonicalProject = canonicalProject
    self.tracks = tracks
    self.notes = notes
    self.baseFingerprint = baseFingerprint
  }
}

public struct ArtifactRecord: Decodable, Sendable, Equatable {
  public let path: String
  public let sha256: String
  public let sizeBytes: Int

  enum CodingKeys: String, CodingKey {
    case path
    case sha256
    case sizeBytes = "size_bytes"
  }
}

public struct BundleManifest: Decodable, Sendable, Equatable {
  public let schemaVersion: Int
  public let artifactType: String
  public let projectID: String
  public let canonicalAudioSHA256: String
  public let status: String
  public let outputs: [ArtifactRecord]
  public let limitations: [String]

  enum CodingKeys: String, CodingKey {
    case schemaVersion = "schema_version"
    case artifactType = "artifact_type"
    case projectID = "project_id"
    case canonicalAudioSHA256 = "canonical_audio_sha256"
    case status
    case outputs
    case limitations
  }
}

public struct CanonicalBundleChoice: Sendable, Equatable, Identifiable {
  public let id: String
  public let directoryURL: URL
  public let canonicalProjectURL: URL
  public let manifest: BundleManifest

  public init(
    id: String,
    directoryURL: URL,
    canonicalProjectURL: URL,
    manifest: BundleManifest
  ) {
    self.id = id
    self.directoryURL = directoryURL
    self.canonicalProjectURL = canonicalProjectURL
    self.manifest = manifest
  }
}
