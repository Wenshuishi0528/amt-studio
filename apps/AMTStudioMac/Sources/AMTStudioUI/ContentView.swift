import AMTStudioCore
import AppKit
import SwiftUI
import UniformTypeIdentifiers

public struct ContentView: View {
  @ObservedObject private var model: AppModel

  public init(model: AppModel) {
    self.model = model
  }

  public var body: some View {
    NavigationSplitView {
      sidebar
        .navigationSplitViewColumnWidth(min: 250, ideal: 300, max: 380)
    } detail: {
      detail
    }
    .frame(minWidth: 1_150, minHeight: 720)
    .toolbar {
      ToolbarItemGroup {
        Button("打开项目", systemImage: "folder") {
          openProjectPanel()
        }
        .accessibilityIdentifier("open-project")
        Button("保存", systemImage: "square.and.arrow.down") {
          model.save()
        }
        .disabled(model.editor == nil)
        .accessibilityIdentifier("save-project")
        Button("导出 MIDI", systemImage: "pianokeys") {
          exportPanel()
        }
        .disabled(model.editor == nil)
        .accessibilityIdentifier("export-midi")
        Button("撤销", systemImage: "arrow.uturn.backward") {
          model.undo()
        }
        .disabled(model.editor?.canUndo != true)
        .accessibilityIdentifier("undo-edit")
        Button("重做", systemImage: "arrow.uturn.forward") {
          model.redo()
        }
        .disabled(model.editor?.canRedo != true)
        .accessibilityIdentifier("redo-edit")
      }
    }
    .alert(
      "AMT Studio",
      isPresented: Binding(
        get: { model.errorMessage != nil },
        set: { if !$0 { model.clearError() } }
      )
    ) {
      Button("知道了") {
        model.clearError()
      }
    } message: {
      Text(model.errorMessage ?? "")
    }
    .task {
      await Task.yield()
      model.openInitialProjectIfNeeded()
    }
  }

  @ViewBuilder
  private var sidebar: some View {
    List {
      Section("项目") {
        if let manifest = model.catalog?.manifest {
          LabeledContent(
            "名称",
            value: manifest.title ?? manifest.projectID
          )
          LabeledContent("项目 ID", value: manifest.projectID)
        } else {
          Text("尚未打开项目")
            .foregroundStyle(.secondary)
        }
      }

      if !model.bundleChoices.isEmpty {
        Section("Canonical bundle（必须明确选择）") {
          ForEach(model.bundleChoices) { bundle in
            Button {
              model.chooseBundle(bundle.id)
            } label: {
              VStack(alignment: .leading, spacing: 3) {
                Text(bundle.id)
                  .lineLimit(1)
                Text("\(bundle.manifest.outputs.count) 个已校验文件")
                  .font(.caption)
                  .foregroundStyle(.secondary)
              }
            }
            .buttonStyle(.plain)
            .accessibilityIdentifier("bundle-\(bundle.id)")
          }
        }
      }

      if !model.trackChoices.isEmpty {
        Section("候选轨（不代表最终准确率）") {
          ForEach(model.trackChoices) { track in
            Button {
              model.chooseTrack(track.id)
            } label: {
              HStack {
                VStack(alignment: .leading, spacing: 3) {
                  Text(track.label)
                  Text(track.instrument ?? "未知乐器")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                }
                Spacer()
                if model.editor?.selectedTrack.id == track.id {
                  Image(systemName: "checkmark.circle.fill")
                    .foregroundStyle(.tint)
                }
              }
            }
            .buttonStyle(.plain)
            .accessibilityIdentifier("track-\(track.id)")
          }
        }
      }

      if let editor = model.editor {
        Section("当前修正版") {
          LabeledContent("候选轨", value: editor.selectedTrack.label)
          LabeledContent("音符", value: "\(editor.notes.count)")
          Text("所有修改写入独立操作历史；原始 JSONL 不会覆盖。")
            .font(.caption)
            .foregroundStyle(.secondary)
        }
      }
    }
    .safeAreaInset(edge: .bottom) {
      Text(model.statusMessage)
        .font(.caption)
        .foregroundStyle(.secondary)
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(10)
        .background(.bar)
        .accessibilityIdentifier("status-message")
    }
  }

