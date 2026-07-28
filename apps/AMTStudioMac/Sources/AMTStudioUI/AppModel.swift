import AppKit
import AVFoundation
import Foundation

#if canImport(AMTStudioCore)
  import AMTStudioCore
#endif

public enum MIDIPlaybackMode: String, CaseIterable, Identifiable, Sendable {
  case currentTrack
  case mix

  public var id: String { rawValue }

  public var label: String {
    switch self {
    case .currentTrack: "当前音轨"
    case .mix: "合奏"
    }
  }
}

public enum HyakConnectionState: String, Sendable {
  case unknown
  case checking
  case connected
  case loginRequired
}

public enum ComputeMode: String, CaseIterable, Codable, Identifiable, Sendable {
  case hyak
  case localGPU
  case localCPU

  public var id: String { rawValue }

  public var label: String {
    switch self {
    case .hyak: "Hyak GPU"
    case .localGPU: "本机 GPU"
    case .localCPU: "本机 CPU"
    }
  }

  public var detail: String {
    switch self {
    case .hyak:
      "默认。提交前自动比较兼容 GPU 的调度时间，Mac 只负责上传、状态和结果。"
    case .localGPU:
      "使用 Apple Metal/MPS；会占用统一内存并可能影响前台软件。"
    case .localCPU:
      "使用本机处理器并降低后台优先级；通常最慢，但不需要 GPU。"
    }
  }

  public var icon: String {
    switch self {
    case .hyak: "network"
    case .localGPU: "gauge.with.dots.needle.67percent"
    case .localCPU: "cpu"
    }
  }

  var localDevice: String? {
    switch self {
    case .hyak: nil
    case .localGPU: "mps"
    case .localCPU: "cpu"
    }
  }

  static func resolve(backend: String?, localDevice: String?) -> ComputeMode {
    guard backend == "local" else { return .hyak }
    return localDevice == "cpu" ? .localCPU : .localGPU
  }
}

public enum RecognitionMode: String, CaseIterable, Codable, Identifiable, Sendable {
  case multitrack
  case gameVocal = "game_vocal"

  public var id: String { rawValue }

  public var label: String {
    switch self {
    case .multitrack: "完整多轨（MuScriptor）"
    case .gameVocal: "主唱旋律单轨（GAME）"
    }
  }

  public var detail: String {
    switch self {
    case .multitrack:
      "默认。识别 voice、伴奏、贝斯和鼓等多条音轨，并自动检查 voice 长空缺。"
    case .gameVocal:
      "Hyak 先分离人声，再由官方 GAME large（高容量版）生成一条主唱旋律；不识别完整伴奏，也不保证纯音乐段有旋律。"
    }
  }

  public var requiresHyak: Bool {
    self == .gameVocal
  }
}

public struct MelodyGap: Sendable, Equatable, Identifiable {
  public let startSec: Double
  public let endSec: Double
  public let otherTrackCount: Int
  public let otherNoteCount: Int

  public var id: String {
    "\(startSec)-\(endSec)"
  }

  public var duration: Double {
    endSec - startSec
  }
}

enum MelodyTrackSelector {
  private static let variantPriority = [
    "voice_enhanced",
    "voice_auto_enhanced",
    "voice_raw",
    "voice_gap_candidate",
    "gap_monophonic_candidate",
    "gap_accompaniment_filtered",
    "gap_raw_candidate",
  ]

  static func preferred(in tracks: [EditorTrack]) -> EditorTrack? {
    for id in variantPriority {
      if let track = tracks.first(where: { $0.id == id }) {
        return track
      }
    }
    return tracks.first {
      $0.instrument?.lowercased() == "voice"
    }
  }

  static func resolveExclusiveVariant(
    from trackIDs: Set<String>,
    tracks: [EditorTrack],
    selectedTrackID: String?
  ) -> Set<String> {
    let availableVariants = Set(
      tracks.lazy.map(\.id).filter(variantPriority.contains)
    )
    let includedVariants = trackIDs.intersection(availableVariants)
    let selectedVariant = selectedTrackID.flatMap {
      availableVariants.contains($0) ? $0 : nil
    }
    if let selectedVariant {
      var resolved = trackIDs.subtracting(availableVariants)
      if includedVariants.contains(selectedVariant) {
        resolved.insert(selectedVariant)
      }
      return resolved
    }
    guard includedVariants.count > 1 else { return trackIDs }

    let chosen =
      variantPriority.first(where: includedVariants.contains)
    var resolved = trackIDs.subtracting(availableVariants)
    if let chosen {
      resolved.insert(chosen)
    }
    return resolved
  }

  static func displayLabel(for track: EditorTrack) -> String {
    switch track.id {
    case "voice_enhanced":
      "增强主唱（原始 + 已审核补漏）"
    case "voice_auto_enhanced":
      "自动增强主旋律（Beta）"
    case "voice_raw":
      "原始 voice"
    case "voice_gap_candidate":
      "补漏候选"
    case "gap_raw_candidate":
      "补漏 1/3 · 原始生成"
    case "gap_accompaniment_filtered":
      "补漏 2/3 · 伴奏过滤后"
    case "gap_monophonic_candidate":
      "补漏 3/3 · 单旋律约束后"
    default:
      track.instrument?.lowercased() == "voice"
        ? "voice 主唱候选"
        : track.label
    }
  }

  static func productTracks(from tracks: [EditorTrack]) -> [EditorTrack] {
    let hasEnhanced = tracks.contains {
      ["voice_enhanced", "voice_auto_enhanced"].contains($0.id)
    }
    return tracks.filter { track in
      guard track.role != "diagnostic_candidate" else { return false }
      if hasEnhanced,
        ["voice_raw", "voice_gap_candidate"].contains(track.id)
      {
        return false
      }
      return ![
        "gap_raw_candidate",
        "gap_accompaniment_filtered",
        "gap_monophonic_candidate",
      ].contains(track.id)
    }
  }
}

public struct LocalProjectItem: Sendable, Equatable, Identifiable {
  public let projectID: String
  public let title: String
  public let url: URL
  public let modifiedAt: Date
  public let hasResults: Bool
  public let jobState: String?
  public let durationSeconds: Double?
  public let submittedAt: Date?
  public let pipelineStage: String?
  public let taskKind: String?
  public let gpuType: String?
  public let estimatedWaitSeconds: Int?

  public init(
    projectID: String,
    title: String,
    url: URL,
    modifiedAt: Date,
    hasResults: Bool,
    jobState: String?,
    durationSeconds: Double? = nil,
    submittedAt: Date? = nil,
    pipelineStage: String? = nil,
    taskKind: String? = nil,
    gpuType: String? = nil,
    estimatedWaitSeconds: Int? = nil
  ) {
    self.projectID = projectID
    self.title = title
    self.url = url
    self.modifiedAt = modifiedAt
    self.hasResults = hasResults
    self.jobState = jobState
    self.durationSeconds = durationSeconds
    self.submittedAt = submittedAt
    self.pipelineStage = pipelineStage
    self.taskKind = taskKind
    self.gpuType = gpuType
    self.estimatedWaitSeconds = estimatedWaitSeconds
  }

  public var id: String {
    url.path
  }

  public var stateLabel: String {
    if hasFailedJob {
      return "任务失败"
    }
    return switch jobState {
    case "RUNNING": "识别中"
    case "PENDING", "CONFIGURING": "排队中"
    case "COMPLETING": "正在收尾"
    case "COMPLETED": hasResults ? "可打开" : "正在取回"
    case nil: hasResults ? "可打开" : "尚无结果"
    default: "任务状态待确认"
    }
  }

  public var hasActiveJob: Bool {
    guard let jobState else { return false }
    return !Self.terminalStates.contains(jobState)
  }

  public var hasFailedJob: Bool {
    guard let jobState else { return false }
    return Self.terminalFailureStates.contains(jobState)
  }

  public var canMoveToTrash: Bool {
    !hasActiveJob
  }

  public var canResumeTimeout: Bool {
    jobState == "TIMEOUT"
  }

  public func elapsedSeconds(at date: Date) -> TimeInterval? {
    guard hasActiveJob, let submittedAt else { return nil }
    return max(0, date.timeIntervalSince(submittedAt))
  }

  public func completionEstimate(at date: Date) -> TaskCompletionEstimate? {
    guard hasActiveJob else { return nil }
    return TaskCompletionEstimator.estimate(
      submittedAt: submittedAt,
      now: date,
      audioDurationSeconds: durationSeconds,
      taskKind: taskKind,
      gpuType: gpuType,
      slurmState: jobState,
      pipelineStage: pipelineStage,
      estimatedWaitSeconds: estimatedWaitSeconds
    )
  }

  fileprivate static let terminalFailureStates: Set<String> = [
    "FAILED",
    "CANCELLED",
    "TIMEOUT",
    "OUT_OF_MEMORY",
    "NODE_FAIL",
    "PREEMPTED",
    "BOOT_FAIL",
    "DEADLINE",
  ]

  fileprivate static let terminalStates =
    terminalFailureStates.union(["COMPLETED"])
}

public struct TaskCompletionEstimate: Sendable, Equatable {
  public let earliest: Date
  public let latest: Date
}

public enum TaskCompletionEstimator {
  public static func estimate(
    submittedAt: Date?,
    now: Date,
    audioDurationSeconds: Double?,
    taskKind: String?,
    gpuType: String?,
    slurmState: String?,
    pipelineStage: String?,
    estimatedWaitSeconds: Int?
  ) -> TaskCompletionEstimate {
    let audioMinutes = max(1, (audioDurationSeconds ?? 240) / 60)
    let baseMinutes: Double =
      switch taskKind {
      case "game_vocal_transcription":
        max(20, 15 + audioMinutes * 7)
      case "targeted_gap_recovery":
        max(12, 8 + audioMinutes * 2)
      default:
        max(20, 12 + audioMinutes * 6)
      }
    let gpuMultiplier: Double =
      switch gpuType?.lowercased() {
      case "a100": 0.75
      case "l40s": 0.85
      case "a40": 1.15
      default: 1
      }
    let expectedProcessing = baseMinutes * gpuMultiplier * 60
    let wait = TimeInterval(max(0, estimatedWaitSeconds ?? 0))

    let remaining: TimeInterval
    if ["PENDING", "CONFIGURING"].contains(slurmState ?? "") {
      let estimatedStart = (submittedAt ?? now).addingTimeInterval(wait)
      remaining =
        max(0, estimatedStart.timeIntervalSince(now))
        + expectedProcessing
    } else {
      let estimatedStart = (submittedAt ?? now).addingTimeInterval(wait)
      let observedProcessing = max(0, now.timeIntervalSince(estimatedStart))
      let progress = stageProgress(pipelineStage)
      let stageAdjustedTotal =
        progress > 0 ? observedProcessing / progress : expectedProcessing
      let expectedTotal = max(expectedProcessing, stageAdjustedTotal)
      remaining = max(minimumRemaining(pipelineStage), expectedTotal - observedProcessing)
    }

    let earliestRemaining = max(60, remaining * 0.75)
    let latestRemaining = max(earliestRemaining + 5 * 60, remaining * 1.35)
    return TaskCompletionEstimate(
      earliest: now.addingTimeInterval(earliestRemaining),
      latest: now.addingTimeInterval(latestRemaining)
    )
  }

  private static func stageProgress(_ stage: String?) -> Double {
    switch stage {
    case "source_separation": 0.25
    case "game_vocal_transcription": 0.55
    case "full_transcription": 0.4
    case "rhythm_analysis": 0.65
    case "gap_planning": 0.72
    case "automatic_gap_recovery": 0.82
    case "targeted_gap_recovery": 0.7
    case "packaging": 0.95
    default: 0.05
    }
  }

  private static func minimumRemaining(_ stage: String?) -> TimeInterval {
    switch stage {
    case "packaging": 2 * 60
    case "gap_planning", "rhythm_analysis": 5 * 60
    default: 8 * 60
    }
  }
}

public enum HyakWallTimePolicy {
  public static let manualConfirmationThresholdSeconds = 21 * 60.0

  public static func automaticHours(
    durationSeconds: Double,
    configuredMinimum: Int = 1
  ) -> Int? {
    guard durationSeconds.isFinite, durationSeconds >= 0 else {
      return max(1, min(24, configuredMinimum))
    }
    guard durationSeconds <= manualConfirmationThresholdSeconds else {
      return nil
    }
    let durationMinimum: Int
    if durationSeconds > 14 * 60 {
      durationMinimum = 3
    } else if durationSeconds > 7 * 60 {
      durationMinimum = 2
    } else {
      durationMinimum = 1
    }
    return max(durationMinimum, max(1, min(24, configuredMinimum)))
  }

  public static func suggestedManualHours(
    durationSeconds: Double?,
    configuredMinimum: Int
  ) -> Int {
    guard let durationSeconds, durationSeconds.isFinite, durationSeconds > 0
    else {
      return max(1, min(24, configuredMinimum))
    }
    let durationMinimum = Int(ceil(durationSeconds / (7 * 60)))
    return min(24, max(durationMinimum, configuredMinimum, 1))
  }
}

public struct HyakTimeConfirmationRequest: Identifiable, Sendable, Equatable {
  public let id = UUID()
  public let title: String
  public let durationSeconds: Double
  fileprivate let audioURL: URL
  fileprivate let computeMode: ComputeMode
  fileprivate let recognitionMode: RecognitionMode
  fileprivate let bookmarkData: Data?
}

public enum SongQueueState: String, Codable, Equatable, Sendable {
  case waiting
  case submitting
  case failed

  public var label: String {
    switch self {
    case .waiting: "等待提交"
    case .submitting: "正在提交"
    case .failed: "提交失败，可重试"
    }
  }
}

public struct SongQueueItem: Codable, Sendable, Equatable, Identifiable {
  public let id: UUID
  public let title: String
  public let audioURL: URL
  public let computeMode: ComputeMode
  public let recognitionMode: RecognitionMode
  public let hyakTimeLimitHours: Int
  public fileprivate(set) var state: SongQueueState
  public fileprivate(set) var failureMessage: String?
  fileprivate let bookmarkData: Data?

  init(
    id: UUID,
    title: String,
    audioURL: URL,
    computeMode: ComputeMode,
    recognitionMode: RecognitionMode,
    hyakTimeLimitHours: Int,
    state: SongQueueState,
    failureMessage: String?,
    bookmarkData: Data?
  ) {
    self.id = id
    self.title = title
    self.audioURL = audioURL
    self.computeMode = computeMode
    self.recognitionMode = recognitionMode
    self.hyakTimeLimitHours = hyakTimeLimitHours
    self.state = state
    self.failureMessage = failureMessage
    self.bookmarkData = bookmarkData
  }

  public var configurationLabel: String {
    let base =
      "\(recognitionMode == .multitrack ? "完整多轨" : "GAME 主唱") · \(computeMode.label)"
    return computeMode == .hyak ? "\(base) · \(hyakTimeLimitHours) 小时" : base
  }

  fileprivate func resolvedAudioURL() -> URL {
    guard let bookmarkData else { return audioURL }
    var isStale = false
    return
      (try? URL(
        resolvingBookmarkData: bookmarkData,
        options: [.withSecurityScope],
        relativeTo: nil,
        bookmarkDataIsStale: &isStale
      )) ?? audioURL
  }
}

enum SongQueuePolicy {
  static func canSubmit(
    _ item: SongQueueItem,
    hasActiveProjectTask: Bool
  ) -> Bool {
    item.computeMode == .hyak || !hasActiveProjectTask
  }
}

public enum TrailingCleanupKind: Sendable, Equatable {
  case sustain
  case percussionRepeats
}

