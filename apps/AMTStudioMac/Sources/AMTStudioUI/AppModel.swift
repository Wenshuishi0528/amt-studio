import Foundation

#if canImport(AMTStudioCore)
  import AMTStudioCore
#endif

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

  public let transport = AudioTransport()

  private let defaults: UserDefaults
  private let persistRecentProject: Bool
  private let recentProjectKey = "AMTStudio.recentProjectPath"
  private var pendingInitialProjectURL: URL?
  private var betaMonitor: Task<Void, Never>?

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
      guard FileManager.default.isExecutableFile(
        atPath: backend.loginScriptURL.path
      ) else {
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
      statusMessage = "请在 Terminal 输入密码并通过 Duo；成功后回到这里选择歌曲"
      errorMessage = nil
    } catch {
      present(error)
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
        if let betaProjectURL {
          startMonitoring(projectURL: betaProjectURL)
        }
      } catch {
        present(error)
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

  public var bundleChoices: [CanonicalBundleChoice] {
    catalog?.bundles ?? []
  }

  public var trackChoices: [EditorTrack] {
    snapshot?.tracks ?? []
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
        if catalog.bundles.isEmpty {
          startMonitoring(projectURL: catalog.rootURL)
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

  public func clearError() {
    errorMessage = nil
  }

  private func refreshMIDIPreview() {
    guard let editor else { return }
    let directory = FileManager.default.temporaryDirectory
      .appendingPathComponent("AMTStudioPreview", isDirectory: true)
    let safeTrackID = editor.selectedTrack.id.map {
      $0.isLetter || $0.isNumber || "-._".contains($0) ? $0 : "-"
    }.reduce(into: "") { $0.append($1) }
    let url = directory.appendingPathComponent(
      "\(editor.snapshot.baseFingerprint.prefix(16))-\(safeTrackID.prefix(48)).mid"
    )
    do {
      _ = try MIDIExporter.export(project: editor, to: url)
      transport.loadMIDI(url: url)
    } catch {
      transport.clearMIDI(
        message: "钢琴预览暂不可用：\(error.localizedDescription)"
      )
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
        try? await Task.sleep(for: .seconds(20))
        guard !Task.isCancelled, let self else { return }
        await self.refreshBetaJob(projectURL: projectURL)
        if self.betaSlurmState == "COMPLETED"
          || self.betaSlurmState == "FAILED"
          || self.betaSlurmState == "CANCELLED"
          || self.errorMessage != nil
        {
          return
        }
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
    } catch {
      present(error)
    }
  }

  private func handleBetaResponse(
    _ response: PrivateBetaResponse
  ) throws {
    guard response.ok else {
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
      openProject(betaProjectURL)
      statusMessage = "Hyak 识别完成，完整多轨已取回；已默认打开 voice 主旋律轨"
    case "failed":
      errorMessage = "Hyak 任务失败；项目日志已经保留，可据此定位问题。"
      statusMessage = "识别失败"
    case "running":
      statusMessage = "Hyak GPU 正在识别整首歌（任务 \(betaJobID ?? "未知")）"
    default:
      statusMessage = "Hyak 任务已排队（\(betaSlurmState ?? "PENDING")）"
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
