import AppKit
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
    default:
      track.instrument?.lowercased() == "voice"
        ? "voice 主唱候选"
        : track.label
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

  public var id: String {
    url.path
  }

  public var stateLabel: String {
    switch jobState {
    case "RUNNING": "识别中"
    case "PENDING", "CONFIGURING": "排队中"
    case "FAILED", "CANCELLED": "任务失败"
    case "COMPLETED": hasResults ? "可打开" : "正在取回"
    default: hasResults ? "可打开" : "尚无结果"
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
  @Published public private(set) var betaProjectURL: URL?
  @Published public private(set) var isBetaBusy = false
  @Published public private(set) var hyakConnectionState: HyakConnectionState = .unknown
  @Published public private(set) var midiPlaybackMode: MIDIPlaybackMode = .mix
  @Published public private(set) var mutedTrackIDs = Set<String>()
  @Published public private(set) var soloTrackIDs = Set<String>()
  @Published public private(set) var trackVolumes: [String: Double] = [:]
  @Published public private(set) var midiMasterVolume = 1.0
  @Published public private(set) var libraryProjects: [LocalProjectItem] = []
  @Published public private(set) var isLoadingProject = false
  @Published public private(set) var isRefreshingLibrary = false
  @Published public private(set) var isLoadingSelection = false
  @Published public private(set) var melodyGaps: [MelodyGap] = []
  @Published public private(set) var showMelodyVersions = false

  public let transport = AudioTransport()

  private let defaults: UserDefaults
  private let persistRecentProject: Bool
  private let recentProjectKey = "AMTStudio.recentProjectPath"
  private let activeBetaProjectKey = "AMTStudio.activeBetaProjectPath"
  private let originalVolumeKey = "AMTStudio.originalVolume"
  private let midiMasterVolumeKey = "AMTStudio.midiMasterVolume"
  private let projectBookmarksKey = "AMTStudio.projectBookmarks"
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
  private var selectionLoadTask: Task<Void, Never>?
  private var selectionLoadGeneration = UUID()

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
    if let initialProjectURL {
      pendingInitialProjectURL = initialProjectURL
    } else if restoreRecent,
      let path = defaults.string(forKey: activeBetaProjectKey),
      FileManager.default.fileExists(atPath: path)
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
    guard let pendingInitialProjectURL else { return }
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

  public func checkHyakConnection() {
    connectionMonitor?.cancel()
    connectionMonitor = Task { [weak self] in
      guard let self else { return }
      _ = await self.probeHyakConnection(resumeJob: true)
    }
  }

  public func transcribeSong(_ audioURL: URL) {
    guard !isBetaBusy else { return }
    let accessing = audioURL.startAccessingSecurityScopedResource()
    isBetaBusy = true
    statusMessage = "正在准备音频、上传 Hyak 并提交 GPU 任务…"
    errorMessage = nil
    Task {
      do {
        let backend = try PrivateBetaBackend.locate()
        let response = try await Task.detached(priority: .userInitiated) {
          try backend.start(audioURL: audioURL)
        }.value
        try handleBetaResponse(response)
        hyakConnectionState = .connected
        if let betaProjectURL {
          startMonitoring(projectURL: betaProjectURL)
        }
      } catch {
        presentBetaError(error)
      }
      if accessing {
        audioURL.stopAccessingSecurityScopedResource()
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
    }
  }

  public var hasActiveBetaJob: Bool {
    betaProjectURL != nil
      && !["COMPLETED", "FAILED", "CANCELLED"].contains(
        betaSlurmState ?? ""
      )
  }

  public var bundleChoices: [CanonicalBundleChoice] {
    catalog?.bundles ?? []
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

  public var visibleTrackChoices: [EditorTrack] {
    guard !showMelodyVersions else { return trackChoices }
    return trackChoices.filter {
      !["voice_raw", "voice_gap_candidate"].contains($0.id)
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
    editor?.notes ?? []
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

  private func updateMelodyCoverage() {
    guard let snapshot else {
      melodyGaps = []
      return
    }
    let selectedVoiceTrack =
      editor?.selectedTrack.instrument?.lowercased() == "voice"
      ? editor?.selectedTrack
      : nil
    guard
      let voiceTrack =
        selectedVoiceTrack
        ?? MelodyTrackSelector.preferred(in: snapshot.tracks)
    else {
      melodyGaps = []
      return
    }
    let voiceNotes =
      editor?.selectedTrack.id == voiceTrack.id
      ? notes
      : snapshot.notes.filter { $0.trackID == voiceTrack.id }
    let duration = max(
      transport.duration,
      snapshot.notes.map(\.offsetSec).max() ?? 0
    )
    melodyGaps = MelodyCoverageAnalyzer.gaps(
      voiceNotes: voiceNotes,
      allNotes: snapshot.notes,
      voiceTrackID: voiceTrack.id,
      duration: duration
    )
  }

  public var melodyGapDuration: Double {
    melodyGaps.reduce(0) { $0 + $1.duration }
  }

  public var melodyCoverageTrackLabel: String {
    guard let snapshot else { return "主唱候选" }
    let track =
      editor?.selectedTrack.instrument?.lowercased() == "voice"
      ? editor?.selectedTrack
      : MelodyTrackSelector.preferred(in: snapshot.tracks)
    return track.map(MelodyTrackSelector.displayLabel) ?? "主唱候选"
  }

  public var hasEnhancedVoiceTrack: Bool {
    snapshot?.tracks.contains(where: {
      ["voice_enhanced", "voice_auto_enhanced"].contains($0.id)
    }) == true
  }

  public func setShowMelodyVersions(_ isVisible: Bool) {
    showMelodyVersions = isVisible
    guard !isVisible,
      let editor,
      ["voice_raw", "voice_gap_candidate"].contains(editor.selectedTrack.id),
      let preferred = snapshot.flatMap({
        MelodyTrackSelector.preferred(in: $0.tracks)
      })
    else {
      return
    }
    chooseTrack(preferred.id)
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
      "已定位 voice 疑似空缺 \(formatClock(next.startSec))–\(formatClock(next.endSec))；可独奏其他轨寻找补全候选"
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
    selectionLoadGeneration = UUID()
    isLoadingSelection = false
    let generation = UUID()
    projectLoadGeneration = generation
    isLoadingProject = true
    melodyGaps = []
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
    transport.stop()
    discardMIDIPreviewArtifact()
    restoreMixerSettings(for: snapshot)
    updateMelodyCoverage()
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

  public func chooseBundle(_ id: String) {
    guard let catalog else { return }
    selectionLoadTask?.cancel()
    let generation = UUID()
    selectionLoadGeneration = generation
    isLoadingSelection = true
    statusMessage = "正在后台打开识别版本 \(id)…"
    selectionLoadTask = Task { [weak self] in
      do {
        let prepared = try await Task.detached(priority: .userInitiated) {
          try PreparedSelection.loadBundle(catalog: catalog, bundleID: id)
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
    selectedNoteID = editor.notes.first?.id
    statusMessage = "音轨 \(editor.selectedTrack.label)，\(editor.notes.count) 个音符"
    errorMessage = nil
    transport.load(audioURL: snapshot.audioURL)
    updateMelodyCoverage()
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
        self.present(error)
      }
      if let self, self.selectionLoadGeneration == generation {
        self.isLoadingSelection = false
      }
    }
  }

  public func selectPreviousReviewNote() {
    selectReviewNote(offset: -1)
  }

  public func selectNextReviewNote() {
    selectReviewNote(offset: 1)
  }

  public func commit(_ note: EditorNote) {
    do {
      guard var editor else { return }
      try editor.update(note)
      try editor.save()
      self.editor = editor
      selectedNoteID = note.id
      statusMessage = "编辑已保存（原始模型输出未修改）"
      errorMessage = nil
      updateMelodyCoverage()
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
      self.selectedNoteID = editor.notes.first?.id
      statusMessage = "删除操作已记录，可撤销"
      errorMessage = nil
      updateMelodyCoverage()
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
      if let selectedNoteID,
        !editor.notes.contains(where: { $0.id == selectedNoteID })
      {
        self.selectedNoteID = editor.notes.first?.id
      }
      statusMessage = "已撤销并保存"
      errorMessage = nil
      updateMelodyCoverage()
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
      statusMessage = "已重做并保存"
      errorMessage = nil
      updateMelodyCoverage()
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
    selectedNoteID = prepared.editor?.notes.first?.id
    statusMessage = prepared.statusMessage
    errorMessage = nil
    if let editor = prepared.editor {
      transport.load(audioURL: editor.snapshot.audioURL)
      refreshMIDIPreview()
    }
    updateMelodyCoverage()
  }

  private func applyPreparedProject(_ prepared: PreparedProject) {
    midiPreviewRefresh?.cancel()
    midiPreviewGeneration = UUID()
    transport.stop()
    discardMIDIPreviewArtifact()
    catalog = prepared.catalog
    snapshot = prepared.snapshot
    editor = prepared.editor
    selectedNoteID = prepared.editor?.notes.first?.id
    lastMelodyGapID = nil
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
    if let state = prepared.jobState {
      betaProjectURL = prepared.catalog.rootURL
      betaJobID = state.jobID
      betaSlurmState = state.slurmState
      betaPipelineStage = state.pipelineStage
      if prepared.catalog.bundles.isEmpty
        || !["COMPLETED", "FAILED", "CANCELLED"].contains(
          state.slurmState ?? ""
        )
      {
        rememberActiveBetaProject()
        startMonitoring(projectURL: prepared.catalog.rootURL)
      } else {
        clearActiveBetaProject()
      }
    }
    refreshProjectLibrary()
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
    betaMonitor?.cancel()
    betaMonitor = Task { [weak self] in
      while !Task.isCancelled {
        guard !Task.isCancelled, let self else { return }
        await self.refreshBetaJob(projectURL: projectURL)
        if self.betaSlurmState == "COMPLETED"
          || self.betaSlurmState == "FAILED"
          || self.betaSlurmState == "CANCELLED"
          || self.hyakConnectionState == .loginRequired
        {
          return
        }
        try? await Task.sleep(for: .seconds(20))
      }
    }
  }

  private func refreshBetaJob(projectURL: URL) async {
    do {
      let backend = try PrivateBetaBackend.locate()
      let response = try await Task.detached(priority: .utility) {
        try backend.refresh(projectURL: projectURL)
      }.value
      try handleBetaResponse(response)
      hyakConnectionState = .connected
    } catch {
      presentBetaError(error)
    }
  }

  private func handleBetaResponse(
    _ response: PrivateBetaResponse
  ) throws {
    guard response.ok else {
      if response.needsHyakLogin == true {
        throw PrivateBetaBackendError.hyakLoginRequired(
          response.error ?? "Hyak 登录已过期"
        )
      }
      throw PrivateBetaBackendError.invalidResponse(
        response.error ?? "未知后台错误"
      )
    }
    if let path = response.localProjectDir {
      betaProjectURL = URL(fileURLWithPath: path, isDirectory: true)
    }
    betaJobID = response.jobID ?? betaJobID
    betaSlurmState = response.slurmState ?? betaSlurmState
    betaPipelineStage = response.pipelineStage ?? betaPipelineStage
    switch response.status {
    case "succeeded":
      guard let betaProjectURL else { return }
      clearActiveBetaProject()
      openProject(betaProjectURL)
      statusMessage = "Hyak 识别流程完成，完整多轨与默认主旋律已取回"
    case "failed":
      clearActiveBetaProject()
      errorMessage = "Hyak 任务失败；项目日志已经保留，可据此定位问题。"
      statusMessage = "识别失败"
    case "running":
      rememberActiveBetaProject()
      switch betaPipelineStage {
      case "automatic_gap_recovery":
        statusMessage = "Hyak 正在自动补漏主旋律（任务 \(betaJobID ?? "未知")）"
      case "gap_planning":
        statusMessage = "整曲多轨已生成，正在检查主旋律长缺口"
      case "packaging":
        statusMessage = "识别已完成，正在打包完整多轨"
      default:
        statusMessage = "Hyak GPU 正在识别整首歌（任务 \(betaJobID ?? "未知")）"
      }
    default:
      rememberActiveBetaProject()
      statusMessage = "Hyak 任务已排队（\(betaSlurmState ?? "PENDING")）"
    }
    refreshProjectLibrary()
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
        if !["COMPLETED", "FAILED", "CANCELLED"].contains(
          betaSlurmState ?? ""
        ) {
          startMonitoring(projectURL: betaProjectURL)
        }
      }
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
      statusMessage = "Hyak 登录已过期；作业仍在运行。重新连接后会自动恢复。"
      return
    }
    present(error)
  }

  private func rememberActiveBetaProject() {
    guard persistRecentProject, let betaProjectURL else { return }
    defaults.set(betaProjectURL.path, forKey: activeBetaProjectKey)
  }

  private func clearActiveBetaProject() {
    guard persistRecentProject else { return }
    defaults.removeObject(forKey: activeBetaProjectKey)
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
}

private struct MixerSettings: Codable {
  let playbackMode: String
  let mutedTrackIDs: [String]
  let soloTrackIDs: [String]
  let trackVolumes: [String: Double]
}

private struct PrivateBetaJobState: Decodable, Sendable {
  let jobID: String?
  let slurmState: String?
  let pipelineStage: String?

  enum CodingKeys: String, CodingKey {
    case jobID = "job_id"
    case slurmState = "slurm_state"
    case pipelineStage = "pipeline_stage"
  }
}

private struct PreparedSelection: Sendable {
  let snapshot: ProjectSnapshot
  let editor: EditorProject?
  let statusMessage: String

  static func loadBundle(
    catalog: ProjectCatalog,
    bundleID: String
  ) throws -> PreparedSelection {
    let snapshot = try ProjectLoader.open(catalog, bundleID: bundleID)
    let preferredTrack =
      MelodyTrackSelector.preferred(in: snapshot.tracks)
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
    let editor = try EditorProject(
      snapshot: snapshot,
      bundleID: bundleID,
      selectedTrackID: trackID
    )
    try? editor.saveWorkspaceSelection()
    let label = MelodyTrackSelector.displayLabel(for: editor.selectedTrack)
    return PreparedSelection(
      snapshot: snapshot,
      editor: editor,
      statusMessage: "音轨 \(label)，\(editor.notes.count) 个音符"
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
    if let workspace {
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
        let editor = try EditorProject(
          snapshot: snapshot,
          bundleID: workspace.canonicalBundleID,
          selectedTrackID: workspace.selectedTrackID
        )
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

    guard catalog.bundles.count == 1 else {
      return PreparedProject(
        catalog: catalog,
        snapshot: nil,
        editor: nil,
        jobState: jobState,
        statusMessage: catalog.bundles.isEmpty
          ? "项目还没有可打开的识别结果"
          : "项目包含多个结果版本，请选择一个",
        warning: warning
      )
    }
    let bundle = catalog.bundles[0]
    let snapshot = try ProjectLoader.open(catalog, bundleID: bundle.id)
    let preferredTrack =
      MelodyTrackSelector.preferred(in: snapshot.tracks)
      ?? (snapshot.tracks.count == 1 ? snapshot.tracks[0] : nil)
    let editor: EditorProject?
    if let preferredTrack {
      let opened = try EditorProject(
        snapshot: snapshot,
        bundleID: bundle.id,
        selectedTrackID: preferredTrack.id
      )
      try? opened.saveWorkspaceSelection()
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
      return "已打开自动增强主旋律（Beta）；原始与仅补漏版本保留在诊断详情"
    }
    if editor.selectedTrack.instrument?.lowercased() == "voice" {
      return "已打开 voice 主唱候选；长空缺会单独提示，不再把它冒充完整主旋律"
    }
    return "已打开音轨 \(editor.selectedTrack.label)，\(editor.notes.count) 个音符"
  }
}

enum LocalProjectLibrary {
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
      projects.append(
        LocalProjectItem(
          projectID: manifest.projectID,
          title: manifest.title ?? manifest.projectID,
          url: child,
          modifiedAt: values.contentModificationDate ?? .distantPast,
          hasResults: hasResults,
          jobState: state?.slurmState
        )
      )
    }
    return projects.sorted {
      if $0.modifiedAt == $1.modifiedAt {
        return $0.title.localizedStandardCompare($1.title)
          == .orderedAscending
      }
      return $0.modifiedAt > $1.modifiedAt
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
