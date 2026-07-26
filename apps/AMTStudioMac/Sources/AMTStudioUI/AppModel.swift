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
  @Published public private(set) var betaProjectURL: URL?
  @Published public private(set) var isBetaBusy = false
  @Published public private(set) var hyakConnectionState: HyakConnectionState = .unknown
  @Published public private(set) var midiPlaybackMode: MIDIPlaybackMode = .mix
  @Published public private(set) var mutedTrackIDs = Set<String>()
  @Published public private(set) var soloTrackIDs = Set<String>()
  @Published public private(set) var trackVolumes: [String: Double] = [:]

  public let transport = AudioTransport()

  private let defaults: UserDefaults
  private let persistRecentProject: Bool
  private let recentProjectKey = "AMTStudio.recentProjectPath"
  private let activeBetaProjectKey = "AMTStudio.activeBetaProjectPath"
  private var pendingInitialProjectURL: URL?
  private var betaMonitor: Task<Void, Never>?
  private var connectionMonitor: Task<Void, Never>?
  private var midiPreviewRefresh: Task<Void, Never>?

  public init(
    defaults: UserDefaults = .standard,
    initialProjectURL: URL? = nil,
    restoreRecent: Bool = true,
    persistRecentProject: Bool = true
  ) {
    self.defaults = defaults
    self.persistRecentProject = persistRecentProject
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
      pendingInitialProjectURL = URL(fileURLWithPath: path)
    }
  }

  public func openInitialProjectIfNeeded() {
    guard let pendingInitialProjectURL else { return }
    self.pendingInitialProjectURL = nil
    openProject(pendingInitialProjectURL)
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
      let process = Process()
      let escapedPath = backend.loginScriptURL.path
        .replacingOccurrences(of: "\\", with: "\\\\")
        .replacingOccurrences(of: "\"", with: "\\\"")
      process.executableURL = URL(fileURLWithPath: "/usr/bin/osascript")
      process.arguments = [
        "-e",
        "tell application \"Terminal\" to activate",
        "-e",
        "tell application \"Terminal\" to do script quoted form of \"\(escapedPath)\"",
      ]
      try process.run()
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

  public var trackChoices: [EditorTrack] {
    snapshot?.tracks ?? []
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
      return solos
    }
    return available.subtracting(mutedTrackIDs)
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
    do {
      let catalog = try ProjectLoader.inspect(url)
      self.catalog = catalog
      snapshot = nil
      editor = nil
      selectedNoteID = nil
      transport.stop()
      if persistRecentProject {
        defaults.set(catalog.rootURL.path, forKey: recentProjectKey)
      }
      statusMessage = "已读取项目；请选择 canonical bundle"
      errorMessage = nil
      let jobStateURL = catalog.rootURL.appendingPathComponent(
        "app/private_beta_job.json"
      )
      if FileManager.default.fileExists(atPath: jobStateURL.path) {
        betaProjectURL = catalog.rootURL
        if let state = try? JSONDecoder().decode(
          PrivateBetaJobState.self,
          from: Data(contentsOf: jobStateURL)
        ) {
          betaJobID = state.jobID
          betaSlurmState = state.slurmState
        }
        if catalog.bundles.isEmpty
          || !["COMPLETED", "FAILED", "CANCELLED"].contains(
            betaSlurmState ?? ""
          )
        {
          rememberActiveBetaProject()
          startMonitoring(projectURL: catalog.rootURL)
        } else {
          clearActiveBetaProject()
        }
      }

      do {
        if let workspace = try EditorProject.loadWorkspace(
          projectURL: catalog.rootURL
        ) {
          guard workspace.projectID == catalog.manifest.projectID,
            let bundle = catalog.bundles.first(where: {
              $0.id == workspace.canonicalBundleID
            }),
            try ProjectLoader.sha256(bundle.canonicalProjectURL)
              == workspace.canonicalProjectSHA256
          else {
            throw AMTProjectError.editSessionMismatch
          }
          try selectBundle(workspace.canonicalBundleID)
          if snapshot?.tracks.contains(where: {
            $0.id == workspace.selectedTrackID
          }) == true {
            try selectTrack(workspace.selectedTrackID)
          }
        } else if catalog.bundles.count == 1 {
          try selectBundle(catalog.bundles[0].id)
        }
      } catch {
        statusMessage = "项目已打开；旧编辑状态无法恢复，请重新选择"
        errorMessage =
          (error as? LocalizedError)?.errorDescription
          ?? error.localizedDescription
      }
    } catch {
      present(error)
    }
  }

  public func selectBundle(_ id: String) throws {
    guard let catalog else {
      throw AMTProjectError.missingManifest
    }
    let snapshot = try ProjectLoader.open(catalog, bundleID: id)
    self.snapshot = snapshot
    editor = nil
    selectedNoteID = nil
    transport.stop()
    restoreMixerSettings(for: snapshot)
    statusMessage = "已验证多轨结果 \(id)；请选择一条音轨"
    errorMessage = nil
    if let voice = snapshot.tracks.first(where: {
      $0.instrument?.lowercased() == "voice"
    }) {
      try selectTrack(voice.id)
      statusMessage = "已默认打开 voice 主旋律轨；其余原始多轨仍完整保留"
    } else if snapshot.tracks.count == 1 {
      try selectTrack(snapshot.tracks[0].id)
    }
  }

  public func chooseBundle(_ id: String) {
    do {
      try selectBundle(id)
    } catch {
      present(error)
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
    var editor = try EditorProject(
      snapshot: snapshot,
      bundleID: bundleID,
      selectedTrackID: id
    )
    try editor.save()
    self.editor = editor
    selectedNoteID = editor.notes.first?.id
    statusMessage = "音轨 \(editor.selectedTrack.label)，\(editor.notes.count) 个音符"
    errorMessage = nil
    transport.load(audioURL: snapshot.audioURL)
    refreshMIDIPreview()
  }

  public func chooseTrack(_ id: String) {
    do {
      try selectTrack(id)
    } catch {
      present(error)
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
      let report = try MIDIExporter.exportArrangement(
        snapshot: snapshot,
        bundleID: bundleID,
        to: url
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
        trackVolumes: trackVolumes
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
      transport.clearMIDI(message: "所有音轨已静音；请启用至少一条音轨。")
      return
    }
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
      "\(editor.snapshot.baseFingerprint.prefix(16))-\(safePreviewID.prefix(48)).mid"
    )
    do {
      _ = try MIDIExporter.exportArrangement(
        snapshot: snapshot,
        bundleID: bundleID,
        to: url,
        includedTrackIDs: includedTrackIDs,
        trackVolumes: trackVolumes
      )
      transport.loadMIDI(url: url)
    } catch {
      transport.clearMIDI(
        message: "MIDI 预览暂不可用：\(error.localizedDescription)"
      )
    }
  }

  private func scheduleMIDIPreviewRefresh() {
    midiPreviewRefresh?.cancel()
    midiPreviewRefresh = Task { [weak self] in
      try? await Task.sleep(for: .milliseconds(180))
      guard !Task.isCancelled, let self else { return }
      self.refreshMIDIPreview()
    }
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
    switch response.status {
    case "succeeded":
      guard let betaProjectURL else { return }
      clearActiveBetaProject()
      openProject(betaProjectURL)
      statusMessage = "Hyak 识别完成，完整多轨已取回；已默认打开 voice 主旋律轨"
    case "failed":
      clearActiveBetaProject()
      errorMessage = "Hyak 任务失败；项目日志已经保留，可据此定位问题。"
      statusMessage = "识别失败"
    case "running":
      rememberActiveBetaProject()
      statusMessage = "Hyak GPU 正在识别整首歌（任务 \(betaJobID ?? "未知")）"
    default:
      rememberActiveBetaProject()
      statusMessage = "Hyak 任务已排队（\(betaSlurmState ?? "PENDING")）"
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
}

private struct MixerSettings: Codable {
  let playbackMode: String
  let mutedTrackIDs: [String]
  let soloTrackIDs: [String]
  let trackVolumes: [String: Double]
}

private struct PrivateBetaJobState: Decodable {
  let jobID: String?
  let slurmState: String?

  enum CodingKeys: String, CodingKey {
    case jobID = "job_id"
    case slurmState = "slurm_state"
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