  @ViewBuilder
  private var detail: some View {
    if let editor = model.editor {
      WorkspaceView(
        model: model,
        transport: model.transport,
        editor: editor
      )
    } else if let snapshot = model.snapshot {
      EmptyStateView(
        icon: "music.note.list",
        title: "请选择一条候选轨",
        message: "这个 bundle 含 \(snapshot.tracks.count) 条候选轨。应用不会自动把其中任何一条宣称为最终主旋律。"
      )
    } else if model.catalog != nil {
      EmptyStateView(
        icon: "shippingbox",
        title: "请选择 canonical bundle",
        message: "项目没有 active/latest 指针，因此必须由你明确选择要编辑的版本。"
      )
    } else {
      EmptyStateView(
        icon: "waveform.and.music.note",
        title: "AMT Studio",
        message: "打开已有项目即可试听和修改，不会触发模型推理，也不需要连接 Hyak。"
      )
    }
  }

  private func openProjectPanel() {
    let panel = NSOpenPanel()
    panel.title = "选择包含 manifest.json 的 AMT Studio 项目"
    panel.canChooseDirectories = true
    panel.canChooseFiles = false
    panel.allowsMultipleSelection = false
    if panel.runModal() == .OK, let url = panel.url {
      model.openProject(url)
    }
  }

  private func exportPanel() {
    let panel = NSSavePanel()
    panel.title = "导出当前候选轨修正版 MIDI"
    panel.nameFieldStringValue = "\(model.editor?.selectedTrack.id ?? "track").performance.mid"
    if let midi = UTType(filenameExtension: "mid") {
      panel.allowedContentTypes = [midi]
    }
    if panel.runModal() == .OK, let url = panel.url {
      model.exportMIDI(to: url)
    }
  }
}

private struct EmptyStateView: View {
  let icon: String
  let title: String
  let message: String

  var body: some View {
    ContentUnavailableView {
      Label(title, systemImage: icon)
    } description: {
      Text(message)
        .frame(maxWidth: 520)
    }
  }
}

private struct WorkspaceView: View {
  @ObservedObject var model: AppModel
  @ObservedObject var transport: AudioTransport
  let editor: EditorProject

  var body: some View {
    HSplitView {
      VStack(spacing: 0) {
        transportControls
        Divider()
        NoteOverview(
          notes: editor.notes,
          currentTime: transport.currentTime,
          duration: timelineDuration
        )
        .frame(height: 70)
        Divider()
        PianoRollView(
          notes: editor.notes,
          currentTime: transport.currentTime,
          duration: timelineDuration,
          selectedNoteID: $model.selectedNoteID,
          onCommit: model.commit
        )
      }
      .frame(minWidth: 760)

      inspector
        .frame(minWidth: 260, idealWidth: 300, maxWidth: 360)
    }
  }

  private var timelineDuration: Double {
    max(
      transport.duration,
      editor.notes.map(\.offsetSec).max() ?? 1,
      1
    )
  }

  private var transportControls: some View {
    VStack(alignment: .leading, spacing: 6) {
      HStack(spacing: 12) {
        Button {
          transport.togglePlayback()
        } label: {
          Image(
            systemName: transport.isPlaying
              ? "pause.fill"
              : "play.fill"
          )
          .frame(width: 22)
        }
        .keyboardShortcut(.space, modifiers: [])
        .accessibilityIdentifier("transport-play-pause")

        Text(formatTime(transport.currentTime))
          .monospacedDigit()
        Slider(
          value: Binding(
            get: { transport.currentTime },
            set: { transport.seek(to: $0) }
          ),
          in: 0...timelineDuration
        )
        Text(formatTime(timelineDuration))
          .monospacedDigit()

        Toggle(
          "原曲",
          isOn: Binding(
            get: { transport.originalEnabled },
            set: { transport.setOriginalEnabled($0) }
          )
        )
        .toggleStyle(.checkbox)
        Toggle(
          "钢琴",
          isOn: Binding(
            get: { transport.midiEnabled },
            set: { transport.setMIDIEnabled($0) }
          )
        )
        .toggleStyle(.checkbox)
        .disabled(!transport.midiAvailable)
      }
      ForEach(transport.errorMessages, id: \.self) { message in
        Label(message, systemImage: "exclamationmark.triangle.fill")
          .font(.caption)
          .foregroundStyle(.orange)
          .accessibilityIdentifier("transport-error")
      }
    }
    .padding(10)
  }