public struct TrailingCleanupSummary: Sendable, Equatable {
  public let kind: TrailingCleanupKind
  public let groupCount: Int
  public let fragmentCount: Int

  public var badgeLabel: String {
    switch kind {
    case .sustain: "连续音碎片 \(fragmentCount) → \(groupCount)"
    case .percussionRepeats: "尾部重复打击 \(fragmentCount)"
    }
  }
}

@MainActor
public final class AppModel: ObservableObject {
  @Published public private(set) var catalog: ProjectCatalog?
  @Published public private(set) var snapshot: ProjectSnapshot?
  @Published public private(set) var editor: EditorProject?
  @Published public var selectedNoteID: String?
  @Published public var reviewConfidenceThreshold = 0.5
  @Published public var errorMessage: String?
  @Published public var statusMessage = "请选择一个已有 AMT Studio 项目"
  @Published public private(set) var betaJobID: String?
  @Published public private(set) var betaSlurmState: String?
  @Published public private(set) var betaPipelineStage: String?
  @Published public private(set) var betaTaskKind: String?
  @Published public private(set) var betaGPUType: String?
  @Published public private(set) var betaPartition: String?
  @Published public private(set) var betaGPUPreemptible = false
  @Published public private(set) var betaGPUSelectionReason: String?
  @Published public private(set) var betaGPUEstimatedWaitSeconds: Int?
  @Published public private(set) var betaProjectURL: URL?
  @Published public private(set) var isBetaBusy = false
  @Published public private(set) var isShowingJobProgress = false
  @Published public private(set) var hyakConnectionState: HyakConnectionState = .unknown
  @Published public private(set) var midiPlaybackMode: MIDIPlaybackMode = .mix
  @Published public private(set) var mutedTrackIDs = Set<String>()
  @Published public private(set) var soloTrackIDs = Set<String>()
  @Published public private(set) var trackVolumes: [String: Double] = [:]
  @Published public private(set) var midiMasterVolume = 1.0
  @Published public private(set) var libraryProjects: [LocalProjectItem] = []
  @Published public private(set) var deletingProjectIDs = Set<String>()
  @Published public private(set) var isLoadingProject = false
  @Published public private(set) var isRefreshingLibrary = false
  @Published public private(set) var isLoadingSelection = false
  @Published public private(set) var melodyGaps: [MelodyGap] = []
  @Published public private(set) var selectedGapIDs = Set<String>()
  @Published public private(set) var appearanceMode: AMTAppearanceMode =
    .precision
  @Published public private(set) var computeMode: ComputeMode = .hyak
  @Published public private(set) var recognitionMode: RecognitionMode =
    .multitrack
  @Published public private(set) var hyakTimeLimitHours = 1
  @Published public private(set) var activeComputeMode: ComputeMode?
  @Published public private(set) var localReadinessMessage = "尚未检查本机环境"
  @Published public private(set) var isCheckingLocalCompute = false
  @Published public private(set) var trailingCleanupSummaries: [String: TrailingCleanupSummary] =
    [:]
  @Published public private(set) var lastSavedAt: Date?
  @Published public private(set) var isManagingTracks = false
  @Published public private(set) var songQueue: [SongQueueItem] = []
  @Published public private(set) var hyakTimeConfirmation:
    HyakTimeConfirmationRequest?
  @Published public private(set) var hyakGPUCapacity: [HyakGPUCapacity] = []
  @Published public private(set) var hyakCapacityRunningJobs = 0
  @Published public private(set) var hyakCapacityPendingJobs = 0
  @Published public private(set) var hyakCapacityOtherJobs = 0
  @Published public private(set) var hyakCapacityCheckedAt: Date?
  @Published public private(set) var isCheckingHyakCapacity = false
  @Published public private(set) var hyakCapacityMessage =
    "尚未检查 Hyak 资源"

  public let transport = AudioTransport()

  private let defaults: UserDefaults
  private let persistRecentProject: Bool
  private let recentProjectKey = "AMTStudio.recentProjectPath"
  private let activeBetaProjectKey = "AMTStudio.activeBetaProjectPath"
  private let activeBetaProjectsKey = "AMTStudio.activeBetaProjectPaths.v1"
  private let originalVolumeKey = "AMTStudio.originalVolume"
  private let midiMasterVolumeKey = "AMTStudio.midiMasterVolume"
  private let projectBookmarksKey = "AMTStudio.projectBookmarks"
  private let appearanceModeKey = "AMTStudio.appearanceMode"
  private let computeModeKey = "AMTStudio.computeMode"
  private let recognitionModeKey = "AMTStudio.recognitionMode"
  private let hyakTimeLimitHoursKey = "AMTStudio.hyakTimeLimitHours"
  private let songQueueKey = "AMTStudio.songQueue.v1"
  private var pendingInitialProjectURL: URL?
  private var betaMonitor: Task<Void, Never>?
  private var connectionMonitor: Task<Void, Never>?
  private var midiPreviewRefresh: Task<Void, Never>?
  private var midiPreviewGeneration = UUID()
  private var currentMIDIPreviewURL: URL?
  private var projectLoadTask: Task<Void, Never>?
  private var projectLoadGeneration = UUID()
  private var activeSecurityScopedURLs: [URL] = []
  private var lastMelodyGapID: String?
  private var lastProjectReviewIssueID: String?
  private var pendingSelectedNoteID: String?
  private var pendingSelectedTrackID: String?
  private var pendingCompletedBundleID: String?
  private var pendingCompletedTrackID: String?
  private var selectionLoadTask: Task<Void, Never>?
  private var selectionLoadGeneration = UUID()
  private var trackManagementTask: Task<Void, Never>?
  private var trackManagementGeneration = UUID()
  private var pendingFragmentRepairTrackID: String?
  private var monitoredBetaProjectPaths = Set<String>()
  private var pendingHyakTimeConfirmations: [HyakTimeConfirmationRequest] = []

  public init(
    defaults: UserDefaults = .standard,
    initialProjectURL: URL? = nil,
    restoreRecent: Bool = true,
    persistRecentProject: Bool = true
  ) {
    self.defaults = defaults
    self.persistRecentProject = persistRecentProject
    let originalVolume =
      defaults.object(forKey: originalVolumeKey) as? Double ?? 0.35
    transport.setOriginalVolume(originalVolume)
    midiMasterVolume =
      defaults.object(forKey: midiMasterVolumeKey) as? Double ?? 1
    appearanceMode =
      defaults.string(forKey: appearanceModeKey)
      .flatMap(AMTAppearanceMode.init(rawValue:)) ?? .precision
    computeMode =
      defaults.string(forKey: computeModeKey)
      .flatMap(ComputeMode.init(rawValue:)) ?? .hyak
    recognitionMode =
      defaults.string(forKey: recognitionModeKey)
      .flatMap(RecognitionMode.init(rawValue:)) ?? .multitrack
    let savedTimeLimit = defaults.integer(forKey: hyakTimeLimitHoursKey)
    hyakTimeLimitHours =
      (1...24).contains(savedTimeLimit) ? savedTimeLimit : 1
    songQueue = Self.restoreSongQueue(
      from: defaults.data(forKey: songQueueKey)
    )
    monitoredBetaProjectPaths = Set(
      (defaults.stringArray(forKey: activeBetaProjectsKey) ?? []).filter {
        FileManager.default.fileExists(atPath: $0)
      }
    )
    if let legacyPath = defaults.string(forKey: activeBetaProjectKey),
      FileManager.default.fileExists(atPath: legacyPath)
    {
      monitoredBetaProjectPaths.insert(legacyPath)
    }
    if let initialProjectURL {
      pendingInitialProjectURL = initialProjectURL
    } else if restoreRecent,
      let path = defaults.string(forKey: activeBetaProjectKey),
      FileManager.default.fileExists(atPath: path)
    {
      pendingInitialProjectURL = URL(fileURLWithPath: path)
    } else if restoreRecent,
      let path = monitoredBetaProjectPaths.sorted().first
    {
      pendingInitialProjectURL = URL(fileURLWithPath: path)
    } else if restoreRecent,
      let path = defaults.string(forKey: recentProjectKey)
    {
      let restored = Self.restoreProjectBookmark(
        path: path,
        defaults: defaults,
        key: projectBookmarksKey
      )
      pendingInitialProjectURL =
        restored?.url ?? URL(fileURLWithPath: path)
      if restored?.accessing == true, let url = restored?.url {
        activeSecurityScopedURLs.append(url)
      }
    }
  }

  public func openInitialProjectIfNeeded() {
    guard let pendingInitialProjectURL else {
      processSongQueueIfPossible()
      return
    }
    self.pendingInitialProjectURL = nil
    openProject(pendingInitialProjectURL)
  }

  public func openAuthorizedProject(_ url: URL) {
    do {
      let data = try url.bookmarkData(
        options: [.withSecurityScope],
        includingResourceValuesForKeys: nil,
        relativeTo: nil
      )
      var bookmarks =
        defaults.dictionary(forKey: projectBookmarksKey)?
        .compactMapValues { $0 as? Data } ?? [:]
      bookmarks[url.standardizedFileURL.path] = data
      bookmarks[url.standardizedFileURL.resolvingSymlinksInPath().path] = data
      defaults.set(bookmarks, forKey: projectBookmarksKey)
      if url.startAccessingSecurityScopedResource() {
        activeSecurityScopedURLs.append(url)
      }
    } catch {
      statusMessage = "项目可以打开，但 macOS 未能保存长期文件授权"
    }
    openProject(url)
  }

  public func revealCurrentProject() {
    guard let url = catalog?.rootURL else { return }
    NSWorkspace.shared.activateFileViewerSelecting([url])
  }

  public func refreshProjectLibrary() {
    guard !isRefreshingLibrary else { return }
    isRefreshingLibrary = true
    Task {
      do {
        let root = try PrivateBetaBackend.locate().localProjectsRoot
        let projects = try await Task.detached(priority: .utility) {
          try LocalProjectLibrary.scan(rootURL: root)
        }.value
        libraryProjects = projects
      } catch {
        libraryProjects = []
      }
      isRefreshingLibrary = false
    }
  }

  public func isDeletingProject(_ project: LocalProjectItem) -> Bool {
    deletingProjectIDs.contains(project.id)
  }

  public func revealProject(_ project: LocalProjectItem) {
    NSWorkspace.shared.activateFileViewerSelecting([project.url])
  }

  public func moveProjectToTrash(_ project: LocalProjectItem) {
    guard project.canMoveToTrash else {
      statusMessage = "正在排队或识别的项目不能删除；任务结束后再试"
      return
    }
    guard !deletingProjectIDs.contains(project.id) else { return }
    deletingProjectIDs.insert(project.id)
    Task { [weak self] in
      guard let self else { return }
      do {
        let root = try PrivateBetaBackend.locate().localProjectsRoot
        let target = try LocalProjectLibrary.validatedTrashTarget(
          project,
          rootURL: root
        )
        try await Self.recycleProject(at: target)
        self.finishProjectRemoval(project, target: target)
      } catch {
        self.present(error)
      }
      self.deletingProjectIDs.remove(project.id)
    }
  }

  public func openHyakLogin() {
    do {
      let backend = try PrivateBetaBackend.locate()
      guard
        FileManager.default.isExecutableFile(
          atPath: backend.loginScriptURL.path
        )
      else {
        throw PrivateBetaBackendError.repositoryNotFound
      }
      guard NSWorkspace.shared.open(backend.loginScriptURL) else {
        throw PrivateBetaBackendError.invalidResponse(
          "无法用 Terminal 打开 Hyak 登录脚本"
        )
      }
      hyakConnectionState = .checking
      statusMessage = "请在 Terminal 输入密码并通过 Duo；连接成功后应用会自动恢复任务"
      errorMessage = nil
      waitForHyakLogin()
    } catch {
      present(error)
    }
  }

  public func refreshHyakCapacity() {
    guard !isCheckingHyakCapacity else { return }
    isCheckingHyakCapacity = true
    hyakCapacityMessage = "正在进行只读调度检查…"
    Task {
      do {
        let backend = try PrivateBetaBackend.locate()
        let timeLimitHours = hyakTimeLimitHours
        let response = try await Task.detached(priority: .utility) {
          try backend.capacity(timeLimitHours: timeLimitHours)
        }.value
        try validateBetaResponse(response)
        guard response.readOnly == true, let capacity = response.gpuCapacity
        else {
          throw PrivateBetaBackendError.invalidResponse(
            "Hyak 资源检查缺少只读证明或 GPU 状态"
          )
        }
        hyakGPUCapacity = capacity
        hyakCapacityRunningJobs = response.runningJobs ?? 0
        hyakCapacityPendingJobs = response.pendingJobs ?? 0
        hyakCapacityOtherJobs = response.otherJobs ?? 0
        hyakCapacityCheckedAt =
          Self.parseBackendDate(response.checkedAt) ?? Date()
        hyakCapacityMessage =
          capacity.isEmpty
          ? "未发现当前账号可用的兼容 GPU 计划"
          : "已用 \(timeLimitHours) 小时任务配置完成只读检查"
        hyakConnectionState = .connected
        errorMessage = nil
      } catch {
        if let backendError = error as? PrivateBetaBackendError,
          case .hyakLoginRequired = backendError
        {
          hyakConnectionState = .loginRequired
          hyakCapacityMessage = "Hyak 登录已过期；请重新连接后再检查"
        } else {
          hyakCapacityMessage =
            (error as? LocalizedError)?.errorDescription
            ?? error.localizedDescription
        }
      }
      isCheckingHyakCapacity = false
    }
  }

  public func checkHyakConnection() {
    connectionMonitor?.cancel()
    connectionMonitor = Task { [weak self] in
      guard let self else { return }
      _ = await self.probeHyakConnection(resumeJob: true)
    }
  }

  public func transcribeSong(_ audioURL: URL) {
    enqueueSongs([audioURL])
  }

  public func enqueueSongs(_ audioURLs: [URL]) {
    let existingPaths = Set(
      songQueue.map { $0.audioURL.standardizedFileURL.path }
        + pendingHyakTimeConfirmations.map {
          $0.audioURL.standardizedFileURL.path
        }
        + [hyakTimeConfirmation?.audioURL.standardizedFileURL.path]
          .compactMap { $0 }
    )
    var queuedPaths = existingPaths
    var addedCount = 0
    for audioURL in audioURLs {
      let standardizedURL = audioURL.standardizedFileURL
      guard queuedPaths.insert(standardizedURL.path).inserted else {
        continue
      }
      let effectiveComputeMode =
        recognitionMode.requiresHyak ? ComputeMode.hyak : computeMode
      let bookmarkData = try? standardizedURL.bookmarkData(
        options: [.withSecurityScope],
        includingResourceValuesForKeys: nil,
        relativeTo: nil
      )
      let durationSeconds = Self.audioDurationSeconds(at: standardizedURL)
      if effectiveComputeMode == .hyak,
        let durationSeconds,
        HyakWallTimePolicy.automaticHours(
          durationSeconds: durationSeconds,
          configuredMinimum: hyakTimeLimitHours
        ) == nil
      {
        pendingHyakTimeConfirmations.append(
          HyakTimeConfirmationRequest(
            title: standardizedURL.deletingPathExtension().lastPathComponent,
            durationSeconds: durationSeconds,
            audioURL: standardizedURL,
            computeMode: effectiveComputeMode,
            recognitionMode: recognitionMode,
            bookmarkData: bookmarkData
          ))
      } else {
        let resolvedHours =
          durationSeconds.flatMap {
            HyakWallTimePolicy.automaticHours(
              durationSeconds: $0,
              configuredMinimum: hyakTimeLimitHours
            )
          } ?? hyakTimeLimitHours
        appendQueuedSong(
          title: standardizedURL.deletingPathExtension().lastPathComponent,
          audioURL: standardizedURL,
          computeMode: effectiveComputeMode,
          recognitionMode: recognitionMode,
          hyakTimeLimitHours: resolvedHours,
          bookmarkData: bookmarkData
        )
      }
      addedCount += 1
    }
    guard addedCount > 0 else {
      statusMessage = "所选歌曲已经在等待队列中"
      return
    }
    persistSongQueue()
    showNextHyakTimeConfirmationIfNeeded()
    statusMessage =
      pendingHyakTimeConfirmations.isEmpty && hyakTimeConfirmation == nil
      ? (addedCount == 1
        ? "已加入任务队列"
        : "已加入 \(addedCount) 首歌曲；Hyak 会依次提交给 Slurm")
      : "较长歌曲需要先确认 Hyak 任务时长；其他歌曲已加入队列"
    errorMessage = nil
    processSongQueueIfPossible()
  }

