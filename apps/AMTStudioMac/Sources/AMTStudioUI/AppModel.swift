import AMTStudioCore
import Foundation

@MainActor
public final class AppModel: ObservableObject {
  @Published public private(set) var catalog: ProjectCatalog?
  @Published public private(set) var snapshot: ProjectSnapshot?
  @Published public private(set) var editor: EditorProject?
  @Published public var selectedNoteID: String?
  @Published public var errorMessage: String?
  @Published public var statusMessage = "请选择一个已有 AMT Studio 项目"

  public let transport = AudioTransport()

  private let defaults: UserDefaults
  private let recentProjectKey = "AMTStudio.recentProjectPath"
  private var pendingInitialProjectURL: URL?

  public init(
    defaults: UserDefaults = .standard,
    initialProjectURL: URL? = nil,
    restoreRecent: Bool = true
  ) {
    self.defaults = defaults
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

  public func openProject(_ url: URL) {
    do {
      let catalog = try ProjectLoader.inspect(url)
      self.catalog = catalog
      snapshot = nil
      editor = nil
      selectedNoteID = nil
      transport.stop()
      defaults.set(catalog.rootURL.path, forKey: recentProjectKey)
      statusMessage = "已读取项目；请选择 canonical bundle"
      errorMessage = nil

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
    statusMessage = "已验证 bundle \(id)；请选择一条候选轨"
    errorMessage = nil
    if snapshot.tracks.count == 1 {
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
    statusMessage = "候选轨 \(editor.selectedTrack.label)，\(editor.notes.count) 个音符"
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

  private func present(_ error: Error) {
    errorMessage =
      (error as? LocalizedError)?.errorDescription
      ?? error.localizedDescription
    statusMessage = "操作失败"
  }
}