  @ViewBuilder
  private var inspector: some View {
    if let note = model.selectedNote {
      NoteInspector(
        note: note,
        onCommit: model.commit,
        onDelete: model.deleteSelectedNote
      )
      .id("\(note.id)-\(note.onsetSec)-\(note.offsetSec)-\(note.pitchMIDI)")
    } else {
      EmptyStateView(
        icon: "cursorarrow.click",
        title: "选择音符",
        message: "拖动音符可同时改变时间与音高；拖左右把手可调整长度。"
      )
    }
  }
}

private struct NoteOverview: View {
  let notes: [EditorNote]
  let currentTime: Double
  let duration: Double

  var body: some View {
    GeometryReader { geometry in
      Canvas { context, size in
        let bins = max(1, Int(size.width / 3))
        var counts = Array(repeating: 0, count: bins)
        for note in notes {
          let index = min(
            bins - 1,
            max(0, Int(note.onsetSec / duration * Double(bins)))
          )
          counts[index] += 1
        }
        let maximum = max(1, counts.max() ?? 1)
        for (index, count) in counts.enumerated() {
          let height = Double(count) / Double(maximum) * (size.height - 18)
          let rect = CGRect(
            x: Double(index) / Double(bins) * size.width,
            y: size.height - height,
            width: max(1, size.width / Double(bins)),
            height: height
          )
          context.fill(Path(rect), with: .color(.accentColor.opacity(0.45)))
        }
        let cursorX = currentTime / duration * size.width
        context.stroke(
          Path(
            CGRect(
              x: cursorX,
              y: 0,
              width: 1,
              height: size.height
            )
          ),
          with: .color(.red),
          lineWidth: 1
        )
      }
      Text("音符密度概览（不是音频波形）")
        .font(.caption2)
        .foregroundStyle(.secondary)
        .padding(4)
    }
    .background(.quaternary.opacity(0.35))
  }
}

private struct PianoRollView: View {
  let notes: [EditorNote]
  let currentTime: Double
  let duration: Double
  @Binding var selectedNoteID: String?
  let onCommit: (EditorNote) -> Void

  private let pointsPerSecond = 28.0
  private let pointsPerSemitone = 14.0

  var body: some View {
    let minimumPitch = max(
      0,
      floor((notes.map(\.pitchMIDI).min() ?? 48) - 3)
    )
    let maximumPitch = min(
      127,
      ceil((notes.map(\.pitchMIDI).max() ?? 84) + 3)
    )
    let contentWidth = max(1_200, duration * pointsPerSecond + 80)
    let contentHeight = max(
      520,
      (maximumPitch - minimumPitch + 1) * pointsPerSemitone
    )

    ScrollView([.horizontal, .vertical]) {
      ZStack(alignment: .topLeading) {
        PianoGrid(
          duration: duration,
          minimumPitch: minimumPitch,
          maximumPitch: maximumPitch,
          pointsPerSecond: pointsPerSecond,
          pointsPerSemitone: pointsPerSemitone
        )
        ForEach(notes) { note in
          NoteBlock(
            note: note,
            minimumPitch: minimumPitch,
            maximumPitch: maximumPitch,
            pointsPerSecond: pointsPerSecond,
            pointsPerSemitone: pointsPerSemitone,
            selected: note.id == selectedNoteID,
            onSelect: { selectedNoteID = note.id },
            onCommit: onCommit
          )
        }
        Rectangle()
          .fill(.red.opacity(0.85))
          .frame(width: 1, height: contentHeight)
          .offset(x: currentTime * pointsPerSecond)
          .allowsHitTesting(false)
      }
      .frame(width: contentWidth, height: contentHeight)
    }
    .background(Color(nsColor: .textBackgroundColor))
    .accessibilityIdentifier("piano-roll")
  }
}

private struct PianoGrid: View {
  let duration: Double
  let minimumPitch: Double
  let maximumPitch: Double
  let pointsPerSecond: Double
  let pointsPerSemitone: Double