  public func confirmHyakTimeLimit(_ hours: Int) {
    guard let request = hyakTimeConfirmation else { return }
    appendQueuedSong(
      title: request.title,
      audioURL: request.audioURL,
      computeMode: request.computeMode,
      recognitionMode: request.recognitionMode,
      hyakTimeLimitHours: max(1, min(24, hours)),
      bookmarkData: request.bookmarkData
    )
    hyakTimeConfirmation = nil
    persistSongQueue()
    showNextHyakTimeConfirmationIfNeeded()
    statusMessage = "已确认“\(request.title)”的 Hyak 时长并加入队列"
    processSongQueueIfPossible()
  }

  public func cancelHyakTimeConfirmation() {
    guard let request = hyakTimeConfirmation else { return }
    hyakTimeConfirmation = nil
    showNextHyakTimeConfirmationIfNeeded()
    statusMessage = "未提交“\(request.title)”"
  }

  private func showNextHyakTimeConfirmationIfNeeded() {
    guard hyakTimeConfirmation == nil,
      !pendingHyakTimeConfirmations.isEmpty
    else { return }
    hyakTimeConfirmation = pendingHyakTimeConfirmations.removeFirst()
  }

  private func appendQueuedSong(
    title: String,
    audioURL: URL,
    computeMode: ComputeMode,
    recognitionMode: RecognitionMode,
    hyakTimeLimitHours: Int,
    bookmarkData: Data?
  ) {
    songQueue.append(
      SongQueueItem(
        id: UUID(),
        title: title,
        audioURL: audioURL,
        computeMode: computeMode,
        recognitionMode: recognitionMode,
        hyakTimeLimitHours: hyakTimeLimitHours,
        state: .waiting,
        failureMessage: nil,
        bookmarkData: bookmarkData
      ))
  }

  private static func audioDurationSeconds(at url: URL) -> Double? {
    let accessing = url.startAccessingSecurityScopedResource()
    defer {
      if accessing {
        url.stopAccessingSecurityScopedResource()
      }
    }
    let seconds = CMTimeGetSeconds(AVURLAsset(url: url).duration)
    return seconds.isFinite && seconds >= 0 ? seconds : nil
  }

  private static func parseBackendDate(_ value: String?) -> Date? {
    guard let value else { return nil }
    let fractional = ISO8601DateFormatter()
    fractional.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
    if let date = fractional.date(from: value) {
      return date
    }
    return ISO8601DateFormatter().date(from: value)
  }

  public func retryQueuedSong(_ id: UUID) {
    guard
      let index = songQueue.firstIndex(where: { $0.id == id }),
      songQueue[index].state == .failed
    else {
      return
    }
    songQueue[index].state = .waiting
    songQueue[index].failureMessage = nil
    persistSongQueue()
    processSongQueueIfPossible()
  }

  public func removeQueuedSong(_ id: UUID) {
    guard
      let index = songQueue.firstIndex(where: { $0.id == id }),
      songQueue[index].state != .submitting
    else {
      return
    }
    let title = songQueue[index].title
    songQueue.remove(at: index)
    persistSongQueue()
    statusMessage = "已从等待队列移除“\(title)”"
  }

  private func processSongQueueIfPossible() {
    guard !isBetaBusy else { return }
    guard
      let index = songQueue.firstIndex(where: { $0.state == .waiting })
    else {
      return
    }
    let item = songQueue[index]
    guard
      SongQueuePolicy.canSubmit(
        item,
        hasActiveProjectTask: activeProjectTaskCount > 0
      )
    else {
      return
    }
    let audioURL = item.resolvedAudioURL()
    let accessing = audioURL.startAccessingSecurityScopedResource()
    songQueue[index].state = .submitting
    songQueue[index].failureMessage = nil
    persistSongQueue()
    isBetaBusy = true
    statusMessage =
      item.computeMode == .hyak
      ? "正在提交“\(item.title)”到 Hyak；后面还有 \(waitingSongCount) 首…"
      : "正在为“\(item.title)”启动\(item.computeMode.label)任务…"
    errorMessage = nil
    Task {
      var shouldAdvance = false
      do {
        let backend = try PrivateBetaBackend.locate()
        let response = try await Task.detached(priority: .userInitiated) {
          try backend.start(
            audioURL: audioURL,
            computeMode: item.computeMode,
            hyakTimeLimitHours: item.hyakTimeLimitHours,
            recognitionMode: item.recognitionMode
          )
        }.value
        try handleBetaResponse(response)
        songQueue.removeAll { $0.id == item.id }
        persistSongQueue()
        showJobProgress()
        if item.computeMode == .hyak {
          hyakConnectionState = .connected
        }
        if let betaProjectURL {
          startMonitoring(projectURL: betaProjectURL)
        }
        shouldAdvance =
          item.computeMode == .hyak
          || (!hasActiveBetaJob && response.status != "succeeded")
      } catch {
        if let backendError = error as? PrivateBetaBackendError,
          case .hyakLoginRequired = backendError
        {
          updateQueuedSong(
            item.id,
            state: .waiting,
            failureMessage: nil
          )
        } else {
          let message =
            (error as? LocalizedError)?.errorDescription
            ?? error.localizedDescription
          updateQueuedSong(
            item.id,
            state: .failed,
            failureMessage: message
          )
          shouldAdvance = true
        }
        presentBetaError(error)
      }
      if accessing {
        audioURL.stopAccessingSecurityScopedResource()
      }
      isBetaBusy = false
      if shouldAdvance {
        processSongQueueIfPossible()
      }
    }
  }

  public var waitingSongCount: Int {
    songQueue.lazy.filter { $0.state == .waiting }.count
  }

  public func addGameVocalVersion() {
    guard !isBetaBusy, !hasActiveBetaJob, let catalog else { return }
    let projectURL = catalog.rootURL
    let requestedTimeLimit = hyakTimeLimitHours
    isBetaBusy = true
    statusMessage =
      "正在准备人声分离与 GAME 主唱旋律任务；原识别版本不会被修改…"
    errorMessage = nil
    Task {
      do {
        let backend = try PrivateBetaBackend.locate()
        let response = try await Task.detached(priority: .userInitiated) {
          try backend.startGameVocal(
            projectURL: projectURL,
            hyakTimeLimitHours: requestedTimeLimit
          )
        }.value
        try handleBetaResponse(response)
        showJobProgress()
        hyakConnectionState = .connected
        if let betaProjectURL {
          startMonitoring(projectURL: betaProjectURL)
        }
      } catch {
        presentBetaError(error)
      }
      isBetaBusy = false
    }
  }

  public func recoverSelectedGaps() {
    guard !isBetaBusy, !hasActiveBetaJob else { return }
    guard let catalog, let editor, let sourceBundleID = selectedBundleID else {
      present(AMTProjectError.missingCanonicalBundle)
      return
    }
    let gaps = selectedMelodyGaps
    guard !gaps.isEmpty else {
      statusMessage = "请先勾选至少一段空缺"
      return
    }
    guard gaps.count <= 16 else {
      statusMessage = "一次最多重算 16 段，请减少选择后再提交"
      return
    }
    guard editor.selectedTrack.instrument?.isEmpty == false else {
      statusMessage = "当前音轨没有可用于定向重算的乐器标签"
      return
    }
    let projectURL = catalog.rootURL
    let sourceTrackID = editor.selectedTrack.id
    let requestedMode = computeMode
    let requestedTimeLimit = hyakTimeLimitHours
    pendingCompletedTrackID = sourceTrackID
    isBetaBusy = true
    statusMessage =
      "正在把所选 \(gaps.count) 段空缺合并为一个\(requestedMode.label)任务…"
    errorMessage = nil
    Task {
      do {
        let backend = try PrivateBetaBackend.locate()
        let response = try await Task.detached(priority: .userInitiated) {
          try backend.startGapRecovery(
            projectURL: projectURL,
            sourceBundleID: sourceBundleID,
            sourceTrackID: sourceTrackID,
            gaps: gaps,
            computeMode: requestedMode,
            hyakTimeLimitHours: requestedTimeLimit
          )
        }.value
        try handleBetaResponse(response)
        showJobProgress()
        if requestedMode == .hyak {
          hyakConnectionState = .connected
        }
        if let betaProjectURL {
          startMonitoring(projectURL: betaProjectURL)
        }
      } catch {
        pendingCompletedTrackID = nil
        presentBetaError(error)
      }
      isBetaBusy = false
    }
  }

  public func refreshBetaJob() {
    guard let betaProjectURL, !isBetaBusy else { return }
    isBetaBusy = true
    Task {
      await refreshBetaJob(projectURL: betaProjectURL)
      isBetaBusy = false
      processSongQueueIfPossible()
    }
  }

  public func suggestedResumeHours(for project: LocalProjectItem) -> Int {
    HyakWallTimePolicy.suggestedManualHours(
      durationSeconds: project.durationSeconds,
      configuredMinimum: hyakTimeLimitHours
    )
  }

  public func resumeTimedOutProject(
    _ project: LocalProjectItem,
    hours: Int
  ) {
    guard !isBetaBusy, project.canResumeTimeout else { return }
    let requestedHours = max(1, min(24, hours))
    isBetaBusy = true
    statusMessage =
      "正在检查“\(project.title)”的可复用检查点并续交 Hyak…"
    errorMessage = nil
    Task {
      do {
        let backend = try PrivateBetaBackend.locate()
        let response = try await Task.detached(priority: .userInitiated) {
          try backend.resumeTimeout(
            projectURL: project.url,
            hyakTimeLimitHours: requestedHours
          )
        }.value
        try handleBetaResponse(response)
        showJobProgress()
        hyakConnectionState = .connected
        startMonitoring(projectURL: project.url)
        refreshProjectLibrary()
      } catch {
        presentBetaError(error)
      }
      isBetaBusy = false
    }
  }

  public var hasActiveBetaJob: Bool {
    betaProjectURL != nil
      && !LocalProjectItem.terminalStates.contains(betaSlurmState ?? "")
  }

  public var shouldShowJobProgress: Bool {
    hasActiveBetaJob && (isShowingJobProgress || editor == nil)
  }

  public func showJobProgress() {
    guard hasActiveBetaJob else { return }
    isShowingJobProgress = true
  }

  public func showCurrentResult() {
    guard editor != nil else { return }
    isShowingJobProgress = false
  }

  public var bundleChoices: [CanonicalBundleChoice] {
    (catalog?.bundles ?? []).filter(\.isDefaultEligible).sorted {
      if $0.modifiedAt == $1.modifiedAt {
        return $0.id > $1.id
      }
      return $0.modifiedAt > $1.modifiedAt
    }
  }

  public var selectedBundleID: String? {
    guard let catalog, let snapshot else { return nil }
    return catalog.bundles.first {
      $0.canonicalProjectURL == snapshot.canonicalProjectURL
    }?.id
  }

  public var trackChoices: [EditorTrack] {
    snapshot?.tracks ?? []
  }

  public var saveStatusLabel: String {
    guard let lastSavedAt else { return "尚无人工修改" }
    return "已保存 \(lastSavedAt.formatted(date: .omitted, time: .shortened))"
  }

  public var visibleTrackChoices: [EditorTrack] {
    MelodyTrackSelector.productTracks(from: trackChoices)
  }

  public func displayedEventCount(for track: EditorTrack) -> Int {
    guard editor?.selectedTrack.id == track.id else {
      return track.eventCount
    }
    return notes.count
  }

  public func canDeleteTrack(_ trackID: String) -> Bool {
    visibleTrackChoices.count > 1
      && visibleTrackChoices.contains(where: { $0.id == trackID })
  }

  public func bundleDisplayName(_ bundleID: String) -> String {
    let ordered = bundleChoices.sorted {
      if $0.modifiedAt == $1.modifiedAt {
        return $0.id < $1.id
      }
      return $0.modifiedAt < $1.modifiedAt
    }
    guard
      let index = ordered.firstIndex(where: { $0.id == bundleID })
    else {
      return bundleID
    }
    let isCustom =
      ordered[index].manifest.claims?["app_derived_arrangement"]
      == .bool(true)
    let isGameVocal =
      ordered[index].manifest.claims?["game_singing_voice_only"]
      == .bool(true)
    return isCustom
      ? "自定义版本 \(index + 1)"
      : isGameVocal
        ? "GAME 主唱旋律 \(index + 1)"
        : "识别版本 \(index + 1)"
  }

  public func productTracks(in bundleID: String) -> [EditorTrack] {
    guard
      let bundle = catalog?.bundles.first(where: {
        $0.id == bundleID && $0.isDefaultEligible
      })
    else {
      return []
    }
    return MelodyTrackSelector.productTracks(from: bundle.tracks)
  }

  public var otherProductBundles: [CanonicalBundleChoice] {
    bundleChoices.filter { $0.id != selectedBundleID }
  }

  public var crossProjectTargets: [LocalProjectItem] {
    let currentPath =
      catalog?.rootURL.standardizedFileURL.resolvingSymlinksInPath().path
    return libraryProjects.filter {
      $0.hasResults && !$0.hasActiveJob
        && $0.url.standardizedFileURL.resolvingSymlinksInPath().path
          != currentPath
    }
  }

  public var activeProjectTaskCount: Int {
    var paths = monitoredBetaProjectPaths
    paths.formUnion(
      libraryProjects.lazy.filter(\.hasActiveJob).map {
        $0.url.standardizedFileURL.resolvingSymlinksInPath().path
      }
    )
    if hasActiveBetaJob, let betaProjectURL {
      paths.insert(
        betaProjectURL.standardizedFileURL.resolvingSymlinksInPath().path
      )
    }
    return paths.count
  }

  public var activeProjectTiming: LocalProjectItem? {
    guard let betaProjectURL else { return nil }
    let activePath =
      betaProjectURL.standardizedFileURL.resolvingSymlinksInPath().path
    return libraryProjects.first {
      $0.url.standardizedFileURL.resolvingSymlinksInPath().path == activePath
    }
  }

  public var audibleTrackIDs: Set<String> {
    guard let snapshot else { return [] }
    if midiPlaybackMode == .currentTrack {
      guard let editor else { return [] }
      return Set([editor.selectedTrack.id])
    }
    let available = Set(snapshot.tracks.map(\.id))
    let solos = soloTrackIDs.intersection(available)
    if !solos.isEmpty {
      let selectedSoloTrackID = editor.map(\.selectedTrack.id).flatMap {
        solos.contains($0) ? $0 : nil
      }
      return MelodyTrackSelector.resolveExclusiveVariant(
        from: solos,
        tracks: snapshot.tracks,
        selectedTrackID: selectedSoloTrackID
      )
    }
    return MelodyTrackSelector.resolveExclusiveVariant(
      from: available.subtracting(mutedTrackIDs),
      tracks: snapshot.tracks,
      selectedTrackID: editor?.selectedTrack.id
    )
  }

