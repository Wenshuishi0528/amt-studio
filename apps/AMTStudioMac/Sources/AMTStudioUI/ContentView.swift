import AppKit
import SwiftUI
import UniformTypeIdentifiers

#if canImport(AMTStudioCore)
  import AMTStudioCore
#endif

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
        Button(hyakActionTitle, systemImage: hyakActionIcon) {
          if model.hyakConnectionState == .connected {
            model.checkHyakConnection()
          } else {
            model.openHyakLogin()
          }
        }
        .disabled(model.hyakConnectionState == .checking)
        .help(hyakActionHelp)
        .accessibilityIdentifier("connect-hyak")
        Button("识别歌曲", systemImage: "waveform.badge.plus") {
          importAudioPanel()
        }
        .disabled(
          model.isBetaBusy || model.hasActiveBetaJob
            || model.isLoadingProject
        )
        .help(
          model.hasActiveBetaJob
            ? "当前已有任务，完成或失败前不会重复提交"
            : "选择 MP3/WAV 并在 Hyak GPU 上识别"
        )
        .accessibilityIdentifier("transcribe-song")
        if model.isBetaBusy {
          ProgressView()
            .controlSize(.small)
        }
        Button("刷新任务", systemImage: "arrow.clockwise") {
          model.refreshBetaJob()
        }
        .disabled(model.betaProjectURL == nil || model.isBetaBusy)
        .accessibilityIdentifier("refresh-beta-job")
        Button("打开项目", systemImage: "folder") {
          openProjectPanel()
        }
        .disabled(model.isLoadingProject)
        .accessibilityIdentifier("open-project")
        Button("结果文件夹", systemImage: "folder.badge.gearshape") {
          model.revealCurrentProject()
        }
        .disabled(model.catalog == nil)
        .accessibilityIdentifier("reveal-project")
        Button("保存", systemImage: "square.and.arrow.down") {
          model.save()
        }
        .disabled(model.editor == nil)
        .accessibilityIdentifier("save-project")
        Menu("导出 MIDI", systemImage: "pianokeys") {
          Button("当前编辑音轨") {
            exportTrackPanel()
          }
          Button("当前混音（静音与音量生效）") {
            exportMixPanel()
          }
          Button("完整多轨") {
            exportArrangementPanel()
          }
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
      model.refreshProjectLibrary()
      model.openInitialProjectIfNeeded()
    }
  }

  @ViewBuilder
  private var sidebar: some View {
    List {
      Section("以前的音乐") {
        if model.libraryProjects.isEmpty {
          if model.isRefreshingLibrary {
            ProgressView("正在读取本地音乐库…")
              .controlSize(.small)
          } else {
            Text("还没有可打开的本地项目")
              .foregroundStyle(.secondary)
          }
        } else {
          ForEach(Array(model.libraryProjects.prefix(12))) { project in
            Button {
              model.openProject(project.url)
            } label: {
              HStack(spacing: 8) {
                Image(
                  systemName: project.hasResults
                    ? "music.note.house.fill"
                    : "hourglass"
                )
                .foregroundStyle(
                  model.catalog?.rootURL == project.url
                    ? Color.accentColor
                    : Color.secondary
                )
                VStack(alignment: .leading, spacing: 2) {
                  Text(project.title)
                    .lineLimit(1)
                  Text(project.stateLabel)
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                }
                Spacer()
                if model.catalog?.rootURL == project.url {
                  Image(systemName: "checkmark.circle.fill")
                    .foregroundStyle(.tint)
                }
              }
              .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .disabled(model.isLoadingProject)
            .accessibilityIdentifier("library-\(project.projectID)")
          }
        }
        Button("刷新音乐库", systemImage: "arrow.clockwise") {
          model.refreshProjectLibrary()
        }
        .disabled(model.isRefreshingLibrary)
      }

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

      Section("Hyak") {
        LabeledContent("连接", value: hyakConnectionLabel)
        if let jobID = model.betaJobID {
          LabeledContent("Job ID", value: jobID)
          LabeledContent(
            "任务",
            value: model.betaSlurmState ?? "准备中"
          )
        }
        if model.hyakConnectionState == .loginRequired {
          Label(
            "登录过期不会终止远端作业。重新登录后会自动查询并取回结果。",
            systemImage: "exclamationmark.arrow.triangle.2.circlepath"
          )
          .font(.caption)
          .foregroundStyle(.orange)
        } else {
          Text("模型只在 Hyak GPU 上运行；关闭 Mac 窗口不会终止已提交的 Slurm 作业。")
            .font(.caption)
            .foregroundStyle(.secondary)
        }
      }

      if !model.bundleChoices.isEmpty {
        Section("识别版本") {
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
            .disabled(model.isLoadingSelection)
            .accessibilityIdentifier("bundle-\(bundle.id)")
          }
        }
      }

      if !model.trackChoices.isEmpty {
        Section("音轨与合奏") {
          Picker(
            "试听",
            selection: Binding(
              get: { model.midiPlaybackMode },
              set: { model.setMIDIPlaybackMode($0) }
            )
          ) {
            ForEach(MIDIPlaybackMode.allCases) { mode in
              Text(mode.label).tag(mode)
            }
          }
          .pickerStyle(.segmented)
          .accessibilityIdentifier("midi-playback-mode")

          HStack {
            Button("全部启用") {
              model.enableAllTracks()
            }
            .accessibilityIdentifier("mixer-enable-all")
            Button("仅听当前") {
              model.listenToSelectedTrack()
            }
            .disabled(model.editor == nil)
            .accessibilityIdentifier("mixer-current-track")
            Spacer()
            Text("\(model.audibleTrackCount) 轨可听")
              .font(.caption)
              .foregroundStyle(.secondary)
          }

          ForEach(model.trackChoices) { track in
            VStack(alignment: .leading, spacing: 5) {
              HStack(spacing: 6) {
                Button {
                  model.chooseTrack(track.id)
                } label: {
                  HStack {
                    VStack(alignment: .leading, spacing: 2) {
                      Text(track.label)
                        .lineLimit(1)
                      Text(
                        "\(track.instrument ?? "未知乐器") · \(track.eventCount) 音符"
                      )
                      .font(.caption2)
                      .foregroundStyle(.secondary)
                    }
                    Spacer()
                    if model.editor?.selectedTrack.id == track.id {
                      Image(systemName: "checkmark.circle.fill")
                        .foregroundStyle(.tint)
                    }
                  }
                  .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .disabled(model.isLoadingSelection)
                .accessibilityIdentifier("track-\(track.id)")

                Button("M") {
                  model.toggleMute(track.id)
                }
                .buttonStyle(.bordered)
                .tint(
                  model.isTrackMuted(track.id) ? .orange : .secondary
                )
                .controlSize(.small)
                .accessibilityLabel("静音 \(track.label)")
                .accessibilityIdentifier("mute-\(track.id)")

                Button("S") {
                  model.toggleSolo(track.id)
                }
                .buttonStyle(.bordered)
                .tint(
                  model.isTrackSoloed(track.id) ? .blue : .secondary
                )
                .controlSize(.small)
                .accessibilityLabel("独奏 \(track.label)")
                .accessibilityIdentifier("solo-\(track.id)")
              }
              HStack(spacing: 6) {
                Image(
                  systemName: model.isTrackMuted(track.id)
                    ? "speaker.slash.fill"
                    : "speaker.wave.2.fill"
                )
                .foregroundStyle(
                  model.isTrackMuted(track.id) ? .orange : .secondary
                )
                Slider(
                  value: Binding(
                    get: { model.volume(for: track.id) },
                    set: {
                      model.setTrackVolume($0, trackID: track.id)
                    }
                  ),
                  in: 0...1
                )
                .accessibilityLabel("\(track.label) 音量")
                Text(
                  model.volume(for: track.id).formatted(
                    .percent.precision(.fractionLength(0))
                  )
                )
                .font(.caption2.monospacedDigit())
                .frame(width: 34, alignment: .trailing)
              }
            }
            .padding(.vertical, 3)
          }
          if model.hasEnhancedVoiceTrack {
            Text(
              "原始、补漏候选和增强主唱是同一旋律的三个版本；合奏时只播放当前选择的版本，不会重复叠音。"
            )
            .font(.caption2)
            .foregroundStyle(.secondary)
          }
          Text("点名称编辑该轨；M 静音，S 独奏。乐器名称是模型预测，可能误分类。")
            .font(.caption2)
            .foregroundStyle(.secondary)
        }
      }

      if !model.melodyGaps.isEmpty {
        Section("主旋律覆盖") {
          Label(
            "\(model.melodyCoverageTrackLabel) 有 \(model.melodyGaps.count) 段 ≥3 秒的疑似空缺",
            systemImage: "waveform.path.badge.minus"
          )
          .foregroundStyle(.orange)
          Text(
            "合计约 \(formatTime(model.melodyGapDuration))。这表示时间覆盖不足，不代表已识别音符不准。"
          )
          .font(.caption)
          .foregroundStyle(.secondary)
          Button("跳到下一处空缺", systemImage: "forward.end") {
            model.seekToNextMelodyGap()
          }
          .accessibilityIdentifier("next-melody-gap")
          ForEach(Array(model.melodyGaps.prefix(4))) { gap in
            VStack(alignment: .leading, spacing: 2) {
              Text(
                "\(formatTime(gap.startSec))–\(formatTime(gap.endSec)) · \(formatTime(gap.duration))"
              )
              .font(.caption.monospacedDigit())
              Text(
                "同期其他 \(gap.otherTrackCount) 轨有 \(gap.otherNoteCount) 个音符，可逐轨独奏寻找补全候选"
              )
              .font(.caption2)
              .foregroundStyle(.secondary)
            }
          }
          Text("原始 voice 不会被覆盖；增强主唱始终保留到原始音符与补漏候选的来源。")
            .font(.caption2)
            .foregroundStyle(.secondary)
        }
      }

      if let editor = model.editor {
        Section("当前编辑音轨") {
          LabeledContent("名称", value: editor.selectedTrack.label)
          LabeledContent("音符", value: "\(editor.notes.count)")
          Text("钢琴窗只编辑当前轨；合奏试听与完整多轨不会覆盖模型原始 JSONL。")
            .font(.caption)
            .foregroundStyle(.secondary)
        }
      }
    }
    .safeAreaInset(edge: .bottom) {
      HStack(spacing: 8) {
        if model.isLoadingProject || model.isLoadingSelection {
          ProgressView()
            .controlSize(.small)
        }
        Text(model.statusMessage)
          .font(.caption)
          .foregroundStyle(.secondary)
      }
      .frame(maxWidth: .infinity, alignment: .leading)
      .padding(10)
      .background(.bar)
      .accessibilityIdentifier("status-message")
    }
  }

  private var hyakActionTitle: String {
    switch model.hyakConnectionState {
    case .connected: "检查 Hyak"
    case .checking: "正在连接"
    case .unknown, .loginRequired: "连接 Hyak"
    }
  }

  private var hyakActionIcon: String {
    switch model.hyakConnectionState {
    case .connected: "network.badge.shield.half.filled"
    case .checking: "arrow.triangle.2.circlepath"
    case .unknown: "network"
    case .loginRequired: "network.slash"
    }
  }

  private var hyakActionHelp: String {
    switch model.hyakConnectionState {
    case .connected: "检查当前连接并恢复任务状态"
    case .checking: "正在等待 Hyak 登录"
    case .unknown: "打开 Terminal 登录 Hyak"
    case .loginRequired: "重新登录；远端作业不会被重复提交"
    }
  }

  private var hyakConnectionLabel: String {
    switch model.hyakConnectionState {
    case .unknown: "未检查"
    case .checking: "检查中"
    case .connected: "已连接"
    case .loginRequired: "需要重新登录"
    }
  }

  @ViewBuilder
  private var detail: some View {
    if model.isLoadingProject {
      VStack(spacing: 14) {
        ProgressView()
          .controlSize(.large)
        Text("正在后台校验项目")
          .font(.headline)
        Text("界面可以继续响应；不会重新运行模型。")
          .foregroundStyle(.secondary)
      }
      .frame(maxWidth: .infinity, maxHeight: .infinity)
    } else if let editor = model.editor {
      WorkspaceView(
        model: model,
        transport: model.transport,
        editor: editor
      )
    } else if model.hasActiveBetaJob {
      EmptyStateView(
        icon: "hourglass",
        title: "Hyak 正在识别",
        message: "Job \(model.betaJobID ?? "准备中") 会在远端继续运行；应用会自动刷新，完成后取回并打开完整多轨。"
      )
    } else if let snapshot = model.snapshot {
      EmptyStateView(
        icon: "music.note.list",
        title: "请选择一条音轨",
        message: "这个结果含 \(snapshot.tracks.count) 条 MuScriptor 原始音轨；voice 存在时会自动作为主唱候选入口，并单独显示长空缺。"
      )
    } else if model.catalog != nil {
      EmptyStateView(
        icon: "shippingbox",
        title: "请选择识别版本",
        message: "这个项目有多个结果版本，请从左侧选择要试听和编辑的一版。"
      )
    } else {
      LibraryHomeView(
        projects: model.libraryProjects,
        isBusy: model.isBetaBusy || model.hasActiveBetaJob,
        onTranscribe: importAudioPanel,
        onOpenProject: openProjectPanel,
        onSelectProject: model.openProject
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
      model.openAuthorizedProject(url)
    }
  }

  private func importAudioPanel() {
    let panel = NSOpenPanel()
    panel.title = "选择要识别的歌曲"
    panel.canChooseDirectories = false
    panel.canChooseFiles = true
    panel.allowsMultipleSelection = false
    panel.allowedContentTypes = [.audio]
    if panel.runModal() == .OK, let url = panel.url {
      model.transcribeSong(url)
    }
  }

  private func exportTrackPanel() {
    let panel = NSSavePanel()
    panel.title = "导出当前音轨修正版 MIDI"
    panel.nameFieldStringValue = "\(model.editor?.selectedTrack.id ?? "track").performance.mid"
    if let midi = UTType(filenameExtension: "mid") {
      panel.allowedContentTypes = [midi]
    }
    if panel.runModal() == .OK, let url = panel.url {
      model.exportMIDI(to: url)
    }
  }

  private func exportArrangementPanel() {
    let panel = NSSavePanel()
    panel.title = "导出完整多轨修正版 MIDI"
    panel.nameFieldStringValue =
      "\(model.catalog?.manifest.projectID ?? "song").multitrack.mid"
    if let midi = UTType(filenameExtension: "mid") {
      panel.allowedContentTypes = [midi]
    }
    if panel.runModal() == .OK, let url = panel.url {
      model.exportArrangementMIDI(to: url)
    }
  }

  private func exportMixPanel() {
    let panel = NSSavePanel()
    panel.title = "导出当前可听混音 MIDI"
    panel.nameFieldStringValue =
      "\(model.catalog?.manifest.projectID ?? "song").mix.mid"
    if let midi = UTType(filenameExtension: "mid") {
      panel.allowedContentTypes = [midi]
    }
    if panel.runModal() == .OK, let url = panel.url {
      model.exportCurrentMixMIDI(to: url)
    }
  }
}

private struct LibraryHomeView: View {
  let projects: [LocalProjectItem]
  let isBusy: Bool
  let onTranscribe: () -> Void
  let onOpenProject: () -> Void
  let onSelectProject: (URL) -> Void

  var body: some View {
    ScrollView {
      VStack(alignment: .leading, spacing: 26) {
        VStack(alignment: .leading, spacing: 8) {
          Label("AMT Studio", systemImage: "waveform")
            .font(.system(size: 34, weight: .bold))
          Text("把一首歌变成可以试听、分轨和编辑的 MIDI。模型在 Hyak GPU 运行，Mac 负责项目与编辑。")
            .font(.title3)
            .foregroundStyle(.secondary)
        }

        HStack(spacing: 16) {
          Button(action: onTranscribe) {
            Label("识别一首新歌", systemImage: "waveform.badge.plus")
              .font(.headline)
              .frame(maxWidth: .infinity, minHeight: 70)
          }
          .buttonStyle(.borderedProminent)
          .disabled(isBusy)

          Button(action: onOpenProject) {
            Label("打开已有项目", systemImage: "folder")
              .font(.headline)
              .frame(maxWidth: .infinity, minHeight: 70)
          }
          .buttonStyle(.bordered)
        }

        if !projects.isEmpty {
          VStack(alignment: .leading, spacing: 12) {
            Text("以前的音乐")
              .font(.title2.bold())
            LazyVGrid(
              columns: [
                GridItem(.flexible(), spacing: 12),
                GridItem(.flexible(), spacing: 12),
              ],
              spacing: 12
            ) {
              ForEach(Array(projects.prefix(8))) { project in
                Button {
                  onSelectProject(project.url)
                } label: {
                  HStack(spacing: 12) {
                    Image(
                      systemName: project.hasResults
                        ? "music.note.house.fill"
                        : "hourglass"
                    )
                    .font(.title2)
                    .foregroundStyle(
                      project.hasResults ? Color.accentColor : Color.secondary
                    )
                    VStack(alignment: .leading, spacing: 4) {
                      Text(project.title)
                        .font(.headline)
                        .lineLimit(2)
                      Text(project.stateLabel)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    }
                    Spacer()
                    Image(systemName: "chevron.right")
                      .foregroundStyle(.tertiary)
                  }
                  .padding(14)
                  .frame(maxWidth: .infinity, minHeight: 82)
                  .background(.quaternary.opacity(0.45))
                  .clipShape(RoundedRectangle(cornerRadius: 12))
                }
                .buttonStyle(.plain)
              }
            }
          }
        }

        Label(
          "已经提交的 Hyak 作业在关闭窗口或 SSH 登录过期后仍会继续；重新连接只恢复查询，不会重复提交。",
          systemImage: "checkmark.shield"
        )
        .font(.callout)
        .foregroundStyle(.secondary)
      }
      .frame(maxWidth: 920, alignment: .leading)
      .padding(44)
      .frame(maxWidth: .infinity, alignment: .top)
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
  let transport: AudioTransport
  let editor: EditorProject

  var body: some View {
    HSplitView {
      VStack(spacing: 0) {
        TransportControlsView(
          model: model,
          transport: transport,
          timelineDuration: timelineDuration
        )
        Divider()
        AudioWaveformPanel(
          transport: transport,
          timelineDuration: timelineDuration
        )
        .frame(height: 90)
        Divider()
        PianoRollView(
          notes: editor.notes,
          transport: transport,
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
      editor.snapshot.notes.map(\.offsetSec).max() ?? 1,
      1
    )
  }

  @ViewBuilder
  private var inspector: some View {
    VStack(spacing: 0) {
      ConfidenceReviewPanel(model: model)
      Divider()
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
}

private struct TransportControlsView: View {
  @ObservedObject var model: AppModel
  @ObservedObject var transport: AudioTransport
  let timelineDuration: Double

  var body: some View {
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
        .accessibilityIdentifier("transport-position")
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
          "MIDI",
          isOn: Binding(
            get: { transport.midiEnabled },
            set: { transport.setMIDIEnabled($0) }
          )
        )
        .toggleStyle(.checkbox)
        .disabled(!transport.midiAvailable)

        Label(
          model.midiPlaybackMode == .mix
            ? "合奏 \(model.audibleTrackCount) 轨"
            : "当前音轨",
          systemImage: model.midiPlaybackMode == .mix
            ? "music.note.list"
            : "music.note"
        )
        .font(.caption)
        .foregroundStyle(.secondary)
      }
      HStack(spacing: 10) {
        Label("原曲音量", systemImage: "waveform")
          .font(.caption)
        Slider(
          value: Binding(
            get: { transport.originalVolume },
            set: { model.setOriginalVolume($0) }
          ),
          in: 0...1
        )
        .frame(maxWidth: 150)
        .accessibilityIdentifier("original-volume")
        Text(
          transport.originalVolume.formatted(
            .percent.precision(.fractionLength(0))
          )
        )
        .font(.caption.monospacedDigit())
        .frame(width: 36, alignment: .trailing)

        Label("MIDI 总音量", systemImage: "pianokeys")
          .font(.caption)
        Slider(
          value: Binding(
            get: { model.midiMasterVolume },
            set: { model.setMIDIMasterVolume($0) }
          ),
          in: 0...1
        )
        .frame(maxWidth: 150)
        .accessibilityIdentifier("midi-master-volume")
        Text(
          model.midiMasterVolume.formatted(
            .percent.precision(.fractionLength(0))
          )
        )
        .font(.caption.monospacedDigit())
        .frame(width: 36, alignment: .trailing)
        if transport.midiLoading {
          ProgressView("正在更新 MIDI…")
            .controlSize(.small)
            .font(.caption)
        }
        Spacer()
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
}

private struct AudioWaveformPanel: View {
  @ObservedObject var transport: AudioTransport
  let timelineDuration: Double

  var body: some View {
    AudioWaveformView(
      samples: transport.waveformSamples,
      isLoading: transport.waveformLoading,
      errorMessage: transport.waveformErrorMessage,
      currentTime: transport.currentTime,
      audioDuration: transport.duration,
      timelineDuration: timelineDuration
    )
  }
}

private struct AudioWaveformView: View {
  let samples: [Float]
  let isLoading: Bool
  let errorMessage: String?
  let currentTime: Double
  let audioDuration: Double
  let timelineDuration: Double

  var body: some View {
    GeometryReader { _ in
      Canvas { context, size in
        if !samples.isEmpty {
          let centerY = size.height / 2
          let usableHeight = max(1, size.height - 24) / 2
          let audioWidth = WaveformLayout.audioWidth(
            viewWidth: size.width,
            audioDuration: audioDuration,
            timelineDuration: timelineDuration
          )
          var path = Path()
          for (index, sample) in samples.enumerated() {
            let x =
              samples.count == 1
              ? 0
              : Double(index) / Double(samples.count - 1) * audioWidth
            let y = centerY - Double(sample) * usableHeight
            if index == 0 {
              path.move(to: CGPoint(x: x, y: y))
            } else {
              path.addLine(to: CGPoint(x: x, y: y))
            }
          }
          for index in samples.indices.reversed() {
            let x =
              samples.count == 1
              ? 0
              : Double(index) / Double(samples.count - 1) * audioWidth
            let y = centerY + Double(samples[index]) * usableHeight
            path.addLine(to: CGPoint(x: x, y: y))
          }
          path.closeSubpath()
          context.fill(path, with: .color(.accentColor.opacity(0.42)))
        }
        let cursorX =
          min(
            1,
            max(0, currentTime / max(0.001, timelineDuration))
          ) * size.width
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
      Text("原曲真实音频波形")
        .font(.caption2)
        .foregroundStyle(.secondary)
        .padding(4)
      if isLoading {
        ProgressView("正在读取音频波形…")
          .controlSize(.small)
          .frame(maxWidth: .infinity, maxHeight: .infinity)
      } else if samples.isEmpty {
        Text(errorMessage ?? "当前音频没有可显示的波形采样")
          .font(.caption)
          .foregroundStyle(
            errorMessage == nil ? Color.secondary : Color.orange
          )
          .frame(maxWidth: .infinity, maxHeight: .infinity)
      }
    }
    .background(.quaternary.opacity(0.35))
    .accessibilityElement(children: .combine)
    .accessibilityLabel("原曲真实音频波形")
    .accessibilityValue(
      isLoading
        ? "正在加载"
        : errorMessage != nil
          ? "加载失败"
          : samples.isEmpty
            ? "无采样"
            : "已加载 \(samples.count) 个采样"
    )
    .accessibilityIdentifier("audio-waveform")
  }
}

enum WaveformLayout {
  static func audioWidth(
    viewWidth: Double,
    audioDuration: Double,
    timelineDuration: Double
  ) -> Double {
    let boundedViewWidth = max(0, viewWidth)
    guard audioDuration.isFinite, timelineDuration.isFinite,
      audioDuration > 0, timelineDuration > 0
    else {
      return 0
    }
    return min(
      boundedViewWidth,
      boundedViewWidth * audioDuration / timelineDuration
    )
  }
}

private struct ConfidenceReviewPanel: View {
  @ObservedObject var model: AppModel

  var body: some View {
    VStack(alignment: .leading, spacing: 8) {
      HStack {
        Label("待复核", systemImage: "exclamationmark.magnifyingglass")
          .font(.headline)
        Spacer()
        Text(model.reviewPositionDescription)
          .font(.caption.monospacedDigit())
          .foregroundStyle(.secondary)
      }
      HStack {
        Text("当前轨原始置信度 ≤")
          .font(.caption)
        Slider(
          value: $model.reviewConfidenceThreshold,
          in: 0...1,
          step: 0.05
        )
        .accessibilityIdentifier("review-confidence-threshold")
        Text(
          model.reviewConfidenceThreshold.formatted(
            .percent.precision(.fractionLength(0))
          )
        )
        .font(.caption.monospacedDigit())
        .frame(width: 38, alignment: .trailing)
      }
      HStack {
        Button("上一个") {
          model.selectPreviousReviewNote()
        }
        .disabled(model.reviewNotes.isEmpty)
        .accessibilityIdentifier("review-previous")
        Button("下一个") {
          model.selectNextReviewNote()
        }
        .disabled(model.reviewNotes.isEmpty)
        .accessibilityIdentifier("review-next")
        Spacer()
        Text("\(model.reviewNotes.count) 个")
          .font(.caption)
      }
      Text(
        "只筛选当前候选轨已提供的原始置信度；不同模型之间不可横向比较。"
      )
      .font(.caption2)
      .foregroundStyle(.secondary)
      if model.notesWithoutConfidenceCount > 0 {
        Text(
          "\(model.notesWithoutConfidenceCount) 个音符没有置信度，未混入待复核队列。"
        )
        .font(.caption2)
        .foregroundStyle(.secondary)
      }
    }
    .padding(12)
  }
}

private struct PianoRollView: View {
  let notes: [EditorNote]
  let transport: AudioTransport
  let duration: Double
  @Binding var selectedNoteID: String?
  let onCommit: (EditorNote) -> Void

  private let pointsPerSecond = 28.0
  private let pointsPerSemitone = 14.0
  private let segmentDuration = 10.0

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
    let segmentCount = max(1, Int(ceil(duration / segmentDuration)))
    let notesBySegment = Dictionary(grouping: notes) {
      min(
        segmentCount - 1,
        max(0, Int($0.onsetSec / segmentDuration))
      )
    }

    ScrollView([.horizontal, .vertical]) {
      ZStack(alignment: .topLeading) {
        PianoGrid(
          duration: duration,
          minimumPitch: minimumPitch,
          maximumPitch: maximumPitch,
          pointsPerSecond: pointsPerSecond,
          pointsPerSemitone: pointsPerSemitone
        )
        LazyHStack(alignment: .top, spacing: 0) {
          ForEach(0..<segmentCount, id: \.self) { index in
            PianoRollSegment(
              notes: notesBySegment[index] ?? [],
              timeOrigin: Double(index) * segmentDuration,
              minimumPitch: minimumPitch,
              maximumPitch: maximumPitch,
              pointsPerSecond: pointsPerSecond,
              pointsPerSemitone: pointsPerSemitone,
              selectedNoteID: $selectedNoteID,
              onCommit: onCommit
            )
            .frame(
              width: segmentDuration * pointsPerSecond,
              height: contentHeight
            )
          }
        }
        PianoRollPlayhead(
          transport: transport,
          pointsPerSecond: pointsPerSecond,
          contentHeight: contentHeight
        )
      }
      .frame(width: contentWidth, height: contentHeight)
    }
    .background(Color(nsColor: .textBackgroundColor))
    .accessibilityIdentifier("piano-roll")
  }
}

private struct PianoRollSegment: View {
  let notes: [EditorNote]
  let timeOrigin: Double
  let minimumPitch: Double
  let maximumPitch: Double
  let pointsPerSecond: Double
  let pointsPerSemitone: Double
  @Binding var selectedNoteID: String?
  let onCommit: (EditorNote) -> Void

  var body: some View {
    ZStack(alignment: .topLeading) {
      ForEach(notes) { note in
        NoteBlock(
          note: note,
          timeOrigin: timeOrigin,
          minimumPitch: minimumPitch,
          maximumPitch: maximumPitch,
          pointsPerSecond: pointsPerSecond,
          pointsPerSemitone: pointsPerSemitone,
          selected: note.id == selectedNoteID,
          onSelect: { selectedNoteID = note.id },
          onCommit: onCommit
        )
      }
    }
  }
}

private struct PianoRollPlayhead: View {
  @ObservedObject var transport: AudioTransport
  let pointsPerSecond: Double
  let contentHeight: Double

  var body: some View {
    Rectangle()
      .fill(.red.opacity(0.85))
      .frame(width: 1, height: contentHeight)
      .offset(x: transport.currentTime * pointsPerSecond)
      .allowsHitTesting(false)
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
  let timeOrigin: Double
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
      (note.onsetSec - timeOrigin) * pointsPerSecond
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
        .accessibilityIdentifier("note-pitch-stepper")
        TextField(
          "起点（秒）",
          value: $onset,
          format: .number.precision(.fractionLength(3))
        )
        .accessibilityIdentifier("note-onset")
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
        .accessibilityIdentifier("note-offset")
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