  var body: some View {
    Canvas { context, size in
      for pitch in Int(minimumPitch)...Int(maximumPitch) {
        let y = (maximumPitch - Double(pitch)) * pointsPerSemitone
        let pitchClass = pitch % 12
        if [1, 3, 6, 8, 10].contains(pitchClass) {
          context.fill(
            Path(
              CGRect(
                x: 0,
                y: y,
                width: size.width,
                height: pointsPerSemitone
              )
            ),
            with: .color(.black.opacity(0.035))
          )
        }
        context.stroke(
          Path(CGRect(x: 0, y: y, width: size.width, height: 0.5)),
          with: .color(.secondary.opacity(0.18)),
          lineWidth: 0.5
        )
      }
      for second in stride(from: 0, through: Int(duration), by: 5) {
        let x = Double(second) * pointsPerSecond
        context.stroke(
          Path(CGRect(x: x, y: 0, width: 0.5, height: size.height)),
          with: .color(.secondary.opacity(0.3)),
          lineWidth: 0.5
        )
        context.draw(
          Text("\(second)s").font(.caption2).foregroundColor(.secondary),
          at: CGPoint(x: x + 3, y: 8),
          anchor: .leading
        )
      }
    }
  }
}

enum PianoRollLayout {
  static let resizeHandleWidth = 6.0
  static let minimumNoteWidth = 28.0
  static var minimumMoveHitWidth: Double {
    minimumNoteWidth - 2 * resizeHandleWidth
  }
}

enum NoteGestureProjection {
  static func move(
    _ note: EditorNote,
    translation: CGSize,
    pointsPerSecond: Double,
    pointsPerSemitone: Double
  ) -> EditorNote {
    var updated = note
    let duration = note.offsetSec - note.onsetSec
    updated.onsetSec = max(
      0,
      note.onsetSec + translation.width / pointsPerSecond
    )
    updated.offsetSec = updated.onsetSec + duration
    updated.pitchMIDI = min(
      127,
      max(
        0,
        (note.pitchMIDI
          - translation.height / pointsPerSemitone).rounded()
      )
    )
    return updated
  }

  static func resizeLeft(
    _ note: EditorNote,
    translation: CGSize,
    pointsPerSecond: Double
  ) -> EditorNote {
    var updated = note
    updated.onsetSec = max(
      0,
      min(
        note.offsetSec - EditorProject.minimumDuration,
        note.onsetSec + translation.width / pointsPerSecond
      )
    )
    return updated
  }

  static func resizeRight(
    _ note: EditorNote,
    translation: CGSize,
    pointsPerSecond: Double
  ) -> EditorNote {
    var updated = note
    updated.offsetSec = max(
      note.onsetSec + EditorProject.minimumDuration,
      note.offsetSec + translation.width / pointsPerSecond
    )
    return updated
  }
}

private struct NoteBlock: View {
  let note: EditorNote
  let minimumPitch: Double
  let maximumPitch: Double
  let pointsPerSecond: Double
  let pointsPerSemitone: Double
  let selected: Bool
  let onSelect: () -> Void
  let onCommit: (EditorNote) -> Void

  @GestureState private var bodyDrag = CGSize.zero
  @GestureState private var leftDrag = CGSize.zero
  @GestureState private var rightDrag = CGSize.zero

  var body: some View {
    let baseWidth = max(
      PianoRollLayout.minimumNoteWidth,
      (note.offsetSec - note.onsetSec) * pointsPerSecond
    )
    let adjustedWidth = max(
      PianoRollLayout.minimumNoteWidth,
      baseWidth - leftDrag.width + rightDrag.width
    )
    let x =
      note.onsetSec * pointsPerSecond
      + adjustedWidth / 2
      + leftDrag.width
      + bodyDrag.width
    let y =
      (maximumPitch - note.pitchMIDI) * pointsPerSemitone
      + pointsPerSemitone / 2
      + bodyDrag.height

    HStack(spacing: 0) {
      Rectangle()
        .fill(.white.opacity(0.75))
        .frame(width: PianoRollLayout.resizeHandleWidth)
        .contentShape(Rectangle())
        .gesture(leftResizeGesture)
        .accessibilityLabel("调整音符起点")
      RoundedRectangle(cornerRadius: 3)
        .fill(noteColor)
        .overlay {
          if selected {
            RoundedRectangle(cornerRadius: 3)
              .stroke(.white, lineWidth: 2)
          }
        }
        .contentShape(Rectangle())
        .gesture(moveGesture)
      Rectangle()
        .fill(.white.opacity(0.75))
        .frame(width: PianoRollLayout.resizeHandleWidth)
        .contentShape(Rectangle())
        .gesture(rightResizeGesture)
        .accessibilityLabel("调整音符终点")
    }
    .frame(width: adjustedWidth, height: max(10, pointsPerSemitone - 2))
    .shadow(color: selected ? .accentColor.opacity(0.7) : .clear, radius: 3)
    .position(x: x, y: y)
    .onTapGesture(perform: onSelect)
    .accessibilityElement(children: .combine)
    .accessibilityLabel(
      "音符 \(Int(note.pitchMIDI.rounded()))，\(note.onsetSec.formatted(.number.precision(.fractionLength(2)))) 秒"
    )
    .accessibilityIdentifier("note-\(note.id)")
  }