  public var audibleTrackCount: Int {
    audibleTrackIDs.count
  }

  public func setMIDIPlaybackMode(_ mode: MIDIPlaybackMode) {
    guard midiPlaybackMode != mode else { return }
    midiPlaybackMode = mode
    saveMixerSettings()
    refreshMIDIPreview()
  }

  public func isTrackMuted(_ id: String) -> Bool {
    mutedTrackIDs.contains(id)
  }

  public func isTrackSoloed(_ id: String) -> Bool {
    soloTrackIDs.contains(id)
  }

  public func volume(for id: String) -> Double {
    trackVolumes[id] ?? 1
  }

  public func setOriginalVolume(_ value: Double) {
    let bounded = min(1, max(0, value))
    transport.setOriginalVolume(bounded)
    defaults.set(bounded, forKey: originalVolumeKey)
  }

  public func setMIDIMasterVolume(_ value: Double) {
    let bounded = min(1, max(0, value))
    guard midiMasterVolume != bounded else { return }
    midiMasterVolume = bounded
    defaults.set(bounded, forKey: midiMasterVolumeKey)
    scheduleMIDIPreviewRefresh()
  }

  public func setAppearanceMode(_ mode: AMTAppearanceMode) {
    guard appearanceMode != mode else { return }
    appearanceMode = mode
    defaults.set(mode.rawValue, forKey: appearanceModeKey)
  }

  public func setComputeMode(_ mode: ComputeMode) {
    guard computeMode != mode else { return }
    guard !(recognitionMode.requiresHyak && mode != .hyak) else {
      statusMessage = "GAME 主唱旋律使用 Hyak 上隔离的 CUDA 模型环境"
      return
    }
    computeMode = mode
    defaults.set(mode.rawValue, forKey: computeModeKey)
    localReadinessMessage =
      mode == .hyak
      ? "Hyak 是默认计算方式"
      : "尚未检查本机环境"
  }

  public func setRecognitionMode(_ mode: RecognitionMode) {
    guard recognitionMode != mode else { return }
    recognitionMode = mode
    defaults.set(mode.rawValue, forKey: recognitionModeKey)
    if mode.requiresHyak, computeMode != .hyak {
      computeMode = .hyak
      defaults.set(ComputeMode.hyak.rawValue, forKey: computeModeKey)
      localReadinessMessage = "GAME 已自动切换到 Hyak GPU"
    }
  }

  public func setHyakTimeLimitHours(_ hours: Int) {
    let bounded = min(24, max(1, hours))
    guard hyakTimeLimitHours != bounded else { return }
    hyakTimeLimitHours = bounded
    defaults.set(bounded, forKey: hyakTimeLimitHoursKey)
  }

  public func checkLocalCompute() {
    guard computeMode != .hyak, !isCheckingLocalCompute else { return }
    isCheckingLocalCompute = true
    localReadinessMessage = "正在检查本机模型与计算设备…"
    Task {
      do {
        let backend = try PrivateBetaBackend.locate()
        let mode = computeMode
        let response = try await Task.detached(priority: .utility) {
          try backend.localReadiness(computeMode: mode)
        }.value
        guard response.ok else {
          throw PrivateBetaBackendError.invalidResponse(
            response.error ?? "本机环境尚未就绪"
          )
        }
        localReadinessMessage =
          response.readinessMessage
          ?? (response.ready == true ? "本机环境已就绪" : "本机环境尚未就绪")
        errorMessage = nil
      } catch {
        localReadinessMessage =
          (error as? LocalizedError)?.errorDescription
          ?? error.localizedDescription
      }
      isCheckingLocalCompute = false
    }
  }

  public func cancelLocalCompute() {
    guard
      activeComputeMode == .localGPU || activeComputeMode == .localCPU,
      let betaProjectURL,
      !isBetaBusy
    else {
      return
    }
    isBetaBusy = true
    statusMessage = "正在停止本机计算…"
    Task {
      do {
        let backend = try PrivateBetaBackend.locate()
        let response = try await Task.detached(priority: .userInitiated) {
          try backend.cancelLocal(projectURL: betaProjectURL)
        }.value
        try handleBetaResponse(response)
      } catch {
        present(error)
      }
      isBetaBusy = false
    }
  }

  public func toggleMute(_ id: String) {
    guard trackChoices.contains(where: { $0.id == id }) else { return }
    midiPlaybackMode = .mix
    soloTrackIDs.remove(id)
    if !mutedTrackIDs.insert(id).inserted {
      mutedTrackIDs.remove(id)
    }
    saveMixerSettings()
    refreshMIDIPreview()
  }

  public func toggleSolo(_ id: String) {
    guard trackChoices.contains(where: { $0.id == id }) else { return }
    midiPlaybackMode = .mix
    mutedTrackIDs.remove(id)
    if !soloTrackIDs.insert(id).inserted {
      soloTrackIDs.remove(id)
    }
    saveMixerSettings()
    refreshMIDIPreview()
  }

  public func setTrackVolume(_ value: Double, trackID: String) {
    guard trackChoices.contains(where: { $0.id == trackID }) else { return }
    trackVolumes[trackID] = min(1, max(0, value))
    saveMixerSettings()
    scheduleMIDIPreviewRefresh()
  }

  public func enableAllTracks() {
    midiPlaybackMode = .mix
    mutedTrackIDs = []
    soloTrackIDs = []
    saveMixerSettings()
    refreshMIDIPreview()
  }

  public func listenToSelectedTrack() {
    setMIDIPlaybackMode(.currentTrack)
  }

  public var notes: [EditorNote] {
    CanonicalTimeline.clippedNotes(
      editor?.notes ?? [],
      duration: canonicalTimelineDuration
    )
  }

  public var selectedNote: EditorNote? {
    guard let selectedNoteID else { return nil }
    return notes.first(where: { $0.id == selectedNoteID })
  }

  public var reviewNotes: [EditorNote] {
    ConfidenceReviewQueue.notes(
      from: notes,
      threshold: reviewConfidenceThreshold
    )
  }

  public var notesWithoutConfidenceCount: Int {
    notes.lazy.filter { $0.confidence == nil }.count
  }

  public var hasConfidenceReviewData: Bool {
    notes.contains { $0.confidence != nil }
  }

  public var rhythm: RhythmMap? {
    snapshot?.canonicalProject.rhythm
  }

  public var representativeBPM: Double? {
    rhythm.flatMap(RhythmTimeline.representativeBPM)
  }

  public var canonicalTimelineDuration: Double {
    if let duration =
      snapshot?.manifest.canonicalAudio.metadata?.durationSec,
      duration.isFinite,
      duration > 0
    {
      return duration
    }
    return max(
      transport.duration,
      snapshot?.notes.map(\.offsetSec).max() ?? 1
    )
  }

  public var currentMeterLabel: String {
    guard let rhythm else { return "—" }
    let meter = RhythmTimeline.meter(
      at: transport.currentTime,
      rhythm: rhythm
    )
    return "\(meter.numerator)/\(meter.denominator)"
  }

  public var currentMusicalPosition: MusicalPosition? {
    guard let rhythm else { return nil }
    return RhythmTimeline.position(
      at: transport.currentTime,
      duration: canonicalTimelineDuration,
      rhythm: rhythm
    )
  }

  public var rhythmSourceLabel: String {
    guard let rhythm else { return "没有节拍信息" }
    return rhythm.isModelEstimated
      ? "模型估算，建议听感确认"
      : "未分析；当前为 MIDI 默认网格"
  }

  public var projectReviewIssues: [ProjectReviewIssue] {
    guard let snapshot else { return [] }
    let visibleTrackIDs = Set(visibleTrackChoices.map(\.id))
    var allNotes = snapshot.notes.filter {
      visibleTrackIDs.contains($0.trackID)
    }
    if let editor {
      allNotes.removeAll { $0.trackID == editor.selectedTrack.id }
      if visibleTrackIDs.contains(editor.selectedTrack.id) {
        allNotes.append(contentsOf: editor.notes)
      }
    }
    return ProjectReviewAnalyzer.issues(
      notes: CanonicalTimeline.clippedNotes(
        allNotes,
        duration: canonicalTimelineDuration
      ),
      confidenceThreshold: reviewConfidenceThreshold
    )
  }

  public var projectReviewSummary: String {
    let issues = projectReviewIssues
    let low = issues.lazy.filter { $0.kind == .lowConfidence }.count
    let short = issues.count - low
    return "\(issues.count) 项 · 低置信度 \(low) · 过短 \(short)"
  }

  public var trailingCleanupGroups: [SustainFragmentGroup] {
    guard let editor else { return [] }
    return cleanupGroups(
      track: editor.selectedTrack,
      notes: editor.notes
    )
  }

  public var currentTrailingCleanupSummary: TrailingCleanupSummary? {
    guard let track = editor?.selectedTrack else { return nil }
    let groups = trailingCleanupGroups
    guard !groups.isEmpty else { return nil }
    return cleanupSummary(track: track, groups: groups)
  }

  public var currentTrailingCleanupStatus: String {
    guard let editor else {
      return "请选择一条音轨后检查结尾。"
    }
    let tags = Set(editor.notes.flatMap(\.tags))
    if tags.contains("automatic-sustain-cleanup")
      || tags.contains("automatic-percussion-repeat-cleanup")
    {
      return "这一识别版本生成时已经处理过当前音轨；目前没有新的保守修复候选。"
    }
    if tags.contains("app-sustain-merge")
      || tags.contains("app-percussion-repeat-collapse")
    {
      return "当前音轨的碎片修复已经保存；目前没有新的保守修复候选。"
    }
    return "已检查当前音轨，暂未发现符合规则的延音碎片或尾部重复打击。"
  }

  public func performTrailingCleanup() {
    do {
      guard var editor else { return }
      let groups = trailingCleanupGroups
      guard !groups.isEmpty else {
        statusMessage = "当前音轨没有符合条件的碎片"
        return
      }
      let fragmentCount = groups.reduce(0) { $0 + $1.fragmentCount }
      let isPercussion = isPercussionTrack(editor.selectedTrack)
      let merged =
        isPercussion
        ? try editor.collapsePercussionRepeats(groups)
        : try editor.mergeSustainFragments(groups)
      try editor.save()
      let persisted = try EditorProject(
        snapshot: editor.snapshot,
        bundleID: editor.bundleID,
        selectedTrackID: editor.selectedTrack.id
      )
      let persistedIDs = Set(persisted.notes.map(\.id))
      let mergedIDs = Set(merged.map(\.id))
      let sourceFragmentIDs = Set(groups.flatMap(\.noteIDs))
      guard mergedIDs.isSubset(of: persistedIDs),
        persistedIDs.isDisjoint(with: sourceFragmentIDs)
      else {
        throw AMTProjectError.invalidEvent(
          "连续音修复没有完整保存，请保持原轨不变后重试"
        )
      }
      self.editor = persisted
      recordSave(persisted)
      selectedNoteID = merged.first?.id
      statusMessage =
        isPercussion
        ? "已把 \(fragmentCount) 个尾部重复打击折叠为 \(merged.count) 个单次打击；已保存且可撤销"
        : "已把 \(fragmentCount) 个碎片重建为 \(merged.count) 个连续音；保存校验通过且可撤销"
      errorMessage = nil
      updateMelodyCoverage()
      refreshTrailingCleanupDiagnostics()
      refreshMIDIPreview()
    } catch {
      present(error)
    }
  }

  private func cleanupGroups(
    track: EditorTrack,
    notes: [EditorNote]
  ) -> [SustainFragmentGroup] {
    if isPercussionTrack(track) {
      return PercussionRepeatAnalyzer.trailingGroups(
        notes: notes,
        timelineEnd: canonicalTimelineDuration
      )
    }
    return SustainFragmentAnalyzer.fragmentedGroups(
      notes: notes,
      timelineEnd: canonicalTimelineDuration
    )
  }

  private func cleanupSummary(
    track: EditorTrack,
    groups: [SustainFragmentGroup]
  ) -> TrailingCleanupSummary {
    TrailingCleanupSummary(
      kind: isPercussionTrack(track) ? .percussionRepeats : .sustain,
      groupCount: groups.count,
      fragmentCount: groups.reduce(0) { $0 + $1.fragmentCount }
    )
  }

  private func isPercussionTrack(_ track: EditorTrack) -> Bool {
    let instrument = track.instrument?.lowercased() ?? ""
    return instrument == "drums"
      || instrument.contains("drum")
      || track.id.lowercased() == "drums"
  }

  private func refreshTrailingCleanupDiagnostics() {
    guard let snapshot else {
      trailingCleanupSummaries = [:]
      return
    }
    var notesByTrack = Dictionary(
      grouping: snapshot.notes,
      by: \.trackID
    )
    if let editor {
      notesByTrack[editor.selectedTrack.id] = editor.notes
    }
    trailingCleanupSummaries = Dictionary(
      uniqueKeysWithValues: snapshot.tracks.compactMap { track in
        let groups = cleanupGroups(
          track: track,
          notes: notesByTrack[track.id] ?? []
        )
        guard !groups.isEmpty else { return nil }
        return (track.id, cleanupSummary(track: track, groups: groups))
      }
    )
  }

  private func updateMelodyCoverage() {
    guard let snapshot, let track = editor?.selectedTrack else {
      melodyGaps = []
      selectedGapIDs = []
      return
    }
    let sourceNotes = snapshot.notes.filter { $0.trackID == track.id }
    melodyGaps = MelodyCoverageAnalyzer.gaps(
      voiceNotes: sourceNotes,
      allNotes: snapshot.notes,
      voiceTrackID: track.id,
      duration: canonicalTimelineDuration
    )
    selectedGapIDs = Set(melodyGaps.map(\.id))
  }

  public var melodyGapDuration: Double {
    melodyGaps.reduce(0) { $0 + $1.duration }
  }

  public var melodyCoverageTrackLabel: String {
    editor.map { MelodyTrackSelector.displayLabel(for: $0.selectedTrack) }
      ?? "当前音轨"
  }

  public var selectedMelodyGaps: [MelodyGap] {
    melodyGaps.filter { selectedGapIDs.contains($0.id) }
  }

  public var selectedMelodyGapDuration: Double {
    selectedMelodyGaps.reduce(0) { $0 + $1.duration }
  }

  public func isGapSelected(_ gap: MelodyGap) -> Bool {
    selectedGapIDs.contains(gap.id)
  }

  public func setGapSelected(_ gap: MelodyGap, selected: Bool) {
    guard melodyGaps.contains(where: { $0.id == gap.id }) else { return }
    if selected {
      selectedGapIDs.insert(gap.id)
    } else {
      selectedGapIDs.remove(gap.id)
    }
  }

  public func selectAllGaps() {
    selectedGapIDs = Set(melodyGaps.map(\.id))
  }

  public func clearGapSelection() {
    selectedGapIDs = []
  }

  public var hasEnhancedVoiceTrack: Bool {
    snapshot?.tracks.contains(where: {
      ["voice_enhanced", "voice_auto_enhanced"].contains($0.id)
    }) == true
  }

  public func repairFragments(in trackID: String) {
    guard trackChoices.contains(where: { $0.id == trackID }) else { return }
    if editor?.selectedTrack.id == trackID {
      performTrailingCleanup()
      return
    }
    pendingFragmentRepairTrackID = trackID
    chooseTrack(trackID)
  }