  private var noteColor: Color {
    guard let confidence = note.confidence else {
      return .indigo.opacity(0.82)
    }
    if confidence < 0.5 {
      return .orange.opacity(0.9)
    }
    return .blue.opacity(0.86)
  }

  private var moveGesture: some Gesture {
    DragGesture(minimumDistance: 1)
      .updating($bodyDrag) { value, state, _ in
        state = value.translation
      }
      .onChanged { _ in onSelect() }
      .onEnded { value in
        onCommit(
          NoteGestureProjection.move(
            note,
            translation: value.translation,
            pointsPerSecond: pointsPerSecond,
            pointsPerSemitone: pointsPerSemitone
          )
        )
      }
  }

  private var leftResizeGesture: some Gesture {
    DragGesture(minimumDistance: 1)
      .updating($leftDrag) { value, state, _ in
        state = value.translation
      }
      .onChanged { _ in onSelect() }
      .onEnded { value in
        onCommit(
          NoteGestureProjection.resizeLeft(
            note,
            translation: value.translation,
            pointsPerSecond: pointsPerSecond
          )
        )
      }
  }

  private var rightResizeGesture: some Gesture {
    DragGesture(minimumDistance: 1)
      .updating($rightDrag) { value, state, _ in
        state = value.translation
      }
      .onChanged { _ in onSelect() }
      .onEnded { value in
        onCommit(
          NoteGestureProjection.resizeRight(
            note,
            translation: value.translation,
            pointsPerSecond: pointsPerSecond
          )
        )
      }
  }
}

private struct NoteInspector: View {
  let note: EditorNote
  let onCommit: (EditorNote) -> Void
  let onDelete: () -> Void

  @State private var onset: Double
  @State private var offset: Double

  init(
    note: EditorNote,
    onCommit: @escaping (EditorNote) -> Void,
    onDelete: @escaping () -> Void
  ) {
    self.note = note
    self.onCommit = onCommit
    self.onDelete = onDelete
    _onset = State(initialValue: note.onsetSec)
    _offset = State(initialValue: note.offsetSec)
  }

  var body: some View {
    Form {
      Section("音符") {
        Stepper(
          "音高 \(Int(note.pitchMIDI.rounded()))",
          value: Binding(
            get: { Int(note.pitchMIDI.rounded()) },
            set: { value in
              var updated = note
              updated.pitchMIDI = Double(value)
              onCommit(updated)
            }
          ),
          in: 0...127
        )
        TextField(
          "起点（秒）",
          value: $onset,
          format: .number.precision(.fractionLength(3))
        )
        .onSubmit {
          var updated = note
          updated.onsetSec = onset
          onCommit(updated)
        }
        TextField(
          "终点（秒）",
          value: $offset,
          format: .number.precision(.fractionLength(3))
        )
        .onSubmit {
          var updated = note
          updated.offsetSec = offset
          onCommit(updated)
        }
        LabeledContent(
          "长度",
          value:
            "\((note.offsetSec - note.onsetSec).formatted(.number.precision(.fractionLength(3)))) 秒"
        )
      }

      Section("来源与不确定性") {
        LabeledContent("模型", value: note.sourceModel)
        LabeledContent("Run", value: note.sourceRunID)
        LabeledContent(
          "置信度",
          value: note.confidence.map {
            $0.formatted(.percent.precision(.fractionLength(1)))
          } ?? "模型未提供"
        )
        Text("“未提供”不等于低置信度。当前候选轨没有被声明为最终准确结果。")
          .font(.caption)
          .foregroundStyle(.secondary)
      }

      Section {
        Button("删除音符", role: .destructive, action: onDelete)
          .accessibilityIdentifier("delete-note")
      }
    }
    .formStyle(.grouped)
  }
}

private func formatTime(_ value: Double) -> String {
  let total = max(0, Int(value.rounded(.down)))
  return String(format: "%d:%02d", total / 60, total % 60)
}