  public func refreshFragmentRepairDiagnostics() {
    refreshTrailingCleanupDiagnostics()
  }

  public func fragmentRepairActionLabel(for trackID: String) -> String {
    guard let track = trackChoices.first(where: { $0.id == trackID }) else {
      return "重新扫描音符碎片…"
    }
    return isPercussionTrack(track)
      ? "重新扫描尾部重复打击…"
      : "预览并重建整轨连续音…"
  }

  public func seekToNextMelodyGap() {
    let gaps = melodyGaps
    guard !gaps.isEmpty else { return }
    let next: MelodyGap
    if let lastMelodyGapID,
      let index = gaps.firstIndex(where: { $0.id == lastMelodyGapID })
    {
      next = gaps[(index + 1) % gaps.count]
    } else {
      next =
        gaps.first(where: { $0.endSec > transport.currentTime + 0.25 })
        ?? gaps[0]
    }
    lastMelodyGapID = next.id
    transport.seek(to: max(0, next.startSec - 0.5))
    statusMessage =
      "已定位 \(melodyCoverageTrackLabel) 疑似空缺 \(formatClock(next.startSec))–\(formatClock(next.endSec))"
  }

  public var reviewPositionDescription: String {
    guard !reviewNotes.isEmpty else { return "0 / 0" }
    guard let selectedNoteID,
      let index = reviewNotes.firstIndex(where: { $0.id == selectedNoteID })
    else {
      return "未选择 / \(reviewNotes.count)"
    }
    return "\(index + 1) / \(reviewNotes.count)"
  }

  public func openProject(_ url: URL) {
    projectLoadTask?.cancel()
    selectionLoadTask?.cancel()
    trackManagementTask?.cancel()
    trackManagementGeneration = UUID()
    isManagingTracks = false
    selectionLoadGeneration = UUID()
    isLoadingSelection = false
    let generation = UUID()
    projectLoadGeneration = generation
    isLoadingProject = true
    melodyGaps = []
    selectedGapIDs = []
    statusMessage = "正在后台校验并打开 \(url.lastPathComponent)…"
    errorMessage = nil
    projectLoadTask = Task { [weak self] in
      do {
        let prepared = try await Task.detached(priority: .userInitiated) {
          try PreparedProject.load(url)
        }.value
        guard !Task.isCancelled, let self,
          self.projectLoadGeneration == generation
        else {
          return
        }
        self.applyPreparedProject(prepared)
      } catch is CancellationError {
        return
      } catch {
        guard let self, self.projectLoadGeneration == generation else {
          return
        }
        self.present(error)
      }
      if let self, self.projectLoadGeneration == generation {
        self.isLoadingProject = false
      }
    }
  }

  func waitForProjectLoadForTesting() async {
    await projectLoadTask?.value
  }

  func waitForSelectionLoadForTesting() async {
    await selectionLoadTask?.value
  }

  public func selectBundle(_ id: String) throws {
    guard let catalog else {
      throw AMTProjectError.missingManifest
    }
    let snapshot = try ProjectLoader.open(catalog, bundleID: id)
    self.snapshot = snapshot
    editor = nil
    selectedNoteID = nil
    lastMelodyGapID = nil
    selectedGapIDs = []
    transport.stop()
    discardMIDIPreviewArtifact()
    restoreMixerSettings(for: snapshot)
    updateMelodyCoverage()
    refreshTrailingCleanupDiagnostics()
    statusMessage = "已验证多轨结果 \(id)；请选择一条音轨"
    errorMessage = nil
    if let voice = MelodyTrackSelector.preferred(in: snapshot.tracks) {
      try selectTrack(voice.id)
      statusMessage =
        "已默认打开 \(MelodyTrackSelector.displayLabel(for: voice))；其余原始音轨仍完整保留"
    } else if snapshot.tracks.count == 1 {
      try selectTrack(snapshot.tracks[0].id)
    }
  }

  public func chooseBundle(
    _ id: String,
    preferredTrackID: String? = nil
  ) {
    guard let catalog else { return }
    selectionLoadTask?.cancel()
    let generation = UUID()
    selectionLoadGeneration = generation
    isLoadingSelection = true
    statusMessage = "正在后台打开识别版本 \(id)…"
    selectionLoadTask = Task { [weak self] in
      do {
        let prepared = try await Task.detached(priority: .userInitiated) {
          try PreparedSelection.loadBundle(
            catalog: catalog,
            bundleID: id,
            preferredTrackID: preferredTrackID
          )
        }.value
        guard !Task.isCancelled, let self,
          self.selectionLoadGeneration == generation
        else {
          return
        }
        self.applyPreparedSelection(prepared)
      } catch is CancellationError {
        return
      } catch {
        guard let self, self.selectionLoadGeneration == generation else {
          return
        }
        self.present(error)
      }
      if let self, self.selectionLoadGeneration == generation {
        self.isLoadingSelection = false
      }
    }
  }

  public func selectTrack(_ id: String) throws {
    guard let catalog, let snapshot else {
      throw AMTProjectError.missingCanonicalBundle
    }
    guard
      let bundleID = catalog.bundles.first(
        where: { $0.canonicalProjectURL == snapshot.canonicalProjectURL }
      )?.id
    else {
      throw AMTProjectError.missingCanonicalBundle
    }
    let editor = try EditorProject(
      snapshot: snapshot,
      bundleID: bundleID,
      selectedTrackID: id
    )
    try editor.saveWorkspaceSelection()
    self.editor = editor
    lastSavedAt = editor.persistedUpdatedAt
    selectedNoteID = editor.notes.first?.id
    statusMessage = "音轨 \(editor.selectedTrack.label)，\(editor.notes.count) 个音符"
    errorMessage = nil
    transport.load(audioURL: snapshot.audioURL)
    updateMelodyCoverage()
    refreshTrailingCleanupDiagnostics()
    refreshMIDIPreview()
  }

  public func chooseTrack(_ id: String) {
    guard let catalog, let snapshot,
      let bundleID = catalog.bundles.first(where: {
        $0.canonicalProjectURL == snapshot.canonicalProjectURL
      })?.id
    else {
      return
    }
    selectionLoadTask?.cancel()
    let generation = UUID()
    selectionLoadGeneration = generation
    isLoadingSelection = true
    statusMessage = "正在后台打开音轨…"
    selectionLoadTask = Task { [weak self] in
      do {
        let prepared = try await Task.detached(priority: .userInitiated) {
          try PreparedSelection.loadTrack(
            snapshot: snapshot,
            bundleID: bundleID,
            trackID: id
          )
        }.value
        guard !Task.isCancelled, let self,
          self.selectionLoadGeneration == generation
        else {
          return
        }
        self.applyPreparedSelection(prepared)
      } catch is CancellationError {
        return
      } catch {
        guard let self, self.selectionLoadGeneration == generation else {
          return
        }
        if self.pendingFragmentRepairTrackID == id {
          self.pendingFragmentRepairTrackID = nil
        }
        self.present(error)
      }
      if let self, self.selectionLoadGeneration == generation {
        self.isLoadingSelection = false
      }
    }
  }

  public func copyTrack(
    from sourceBundleID: String,
    trackID: String
  ) {
    deriveTrackArrangement(
      .copy(
        sourceBundleID: sourceBundleID,
        sourceTrackID: trackID
      ),
      progress: "正在复制所选音轨并创建自定义版本…"
    )
  }

  public func copySelectedTrack(
    to targetProject: LocalProjectItem,
    targetBundleID: String
  ) {
    guard !isManagingTracks, let sourceCatalog = catalog,
      let sourceBundleID = selectedBundleID,
      let sourceTrackID = editor?.selectedTrack.id
    else {
      return
    }
    guard targetProject.hasResults, !targetProject.hasActiveJob else {
      statusMessage = "目标歌曲正在识别或没有可用结果，暂时不能写入新版本"
      return
    }
    isManagingTracks = true
    statusMessage =
      "正在把当前音轨复制到“\(targetProject.title)”并创建自定义版本…"
    errorMessage = nil
    trackManagementTask?.cancel()
    let generation = UUID()
    trackManagementGeneration = generation
    trackManagementTask = Task { [weak self] in
      defer {
        if self?.trackManagementGeneration == generation {
          self?.isManagingTracks = false
        }
      }
      do {
        let result = try await Task.detached(priority: .userInitiated) {
          let targetCatalog = try ProjectLoader.inspect(targetProject.url)
          return try TrackArrangementBuilder.copyAcrossProjects(
            sourceCatalog: sourceCatalog,
            sourceBundleID: sourceBundleID,
            sourceTrackID: sourceTrackID,
            targetCatalog: targetCatalog,
            targetBundleID: targetBundleID
          )
        }.value
        guard !Task.isCancelled, let self,
          self.trackManagementGeneration == generation
        else {
          return
        }
        self.pendingCompletedBundleID = result.bundleID
        self.pendingCompletedTrackID = result.selectedTrackID
        self.statusMessage =
          "已复制到“\(targetProject.title)”；正在打开目标自定义版本"
        self.refreshProjectLibrary()
        self.openProject(targetProject.url)
      } catch is CancellationError {
        return
      } catch {
        guard let self else { return }
        self.present(error)
      }
    }
  }

  public func mergeTracks(
    _ trackIDs: Set<String>,
    instrumentSourceTrackID: String
  ) {
    deriveTrackArrangement(
      .merge(
        trackIDs: trackIDs,
        instrumentSourceTrackID: instrumentSourceTrackID
      ),
      progress: "正在合并 \(trackIDs.count) 条音轨并创建自定义版本…"
    )
  }

  public func deleteTrack(_ trackID: String) {
    guard canDeleteTrack(trackID) else {
      statusMessage = "当前版本至少需要保留一条可见产品音轨"
      return
    }
    deriveTrackArrangement(
      .delete(trackID: trackID),
      progress: "正在从自定义副本中删除音轨…"
    )
  }

  private func deriveTrackArrangement(
    _ action: TrackArrangementAction,
    progress: String
  ) {
    guard !isManagingTracks, let catalog, let targetBundleID = selectedBundleID
    else {
      return
    }
    isManagingTracks = true
    statusMessage = progress
    errorMessage = nil
    trackManagementTask?.cancel()
    let generation = UUID()
    trackManagementGeneration = generation
    trackManagementTask = Task { [weak self] in
      defer {
        if self?.trackManagementGeneration == generation {
          self?.isManagingTracks = false
        }
      }
      do {
        let result = try await Task.detached(priority: .userInitiated) {
          try TrackArrangementBuilder.derive(
            catalog: catalog,
            targetBundleID: targetBundleID,
            action: action
          )
        }.value
        let refreshed = try await Task.detached(priority: .userInitiated) {
          try ProjectLoader.inspect(catalog.rootURL)
        }.value
        let prepared = try await Task.detached(priority: .userInitiated) {
          try PreparedSelection.loadBundle(
            catalog: refreshed,
            bundleID: result.bundleID,
            preferredTrackID: result.selectedTrackID
          )
        }.value
        guard !Task.isCancelled, let self,
          self.trackManagementGeneration == generation,
          self.catalog?.rootURL == catalog.rootURL
        else {
          return
        }
        self.catalog = refreshed
        if self.selectedBundleID == targetBundleID {
          self.applyPreparedSelection(prepared)
          self.statusMessage =
            "已创建 \(self.bundleDisplayName(result.bundleID))："
            + "\(result.trackCount) 轨、\(result.noteCount) 个音符；原识别版本未修改"
        } else {
          self.statusMessage =
            "自定义版本已创建；你已切换版本，因此没有自动跳转"
        }
        self.refreshProjectLibrary()
      } catch is CancellationError {
        return
      } catch {
        guard let self else { return }
        self.present(error)
      }
    }
  }

  func waitForTrackManagementForTesting() async {
    await trackManagementTask?.value
  }

  public func selectPreviousReviewNote() {
    selectReviewNote(offset: -1)
  }

  public func selectNextReviewNote() {
    selectReviewNote(offset: 1)
  }

  public func createNoteAtPlayhead() {
    do {
      guard var editor else { return }
      let start = max(0, transport.currentTime)
      let beatDuration =
        rhythm.map {
          RhythmTimeline.beatDuration(at: start, rhythm: $0)
        } ?? 0.5
      let duration = min(4, max(0.08, beatDuration))
      let pitch =
        selectedNote?.pitchMIDI
        ?? editor.notes.map(\.pitchMIDI).sorted().dropFirst(
          editor.notes.count / 2
        ).first
        ?? 60
      let note = EditorNote(
        id: "app-created-\(UUID().uuidString.lowercased())",
        trackID: editor.selectedTrack.id,
        sourceTrackID: editor.selectedTrack.id,
        instrument: editor.selectedTrack.instrument,
        onsetSec: start,
        offsetSec: start + duration,
        pitchMIDI: pitch.rounded(),
        velocity: 80,
        confidence: nil,
        isMainMelodyCandidate:
          editor.selectedTrack.instrument?.lowercased() == "voice",
        sourceRunID: "amt-studio-manual-edit",
        sourceModel: "manual",
        sourceEventIDs: [],
        tags: ["app-created"],
        extra: [:]
      )
      try editor.create(note)
      try editor.save()
      self.editor = editor
      recordSave(editor)
      selectedNoteID = note.id
      statusMessage =
        "已在播放头新增 1 个音符，长度为当前一拍；可拖动或调整两端"
      errorMessage = nil
      updateMelodyCoverage()
      refreshTrailingCleanupDiagnostics()
      refreshMIDIPreview()
    } catch {
      present(error)
    }
  }

  public func seekToNextProjectReviewIssue() {
    let issues = projectReviewIssues
    guard !issues.isEmpty else { return }
    let issue: ProjectReviewIssue
    if let lastProjectReviewIssueID,
      let index = issues.firstIndex(where: { $0.id == lastProjectReviewIssueID })
    {
      issue = issues[(index + 1) % issues.count]
    } else {
      issue =
        issues.first(where: { $0.timeSec > transport.currentTime + 0.05 })
        ?? issues[0]
    }
    lastProjectReviewIssueID = issue.id
    transport.seek(to: max(0, issue.timeSec - 0.25))
    if editor?.selectedTrack.id == issue.trackID {
      selectedNoteID = issue.noteID
    } else {
      pendingSelectedTrackID = issue.trackID
      pendingSelectedNoteID = issue.noteID
      chooseTrack(issue.trackID)
    }
    let trackLabel =
      snapshot?.tracks.first(where: { $0.id == issue.trackID })
      .map { MelodyTrackSelector.displayLabel(for: $0) }
      ?? issue.trackID
    statusMessage =
      "已定位 \(trackLabel) · \(issue.kind.label) · \(formatClock(issue.timeSec))"
  }

  public func commit(_ note: EditorNote) {
    do {
      guard var editor else { return }
      try editor.update(note)
      try editor.save()
      self.editor = editor
      recordSave(editor)
      selectedNoteID = note.id
      statusMessage = "编辑已保存（原始模型输出未修改）"
      errorMessage = nil
      updateMelodyCoverage()
      refreshTrailingCleanupDiagnostics()
      refreshMIDIPreview()
    } catch {
      present(error)
    }
  }

  public func deleteSelectedNote() {
    do {
      guard var editor, let selectedNoteID else { return }
      try editor.delete(noteID: selectedNoteID)
      try editor.save()
      self.editor = editor
      recordSave(editor)
      self.selectedNoteID = editor.notes.first?.id
      statusMessage = "删除操作已记录，可撤销"
      errorMessage = nil
      updateMelodyCoverage()
      refreshTrailingCleanupDiagnostics()
      refreshMIDIPreview()
    } catch {
      present(error)
    }
  }

  public func undo() {
    do {
      guard var editor else { return }
      try editor.undo()
      try editor.save()
      self.editor = editor
      recordSave(editor)
      if let selectedNoteID,
        !editor.notes.contains(where: { $0.id == selectedNoteID })
      {
        self.selectedNoteID = editor.notes.first?.id
      }
      statusMessage = "已撤销并保存"
      errorMessage = nil
      updateMelodyCoverage()
      refreshTrailingCleanupDiagnostics()
      refreshMIDIPreview()
    } catch {
      present(error)
    }
  }

  public func redo() {
    do {
      guard var editor else { return }
      try editor.redo()
      try editor.save()
      self.editor = editor
      recordSave(editor)
      statusMessage = "已重做并保存"
      errorMessage = nil
      updateMelodyCoverage()
      refreshTrailingCleanupDiagnostics()
      refreshMIDIPreview()
    } catch {
      present(error)
    }
  }

  public func save() {
    do {
      guard var editor else { return }
      try editor.save()
      self.editor = editor
      recordSave(editor)
      statusMessage = "项目选择与编辑历史已保存"
      errorMessage = nil
    } catch {
      present(error)
    }
  }

  @discardableResult
  public func exportMIDI(to url: URL) -> MIDIExportReport? {
    do {
      guard let editor else { return nil }
      let report = try MIDIExporter.export(project: editor, to: url)
      statusMessage = "已导出 \(report.noteCount) 个音符：\(url.lastPathComponent)"
      errorMessage = nil
      return report
    } catch {
      present(error)
      return nil
    }
  }

  @discardableResult
  public func exportArrangementMIDI(to url: URL) -> MIDIExportReport? {
    do {
      guard let catalog, let snapshot else { return nil }
      guard
        let bundleID = catalog.bundles.first(
          where: { $0.canonicalProjectURL == snapshot.canonicalProjectURL }
        )?.id
      else {
        throw AMTProjectError.missingCanonicalBundle
      }
      let allTrackIDs = Set(snapshot.tracks.map(\.id))
      let includedTrackIDs = MelodyTrackSelector.resolveExclusiveVariant(
        from: allTrackIDs,
        tracks: snapshot.tracks,
        selectedTrackID: MelodyTrackSelector.preferred(in: snapshot.tracks)?.id
      )
      let report = try MIDIExporter.exportArrangement(
        snapshot: snapshot,
        bundleID: bundleID,
        to: url,
        includedTrackIDs: includedTrackIDs
      )
      statusMessage =
        "已导出 \(report.trackCount) 条音轨、\(report.noteCount) 个音符：\(url.lastPathComponent)"
      errorMessage = nil
      return report
    } catch {
      present(error)
      return nil
    }
  }

  @discardableResult
  public func exportCurrentMixMIDI(to url: URL) -> MIDIExportReport? {
    do {
      guard let catalog, let snapshot else { return nil }
      guard
        let bundleID = catalog.bundles.first(
          where: { $0.canonicalProjectURL == snapshot.canonicalProjectURL }
        )?.id
      else {
        throw AMTProjectError.missingCanonicalBundle
      }
      let report = try MIDIExporter.exportArrangement(
        snapshot: snapshot,
        bundleID: bundleID,
        to: url,
        includedTrackIDs: audibleTrackIDs,
        trackVolumes: effectiveTrackVolumes
      )
      statusMessage =
        "已导出当前混音：\(report.trackCount) 轨、\(report.noteCount) 个音符"
      errorMessage = nil
      return report
    } catch {
      present(error)
      return nil
    }
  }

  public func clearError() {
    errorMessage = nil
  }

  private func applyPreparedSelection(_ prepared: PreparedSelection) {
    let bundleChanged =
      snapshot?.canonicalProjectURL != prepared.snapshot.canonicalProjectURL
    if bundleChanged {
      midiPreviewRefresh?.cancel()
      midiPreviewGeneration = UUID()
      transport.stop()
      discardMIDIPreviewArtifact()
      restoreMixerSettings(for: prepared.snapshot)
      lastMelodyGapID = nil
    }
    snapshot = prepared.snapshot
    editor = prepared.editor
    lastSavedAt = prepared.editor?.persistedUpdatedAt
    if let editor = prepared.editor,
      pendingSelectedTrackID == editor.selectedTrack.id,
      let pendingSelectedNoteID,
      editor.notes.contains(where: { $0.id == pendingSelectedNoteID })
    {
      selectedNoteID = pendingSelectedNoteID
    } else {
      selectedNoteID = prepared.editor?.notes.first?.id
    }
    pendingSelectedTrackID = nil
    pendingSelectedNoteID = nil
    statusMessage = prepared.statusMessage
    errorMessage = nil
    if let editor = prepared.editor {
      transport.load(audioURL: editor.snapshot.audioURL)
      refreshMIDIPreview()
    }
    updateMelodyCoverage()
    refreshTrailingCleanupDiagnostics()
    if pendingFragmentRepairTrackID == prepared.editor?.selectedTrack.id {
      pendingFragmentRepairTrackID = nil
      performTrailingCleanup()
    }
  }

  private func applyPreparedProject(_ prepared: PreparedProject) {
    midiPreviewRefresh?.cancel()
    midiPreviewGeneration = UUID()
    transport.stop()
    discardMIDIPreviewArtifact()
    catalog = prepared.catalog
    snapshot = prepared.snapshot
    editor = prepared.editor
    lastSavedAt = prepared.editor?.persistedUpdatedAt
    selectedNoteID = prepared.editor?.notes.first?.id
    lastMelodyGapID = nil
    lastProjectReviewIssueID = nil
    pendingSelectedTrackID = nil
    pendingSelectedNoteID = nil
    statusMessage = prepared.statusMessage
    errorMessage = prepared.warning
    if persistRecentProject {
      defaults.set(prepared.catalog.rootURL.path, forKey: recentProjectKey)
    }
    if let snapshot = prepared.snapshot {
      restoreMixerSettings(for: snapshot)
    }
    if let editor = prepared.editor {
      transport.load(audioURL: editor.snapshot.audioURL)
      refreshMIDIPreview()
    }
    updateMelodyCoverage()
    refreshTrailingCleanupDiagnostics()
    betaGPUType = prepared.jobState?.slurmGPUType
    betaPartition = prepared.jobState?.slurmPartition
    betaGPUPreemptible = prepared.jobState?.gpuPreemptible ?? false
    betaGPUSelectionReason = prepared.jobState?.gpuSelectionReason
    betaGPUEstimatedWaitSeconds =
      prepared.jobState?.gpuEstimatedWaitSeconds
    if let state = prepared.jobState {
      betaProjectURL = prepared.catalog.rootURL
      betaJobID = state.jobID
      betaSlurmState = state.slurmState
      betaPipelineStage = state.pipelineStage
      betaTaskKind = state.taskKind
      activeComputeMode = ComputeMode.resolve(
        backend: state.backend,
        localDevice: state.localDevice
      )
      if prepared.catalog.bundles.isEmpty
        || !LocalProjectItem.terminalStates.contains(state.slurmState ?? "")
      {
        isShowingJobProgress = true
        rememberActiveBetaProject()
        startMonitoring(projectURL: prepared.catalog.rootURL)
      } else {
        isShowingJobProgress = false
        clearActiveBetaProject()
      }
    }
    refreshProjectLibrary()
    if let bundleID = pendingCompletedBundleID,
      let completedBundle = prepared.catalog.bundles.first(where: {
        $0.id == bundleID
      })
    {
      let trackID = pendingCompletedTrackID
      pendingCompletedBundleID = nil
      pendingCompletedTrackID = nil
      if completedBundle.isDefaultEligible {
        chooseBundle(bundleID, preferredTrackID: trackID)
      } else {
        statusMessage =
          "新补漏结果未通过主旋律准入，已保留当前安全版本"
        errorMessage =
          completedBundle.defaultExclusionReason
          ?? "新补漏结果未进入产品版本，没有自动覆盖主旋律"
      }
    }
    processSongQueueIfPossible()
  }

  private func refreshMIDIPreview() {
    guard let catalog, let snapshot, let editor else { return }
    guard
      let bundleID = catalog.bundles.first(
        where: { $0.canonicalProjectURL == snapshot.canonicalProjectURL }
      )?.id
    else {
      return
    }
    let includedTrackIDs = audibleTrackIDs
    guard !includedTrackIDs.isEmpty else {
      midiPreviewRefresh?.cancel()
      midiPreviewGeneration = UUID()
      transport.clearMIDI(message: "所有音轨已静音；请启用至少一条音轨。")
      discardMIDIPreviewArtifact()
      return
    }
    midiPreviewRefresh?.cancel()
    let generation = UUID()
    midiPreviewGeneration = generation
    let directory = FileManager.default.temporaryDirectory
      .appendingPathComponent("AMTStudioPreview", isDirectory: true)
    let previewID =
      midiPlaybackMode == .mix
      ? "mix"
      : editor.selectedTrack.id
    let safePreviewID = previewID.map {
      $0.isLetter || $0.isNumber || "-._".contains($0) ? $0 : "-"
    }.reduce(into: "") { $0.append($1) }
    let url = directory.appendingPathComponent(
      "\(editor.snapshot.baseFingerprint.prefix(16))-\(safePreviewID.prefix(48))-\(generation.uuidString).mid"
    )
    let volumes = effectiveTrackVolumes
    transport.beginMIDILoading()
    midiPreviewRefresh = Task { [weak self] in
      do {
        try await Task.sleep(for: .milliseconds(100))
        guard !Task.isCancelled else { return }
        _ = try await Task.detached(priority: .utility) {
          try MIDIExporter.exportArrangement(
            snapshot: snapshot,
            bundleID: bundleID,
            to: url,
            includedTrackIDs: includedTrackIDs,
            trackVolumes: volumes
          )
        }.value
        guard !Task.isCancelled, let self,
          self.midiPreviewGeneration == generation
        else {
          try? FileManager.default.removeItem(at: url)
          return
        }
        let previous = self.currentMIDIPreviewURL
        self.transport.loadMIDI(url: url)
        if self.transport.midiAvailable {
          self.currentMIDIPreviewURL = url
          if let previous, previous != url {
            try? FileManager.default.removeItem(at: previous)
          }
        } else {
          try? FileManager.default.removeItem(at: url)
        }
      } catch is CancellationError {
        try? FileManager.default.removeItem(at: url)
      } catch {
        guard let self, self.midiPreviewGeneration == generation else {
          return
        }
        self.transport.clearMIDI(
          message: "MIDI 预览暂不可用：\(error.localizedDescription)"
        )
      }
    }
  }

  private func recordSave(_ editor: EditorProject) {
    lastSavedAt = editor.persistedUpdatedAt ?? Date()
  }

  private func scheduleMIDIPreviewRefresh() {
    refreshMIDIPreview()
  }

  private var effectiveTrackVolumes: [String: Double] {
    trackVolumes.mapValues {
      min(1, max(0, $0 * midiMasterVolume))
    }
  }

  private func discardMIDIPreviewArtifact() {
    guard let currentMIDIPreviewURL else { return }
    try? FileManager.default.removeItem(at: currentMIDIPreviewURL)
    self.currentMIDIPreviewURL = nil
  }

  private func selectReviewNote(offset: Int) {
    let queue = reviewNotes
    guard !queue.isEmpty else { return }
    let targetIndex: Int
    if let selectedNoteID,
      let currentIndex = queue.firstIndex(where: { $0.id == selectedNoteID })
    {
      targetIndex = (currentIndex + offset + queue.count) % queue.count
    } else {
      targetIndex = offset < 0 ? queue.count - 1 : 0
    }
    let note = queue[targetIndex]
    selectedNoteID = note.id
    transport.seek(to: max(0, note.onsetSec - 0.25))
    statusMessage =
      "待复核音符 \(targetIndex + 1) / \(queue.count)，已定位到 \(note.onsetSec.formatted(.number.precision(.fractionLength(2)))) 秒"
  }

  private func present(_ error: Error) {
    errorMessage =
      (error as? LocalizedError)?.errorDescription
      ?? error.localizedDescription
    statusMessage = "操作失败"
  }

  private func startMonitoring(projectURL: URL) {
    rememberActiveBetaProject(projectURL)
    restartBetaMonitor()
  }

  private func restartBetaMonitor() {
    betaMonitor?.cancel()
    betaMonitor = Task { [weak self] in
      while !Task.isCancelled {
        guard !Task.isCancelled, let self else { return }
        if self.isBetaBusy {
          try? await Task.sleep(for: .seconds(1))
          continue
        }
        let paths = self.monitoredBetaProjectPaths.sorted()
        guard !paths.isEmpty else { return }
        for path in paths {
          guard !Task.isCancelled, !self.isBetaBusy else { break }
          await self.refreshMonitoredProject(
            URL(fileURLWithPath: path, isDirectory: true)
          )
          if self.hyakConnectionState == .loginRequired {
            return
          }
        }
        guard !self.monitoredBetaProjectPaths.isEmpty else {
          return
        }
        try? await Task.sleep(for: .seconds(20))
      }
    }
  }

  private func refreshMonitoredProject(_ projectURL: URL) async {
    do {
      let backend = try PrivateBetaBackend.locate()
      let response = try await Task.detached(priority: .utility) {
        try backend.refresh(projectURL: projectURL)
      }.value
      let currentPath =
        betaProjectURL?.standardizedFileURL.resolvingSymlinksInPath().path
      let refreshedPath =
        projectURL.standardizedFileURL.resolvingSymlinksInPath().path
      if currentPath == refreshedPath {
        try handleBetaResponse(response)
      } else {
        try validateBetaResponse(response)
        if ComputeMode.resolve(
          backend: response.backend,
          localDevice: response.localDevice
        ) == .hyak {
          hyakConnectionState = .connected
        }
        if ["succeeded", "failed", "cancelled"].contains(
          response.status ?? ""
        ) {
          forgetActiveBetaProject(projectURL)
          processSongQueueIfPossible()
        }
        refreshProjectLibrary()
      }
    } catch {
      presentBetaError(error)
    }
  }

  private func refreshBetaJob(projectURL: URL) async {
    do {
      let backend = try PrivateBetaBackend.locate()
      let response = try await Task.detached(priority: .utility) {
        try backend.refresh(projectURL: projectURL)
      }.value
      try handleBetaResponse(response)
      if activeComputeMode == .hyak {
        hyakConnectionState = .connected
      }
    } catch {
      presentBetaError(error)
    }
  }

  private func handleBetaResponse(
    _ response: PrivateBetaResponse
  ) throws {
    try validateBetaResponse(response)
    if let path = response.localProjectDir {
      betaProjectURL = URL(fileURLWithPath: path, isDirectory: true)
    }
    activeComputeMode = ComputeMode.resolve(
      backend: response.backend,
      localDevice: response.localDevice
    )
    betaTaskKind = response.taskKind ?? betaTaskKind
    betaJobID = response.jobID ?? betaJobID
    betaSlurmState = response.slurmState ?? betaSlurmState
    betaPipelineStage = response.pipelineStage ?? betaPipelineStage
    if activeComputeMode == .hyak {
      betaGPUType = response.slurmGPUType ?? betaGPUType
      betaPartition = response.slurmPartition ?? betaPartition
      betaGPUPreemptible =
        response.gpuPreemptible ?? betaGPUPreemptible
      betaGPUSelectionReason =
        response.gpuSelectionReason ?? betaGPUSelectionReason
      betaGPUEstimatedWaitSeconds =
        response.gpuEstimatedWaitSeconds
        ?? betaGPUEstimatedWaitSeconds
    } else {
      betaGPUType = nil
      betaPartition = nil
      betaGPUPreemptible = false
      betaGPUSelectionReason = nil
      betaGPUEstimatedWaitSeconds = nil
    }
    if betaTaskKind == "targeted_gap_recovery",
      let bundleID = response.bundleID
    {
      pendingCompletedBundleID = bundleID
      pendingCompletedTrackID =
        response.sourceTrackID ?? pendingCompletedTrackID
    }
    if betaTaskKind == "game_vocal_transcription",
      let bundleID = response.bundleID
    {
      pendingCompletedBundleID = bundleID
      pendingCompletedTrackID = "voice"
    }
    switch response.status {
    case "succeeded":
      guard let betaProjectURL else { return }
      isShowingJobProgress = false
      clearActiveBetaProject()
      openProject(betaProjectURL)
      statusMessage =
        betaTaskKind == "targeted_gap_recovery"
        ? response.recoveredCandidateNoteCount == 0
          ? "重算完成，但模型没有生成新音符；原音轨保持不变"
          : "所选空缺已重算；正在打开新识别版本"
        : betaTaskKind == "game_vocal_transcription"
          ? "GAME 主唱旋律单轨已取回；正在打开新版本"
          : activeComputeMode == .hyak
            ? "Hyak 识别流程完成，完整多轨与默认主旋律已取回"
            : "本机识别完成，完整多轨与默认主旋律已生成"
    case "failed", "cancelled":
      isShowingJobProgress = false
      clearActiveBetaProject()
      pendingCompletedBundleID = nil
      pendingCompletedTrackID = nil
      if response.status == "cancelled" {
        errorMessage = nil
        statusMessage = "本机计算已停止；未完成项目与日志已经保留"
      } else {
        let prefix =
          activeComputeMode == .hyak
          ? "Hyak 任务失败"
          : "本机任务失败"
        errorMessage =
          response.failureReason.map { "\(prefix)：\($0)" }
          ?? "\(prefix)；项目日志已经保留，可据此定位问题。"
        statusMessage = "识别失败"
      }
      processSongQueueIfPossible()
    case "running":
      rememberActiveBetaProject()
      switch betaPipelineStage {
      case "source_separation":
        statusMessage = "Hyak 正在用 BS-Roformer 分离主唱人声"
      case "game_vocal_transcription":
        statusMessage = "Hyak 正在用 GAME 识别主唱旋律"
      case "rhythm_analysis":
        statusMessage =
          betaTaskKind == "game_vocal_transcription"
          ? "GAME 主唱旋律已生成，正在分析速度与拍号"
          : "正在分析速度与拍号"
      case "targeted_gap_recovery":
        statusMessage =
          "\(activeComputeMode?.label ?? "计算任务")正在重算所选空缺（\(betaJobID ?? "未知")）"
      case "automatic_gap_recovery":
        statusMessage =
          "\(activeComputeMode?.label ?? "计算任务")正在自动补漏主旋律（\(betaJobID ?? "未知")）"
      case "gap_planning":
        statusMessage = "整曲多轨已生成，正在检查主旋律长缺口"
      case "packaging":
        statusMessage =
          betaTaskKind == "game_vocal_transcription"
          ? "GAME 识别已完成，正在生成单轨 MIDI 并取回 Mac"
          : "识别已完成，正在打包完整多轨"
      default:
        statusMessage =
          "\(activeComputeMode?.label ?? "计算任务")正在识别整首歌（\(betaJobID ?? "未知")）"
      }
    default:
      rememberActiveBetaProject()
      statusMessage =
        betaTaskKind == "targeted_gap_recovery"
        ? "\(activeComputeMode?.label ?? "计算任务")空缺重算已提交（\(betaSlurmState ?? "PENDING")）"
        : betaTaskKind == "game_vocal_transcription"
          ? "GAME 主唱旋律任务已排队（\(betaSlurmState ?? "PENDING")）"
          : activeComputeMode == .hyak
            ? "Hyak 任务已排队（\(betaSlurmState ?? "PENDING")）"
            : "本机后台任务正在启动"
    }
    refreshProjectLibrary()
  }

  private func validateBetaResponse(
    _ response: PrivateBetaResponse
  ) throws {
    guard response.ok else {
      if response.needsHyakLogin == true {
        throw PrivateBetaBackendError.hyakLoginRequired(
          response.error ?? "Hyak 登录已过期"
        )
      }
      throw PrivateBetaBackendError.operationFailed(
        response.error ?? "未知后台错误"
      )
    }
  }

  private func waitForHyakLogin() {
    connectionMonitor?.cancel()
    connectionMonitor = Task { [weak self] in
      guard let self else { return }
      for attempt in 0..<40 {
        if attempt > 0 {
          try? await Task.sleep(for: .seconds(3))
        }
        guard !Task.isCancelled else { return }
        if await self.probeHyakConnection(resumeJob: true) {
          return
        }
      }
      self.hyakConnectionState = .loginRequired
      self.statusMessage = "仍未连接 Hyak；请确认 Terminal 中的密码和 Duo 已完成"
    }
  }

  private func probeHyakConnection(resumeJob: Bool) async -> Bool {
    hyakConnectionState = .checking
    do {
      let backend = try PrivateBetaBackend.locate()
      let response = try await Task.detached(priority: .utility) {
        try backend.connection()
      }.value
      guard response.ok, response.status == "connected" else {
        hyakConnectionState = .loginRequired
        if response.needsHyakLogin == true {
          statusMessage = "Hyak 登录已过期；远端作业不会停止，请重新连接"
        }
        return false
      }
      hyakConnectionState = .connected
      statusMessage = "Hyak 已连接\(response.host.map { "（\($0)）" } ?? "")"
      errorMessage = nil
      if resumeJob, let betaProjectURL {
        await refreshBetaJob(projectURL: betaProjectURL)
      }
      if resumeJob, !monitoredBetaProjectPaths.isEmpty {
        restartBetaMonitor()
      }
      processSongQueueIfPossible()
      return true
    } catch {
      hyakConnectionState = .loginRequired
      statusMessage = "Hyak 登录已过期；远端作业不会停止，请重新连接"
      return false
    }
  }

  private func presentBetaError(_ error: Error) {
    if let backendError = error as? PrivateBetaBackendError,
      case .hyakLoginRequired = backendError
    {
      hyakConnectionState = .loginRequired
      errorMessage = nil
      statusMessage =
        activeProjectTaskCount > 0
        ? "Hyak 登录已过期；作业仍在运行。重新连接后会自动恢复。"
        : "Hyak 尚未连接；请先在 Terminal 完成密码与 Duo，再重新提交。"
      return
    }
    present(error)
  }

  private func updateQueuedSong(
    _ id: UUID,
    state: SongQueueState,
    failureMessage: String?
  ) {
    guard let index = songQueue.firstIndex(where: { $0.id == id }) else {
      return
    }
    songQueue[index].state = state
    songQueue[index].failureMessage = failureMessage
    persistSongQueue()
  }

  private func persistSongQueue() {
    guard let data = try? JSONEncoder().encode(songQueue) else { return }
    defaults.set(data, forKey: songQueueKey)
  }

  private static func restoreSongQueue(from data: Data?) -> [SongQueueItem] {
    guard
      let data,
      var restored = try? JSONDecoder().decode(
        [SongQueueItem].self,
        from: data
      )
    else {
      return []
    }
    for index in restored.indices where restored[index].state == .submitting {
      restored[index].state = .failed
      restored[index].failureMessage =
        "软件上次在提交确认前关闭。为避免重复任务，请确认后手动重试。"
    }
    return restored
  }

  private func rememberActiveBetaProject(_ projectURL: URL? = nil) {
    guard let projectURL = projectURL ?? betaProjectURL else { return }
    let path =
      projectURL.standardizedFileURL.resolvingSymlinksInPath().path
    monitoredBetaProjectPaths.insert(path)
    guard persistRecentProject else { return }
    defaults.set(path, forKey: activeBetaProjectKey)
    defaults.set(
      monitoredBetaProjectPaths.sorted(),
      forKey: activeBetaProjectsKey
    )
  }

  private func clearActiveBetaProject() {
    guard let betaProjectURL else { return }
    forgetActiveBetaProject(betaProjectURL)
  }

  private func forgetActiveBetaProject(_ projectURL: URL) {
    let path =
      projectURL.standardizedFileURL.resolvingSymlinksInPath().path
    monitoredBetaProjectPaths.remove(path)
    guard persistRecentProject else { return }
    defaults.set(
      monitoredBetaProjectPaths.sorted(),
      forKey: activeBetaProjectsKey
    )
    if defaults.string(forKey: activeBetaProjectKey) == path {
      if let replacement = monitoredBetaProjectPaths.sorted().first {
        defaults.set(replacement, forKey: activeBetaProjectKey)
      } else {
        defaults.removeObject(forKey: activeBetaProjectKey)
      }
    }
  }

  func forgetActiveProjectForTesting(_ projectURL: URL) {
    forgetActiveBetaProject(projectURL)
  }

  private func restoreMixerSettings(for snapshot: ProjectSnapshot) {
    let available = Set(snapshot.tracks.map(\.id))
    mutedTrackIDs = []
    soloTrackIDs = []
    trackVolumes = Dictionary(
      uniqueKeysWithValues: snapshot.tracks.map { ($0.id, 1) }
    )
    midiPlaybackMode = .mix
    guard
      let data = defaults.data(forKey: mixerSettingsKey(snapshot)),
      let settings = try? JSONDecoder().decode(
        MixerSettings.self,
        from: data
      )
    else {
      return
    }
    mutedTrackIDs = Set(settings.mutedTrackIDs).intersection(available)
    soloTrackIDs = Set(settings.soloTrackIDs).intersection(available)
    for (trackID, volume) in settings.trackVolumes
    where available.contains(trackID) && volume.isFinite {
      trackVolumes[trackID] = min(1, max(0, volume))
    }
    midiPlaybackMode =
      MIDIPlaybackMode(rawValue: settings.playbackMode) ?? .mix
  }

  private func saveMixerSettings() {
    guard let snapshot else { return }
    let settings = MixerSettings(
      playbackMode: midiPlaybackMode.rawValue,
      mutedTrackIDs: mutedTrackIDs.sorted(),
      soloTrackIDs: soloTrackIDs.sorted(),
      trackVolumes: trackVolumes
    )
    if let data = try? JSONEncoder().encode(settings) {
      defaults.set(data, forKey: mixerSettingsKey(snapshot))
    }
  }

  private func mixerSettingsKey(_ snapshot: ProjectSnapshot) -> String {
    "AMTStudio.mixer.\(snapshot.baseFingerprint)"
  }

  private static func restoreProjectBookmark(
    path: String,
    defaults: UserDefaults,
    key: String
  ) -> (url: URL, accessing: Bool)? {
    guard
      let data = defaults.dictionary(forKey: key)?[path] as? Data
    else {
      return nil
    }
    do {
      var stale = false
      let url = try URL(
        resolvingBookmarkData: data,
        options: [.withSecurityScope],
        relativeTo: nil,
        bookmarkDataIsStale: &stale
      )
      if stale {
        let refreshed = try url.bookmarkData(
          options: [.withSecurityScope],
          includingResourceValuesForKeys: nil,
          relativeTo: nil
        )
        var bookmarks =
          defaults.dictionary(forKey: key)?
          .compactMapValues { $0 as? Data } ?? [:]
        bookmarks[path] = refreshed
        defaults.set(bookmarks, forKey: key)
      }
      return (url, url.startAccessingSecurityScopedResource())
    } catch {
      return nil
    }
  }

  private static func recycleProject(at url: URL) async throws {
    try await withCheckedThrowingContinuation {
      (continuation: CheckedContinuation<Void, Error>) in
      NSWorkspace.shared.recycle([url]) { _, error in
        if let error {
          continuation.resume(throwing: error)
        } else {
          continuation.resume()
        }
      }
    }
  }

  private func finishProjectRemoval(
    _ project: LocalProjectItem,
    target: URL
  ) {
    libraryProjects.removeAll { $0.id == project.id }
    let resolvedTarget = target.standardizedFileURL.resolvingSymlinksInPath()
    guard
      catalog?.rootURL.standardizedFileURL.resolvingSymlinksInPath()
        .path == resolvedTarget.path
    else {
      statusMessage = "已把“\(project.title)”移到废纸篓"
      refreshProjectLibrary()
      return
    }

    projectLoadTask?.cancel()
    selectionLoadTask?.cancel()
    midiPreviewRefresh?.cancel()
    transport.stop()
    discardMIDIPreviewArtifact()
    catalog = nil
    snapshot = nil
    editor = nil
    selectedNoteID = nil
    melodyGaps = []
    selectedGapIDs = []
    trailingCleanupSummaries = [:]
    lastSavedAt = nil
    defaults.removeObject(forKey: recentProjectKey)
    if betaProjectURL?.standardizedFileURL.resolvingSymlinksInPath().path
      == resolvedTarget.path
    {
      let removedProjectURL = betaProjectURL
      if let removedProjectURL {
        forgetActiveBetaProject(removedProjectURL)
      }
      betaProjectURL = nil
      betaJobID = nil
      betaSlurmState = nil
      betaPipelineStage = nil
      betaTaskKind = nil
      betaGPUType = nil
      betaPartition = nil
      betaGPUPreemptible = false
      betaGPUSelectionReason = nil
      betaGPUEstimatedWaitSeconds = nil
      activeComputeMode = nil
      if monitoredBetaProjectPaths.isEmpty {
        betaMonitor?.cancel()
      } else {
        restartBetaMonitor()
      }
    }
    statusMessage = "已把“\(project.title)”移到废纸篓"
    errorMessage = nil
    refreshProjectLibrary()
  }
}

private struct MixerSettings: Codable {
  let playbackMode: String
  let mutedTrackIDs: [String]
  let soloTrackIDs: [String]
  let trackVolumes: [String: Double]
}

private struct PrivateBetaJobState: Decodable, Sendable {
  let jobID: String?
  let bundleID: String?
  let sourceBundleID: String?
  let sourceTrackID: String?
  let slurmState: String?
  let pipelineStage: String?
  let backend: String?
  let localDevice: String?
  let taskKind: String?
  let slurmGPUType: String?
  let slurmPartition: String?
  let gpuPreemptible: Bool?
  let gpuSelectionReason: String?
  let gpuEstimatedWaitSeconds: Int?
  let submittedAt: String?

  enum CodingKeys: String, CodingKey {
    case jobID = "job_id"
    case bundleID = "bundle_id"
    case sourceBundleID = "source_bundle_id"
    case sourceTrackID = "source_track_id"
    case slurmState = "slurm_state"
    case pipelineStage = "pipeline_stage"
    case backend
    case localDevice = "local_device"
    case taskKind = "task_kind"
    case slurmGPUType = "slurm_gpu_type"
    case slurmPartition = "slurm_partition"
    case gpuPreemptible = "gpu_preemptible"
    case gpuSelectionReason = "gpu_selection_reason"
    case gpuEstimatedWaitSeconds = "gpu_estimated_wait_seconds"
    case submittedAt = "submitted_at"
  }
}

private struct PreparedSelection: Sendable {
  let snapshot: ProjectSnapshot
  let editor: EditorProject?
  let statusMessage: String

  static func loadBundle(
    catalog: ProjectCatalog,
    bundleID: String,
    preferredTrackID: String? = nil
  ) throws -> PreparedSelection {
    let snapshot = try ProjectLoader.open(catalog, bundleID: bundleID)
    let preferredTrack =
      preferredTrackID.flatMap { id in
        snapshot.tracks.first(where: { $0.id == id })
      }
      ?? MelodyTrackSelector.preferred(in: snapshot.tracks)
      ?? (snapshot.tracks.count == 1 ? snapshot.tracks[0] : nil)
    guard let preferredTrack else {
      return PreparedSelection(
        snapshot: snapshot,
        editor: nil,
        statusMessage: "已打开完整多轨；请选择要编辑的音轨"
      )
    }
    return try loadTrack(
      snapshot: snapshot,
      bundleID: bundleID,
      trackID: preferredTrack.id
    )
  }

  static func loadTrack(
    snapshot: ProjectSnapshot,
    bundleID: String,
    trackID: String
  ) throws -> PreparedSelection {
    var editor = try EditorProject(
      snapshot: snapshot,
      bundleID: bundleID,
      selectedTrackID: trackID
    )
    let restoredCompatibleEdits = editor.restoredFromCompatibleVersion
    let repairedCount: Int
    if let duration =
      snapshot.manifest.canonicalAudio.metadata?.durationSec
    {
      repairedCount = try editor.repairLegacySustainOverflow(
        timelineEnd: duration
      )
      if repairedCount > 0 {
        try editor.save()
      }
    } else {
      repairedCount = 0
    }
    if restoredCompatibleEdits {
      try editor.save()
    } else {
      try? editor.saveWorkspaceSelection()
    }
    let label = MelodyTrackSelector.displayLabel(for: editor.selectedTrack)
    let repairMessage =
      repairedCount > 0
      ? "；已把 \(repairedCount) 个旧版结尾延音截到真实音频终点"
      : ""
    let restoredMessage =
      restoredCompatibleEdits
      ? "；已恢复上一识别版本的人工修改"
      : ""
    return PreparedSelection(
      snapshot: snapshot,
      editor: editor,
      statusMessage:
        "音轨 \(label)，\(editor.notes.count) 个音符\(repairMessage)\(restoredMessage)"
    )
  }
}

private struct PreparedProject: Sendable {
  let catalog: ProjectCatalog
  let snapshot: ProjectSnapshot?
  let editor: EditorProject?
  let jobState: PrivateBetaJobState?
  let statusMessage: String
  let warning: String?

  static func load(_ url: URL) throws -> PreparedProject {
    let catalog = try ProjectLoader.inspect(url)
    let stateURL = catalog.rootURL.appendingPathComponent(
      "app/private_beta_job.json"
    )
    let jobState =
      try? JSONDecoder().decode(
        PrivateBetaJobState.self,
        from: Data(contentsOf: stateURL)
      )

    var warning: String?
    let workspace: EditorWorkspace?
    do {
      workspace = try EditorProject.loadWorkspace(
        projectURL: catalog.rootURL
      )
    } catch {
      workspace = nil
      warning =
        "旧编辑状态无法读取，已改用当前校验结果："
        + ((error as? LocalizedError)?.errorDescription
          ?? error.localizedDescription)
    }
    let rejectedCompletedBundle =
      jobState?.bundleID.flatMap { bundleID in
        catalog.bundles.first(where: {
          $0.id == bundleID && !$0.isDefaultEligible
        })
      }
    let recoverySourceBundle =
      rejectedCompletedBundle.flatMap { _ in
        jobState?.sourceBundleID.flatMap { sourceBundleID in
          catalog.bundles.first(where: {
            $0.id == sourceBundleID && $0.isDefaultEligible
          })
        }
      }
    if let workspace,
      let workspaceBundle = catalog.bundles.first(where: {
        $0.id == workspace.canonicalBundleID
      }),
      !workspaceBundle.isDefaultEligible
    {
      warning =
        workspaceBundle.defaultExclusionReason
        ?? "上次打开的是实验中间结果，已改用可用产品版本"
    } else if let workspace {
      do {
        guard workspace.projectID == catalog.manifest.projectID,
          let bundle = catalog.bundles.first(where: {
            $0.id == workspace.canonicalBundleID
          }),
          try ProjectLoader.sha256(bundle.canonicalProjectURL)
            == workspace.canonicalProjectSHA256
        else {
          throw AMTProjectError.editSessionMismatch
        }
        let snapshot = try ProjectLoader.open(
          catalog,
          bundleID: workspace.canonicalBundleID
        )
        guard
          snapshot.tracks.contains(where: {
            $0.id == workspace.selectedTrackID
          })
        else {
          throw AMTProjectError.editSessionMismatch
        }
        var editor = try EditorProject(
          snapshot: snapshot,
          bundleID: workspace.canonicalBundleID,
          selectedTrackID: workspace.selectedTrackID
        )
        if editor.restoredFromCompatibleVersion {
          try editor.save()
        }
        return PreparedProject(
          catalog: catalog,
          snapshot: snapshot,
          editor: editor,
          jobState: jobState,
          statusMessage: projectStatus(editor: editor),
          warning: nil
        )
      } catch {
        warning =
          "旧编辑状态无法恢复，已改用当前校验结果："
          + ((error as? LocalizedError)?.errorDescription
            ?? error.localizedDescription)
      }
    }

    guard
      let bundle =
        recoverySourceBundle
        ?? catalog.bundles.filter(\.isDefaultEligible).max(by: {
          if $0.modifiedAt == $1.modifiedAt {
            return $0.id < $1.id
          }
          return $0.modifiedAt < $1.modifiedAt
        })
    else {
      return PreparedProject(
        catalog: catalog,
        snapshot: nil,
        editor: nil,
        jobState: jobState,
        statusMessage: catalog.bundles.isEmpty
          ? "项目还没有可打开的识别结果"
          : "当前没有可用产品版本",
        warning: warning
      )
    }
    let snapshot = try ProjectLoader.open(catalog, bundleID: bundle.id)
    let preferredTrack =
      MelodyTrackSelector.preferred(in: snapshot.tracks)
      ?? (snapshot.tracks.count == 1 ? snapshot.tracks[0] : nil)
    let editor: EditorProject?
    if let preferredTrack {
      var opened = try EditorProject(
        snapshot: snapshot,
        bundleID: bundle.id,
        selectedTrackID: preferredTrack.id
      )
      if opened.restoredFromCompatibleVersion {
        try opened.save()
      } else {
        try? opened.saveWorkspaceSelection()
      }
      editor = opened
    } else {
      editor = nil
    }
    return PreparedProject(
      catalog: catalog,
      snapshot: snapshot,
      editor: editor,
      jobState: jobState,
      statusMessage: editor.map { projectStatus(editor: $0) }
        ?? "已打开完整多轨；请选择要编辑的音轨",
      warning: warning
    )
  }

  private static func projectStatus(editor: EditorProject) -> String {
    if editor.selectedTrack.id == "voice_enhanced" {
      return "已打开增强主唱；原始 voice 与补漏候选仍可单独切换"
    }
    if editor.selectedTrack.id == "voice_auto_enhanced" {
      return "已打开自动增强主旋律（Beta）"
    }
    if editor.selectedTrack.instrument?.lowercased() == "voice" {
      return "已打开 voice 主唱候选；长空缺会单独提示，不再把它冒充完整主旋律"
    }
    return "已打开音轨 \(editor.selectedTrack.label)，\(editor.notes.count) 个音符"
  }
}

enum LocalProjectLibrary {
  static func validatedTrashTarget(
    _ project: LocalProjectItem,
    rootURL: URL
  ) throws -> URL {
    guard project.canMoveToTrash else {
      throw LocalProjectLibraryError.activeJob
    }
    let root = rootURL.standardizedFileURL.resolvingSymlinksInPath()
    let candidate = project.url.standardizedFileURL
    let values = try candidate.resourceValues(
      forKeys: [.isDirectoryKey, .isSymbolicLinkKey]
    )
    let target = candidate.resolvingSymlinksInPath()
    guard values.isDirectory == true, values.isSymbolicLink != true,
      target.path != root.path,
      target.deletingLastPathComponent().path == root.path
    else {
      throw LocalProjectLibraryError.unsafeTarget
    }
    let manifestURL = target.appendingPathComponent("manifest.json")
    guard
      let manifest = try? JSONDecoder().decode(
        ProjectManifest.self,
        from: Data(contentsOf: manifestURL)
      ),
      manifest.projectID == project.projectID
    else {
      throw LocalProjectLibraryError.projectMismatch
    }
    let stateURL = target.appendingPathComponent(
      "app/private_beta_job.json"
    )
    if FileManager.default.fileExists(atPath: stateURL.path) {
      guard
        let state = try? JSONDecoder().decode(
          PrivateBetaJobState.self,
          from: Data(contentsOf: stateURL)
        ),
        let slurmState = state.slurmState,
        LocalProjectItem.terminalStates.contains(slurmState)
      else {
        throw LocalProjectLibraryError.activeJob
      }
    }
    return target
  }

  static func scan(rootURL: URL) throws -> [LocalProjectItem] {
    guard FileManager.default.fileExists(atPath: rootURL.path) else {
      return []
    }
    let children = try FileManager.default.contentsOfDirectory(
      at: rootURL,
      includingPropertiesForKeys: [
        .isDirectoryKey,
        .contentModificationDateKey,
      ],
      options: [.skipsHiddenFiles]
    )
    var projects: [LocalProjectItem] = []
    for child in children {
      guard
        let values = try? child.resourceValues(
          forKeys: [.isDirectoryKey, .contentModificationDateKey]
        )
      else {
        continue
      }
      guard values.isDirectory == true else { continue }
      let manifestURL = child.appendingPathComponent("manifest.json")
      guard FileManager.default.fileExists(atPath: manifestURL.path),
        let manifest = try? JSONDecoder().decode(
          ProjectManifest.self,
          from: Data(contentsOf: manifestURL)
        )
      else {
        continue
      }
      let exportsURL = child.appendingPathComponent("exports")
      let hasResults =
        ((try? FileManager.default.contentsOfDirectory(
          at: exportsURL,
          includingPropertiesForKeys: nil
        )) ?? [])
        .contains {
          FileManager.default.fileExists(
            atPath: $0.appendingPathComponent("bundle_manifest.json").path
          )
        }
      let stateURL = child.appendingPathComponent(
        "app/private_beta_job.json"
      )
      let state =
        try? JSONDecoder().decode(
          PrivateBetaJobState.self,
          from: Data(contentsOf: stateURL)
        )
      let modifiedAt =
        [
          values.contentModificationDate,
          modificationDate(at: manifestURL),
          modificationDate(at: stateURL),
          newestBundleModificationDate(in: exportsURL),
        ].compactMap { $0 }.max() ?? .distantPast
      projects.append(
        LocalProjectItem(
          projectID: manifest.projectID,
          title: manifest.title ?? manifest.projectID,
          url: child,
          modifiedAt: modifiedAt,
          hasResults: hasResults,
          jobState: state?.slurmState,
          durationSeconds: manifest.canonicalAudio.metadata?.durationSec,
          submittedAt: parseBackendDate(state?.submittedAt),
          pipelineStage: state?.pipelineStage,
          taskKind: state?.taskKind,
          gpuType: state?.slurmGPUType,
          estimatedWaitSeconds: state?.gpuEstimatedWaitSeconds
        )
      )
    }
    return projects.sorted {
      if $0.hasActiveJob != $1.hasActiveJob {
        return $0.hasActiveJob
      }
      if $0.hasResults != $1.hasResults {
        return $0.hasResults
      }
      if $0.modifiedAt == $1.modifiedAt {
        return $0.title.localizedStandardCompare($1.title)
          == .orderedAscending
      }
      return $0.modifiedAt > $1.modifiedAt
    }
  }

  private static func modificationDate(at url: URL) -> Date? {
    try? url.resourceValues(
      forKeys: [.contentModificationDateKey]
    ).contentModificationDate
  }

  private static func parseBackendDate(_ value: String?) -> Date? {
    guard let value else { return nil }
    let fractional = ISO8601DateFormatter()
    fractional.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
    if let date = fractional.date(from: value) {
      return date
    }
    return ISO8601DateFormatter().date(from: value)
  }

  private static func newestBundleModificationDate(in exportsURL: URL) -> Date? {
    let bundles =
      (try? FileManager.default.contentsOfDirectory(
        at: exportsURL,
        includingPropertiesForKeys: [.isDirectoryKey],
        options: [.skipsHiddenFiles]
      )) ?? []
    return bundles.compactMap { bundle in
      modificationDate(
        at: bundle.appendingPathComponent("bundle_manifest.json")
      )
    }.max()
  }
}

private enum LocalProjectLibraryError: LocalizedError {
  case activeJob
  case unsafeTarget
  case projectMismatch

  var errorDescription: String? {
    switch self {
    case .activeJob:
      "正在排队或识别的项目不能删除"
    case .unsafeTarget:
      "拒绝删除音乐库之外的目录或符号链接"
    case .projectMismatch:
      "项目身份与目录不匹配，已拒绝删除"
    }
  }
}

enum ConfidenceReviewQueue {
  static func notes(
    from notes: [EditorNote],
    threshold: Double
  ) -> [EditorNote] {
    let boundedThreshold = min(1, max(0, threshold))
    return
      notes
      .filter { note in
        guard let confidence = note.confidence else { return false }
        return confidence <= boundedThreshold
      }
      .sorted { first, second in
        guard first.confidence == second.confidence else {
          return (first.confidence ?? 1) < (second.confidence ?? 1)
        }
        guard first.onsetSec == second.onsetSec else {
          return first.onsetSec < second.onsetSec
        }
        return first.id < second.id
      }
  }
}

enum MelodyCoverageAnalyzer {
  static func gaps(
    voiceNotes: [EditorNote],
    allNotes: [EditorNote],
    voiceTrackID: String,
    duration: Double,
    minimumGapDuration: Double = 3
  ) -> [MelodyGap] {
    guard duration.isFinite, duration > 0,
      minimumGapDuration.isFinite, minimumGapDuration > 0
    else {
      return []
    }
    var merged: [(start: Double, end: Double)] = []
    for note in voiceNotes.sorted(by: {
      ($0.onsetSec, $0.offsetSec, $0.id)
        < ($1.onsetSec, $1.offsetSec, $1.id)
    }) {
      guard note.onsetSec < duration else { continue }
      let start = max(0, note.onsetSec)
      let end = min(duration, note.offsetSec)
      guard end > start else { continue }
      if let last = merged.last, start <= last.end {
        merged[merged.count - 1].end = max(last.end, end)
      } else {
        merged.append((start, end))
      }
    }

    var ranges: [(Double, Double)] = []
    var cursor = 0.0
    for interval in merged {
      if interval.start - cursor >= minimumGapDuration {
        ranges.append((cursor, interval.start))
      }
      cursor = max(cursor, interval.end)
    }
    if duration - cursor >= minimumGapDuration {
      ranges.append((cursor, duration))
    }

    return ranges.map { start, end in
      let candidates = allNotes.filter {
        $0.trackID != voiceTrackID
          && $0.onsetSec < end
          && $0.offsetSec > start
      }
      return MelodyGap(
        startSec: start,
        endSec: end,
        otherTrackCount: Set(candidates.map(\.trackID)).count,
        otherNoteCount: candidates.count
      )
    }
  }
}

private func formatClock(_ seconds: Double) -> String {
  let bounded = max(0, seconds)
  let minutes = Int(bounded) / 60
  let remainder = Int(bounded) % 60
  return String(format: "%d:%02d", minutes, remainder)
}
