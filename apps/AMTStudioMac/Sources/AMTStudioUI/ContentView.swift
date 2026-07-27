import AppKit
import SwiftUI
import UniformTypeIdentifiers

#if canImport(AMTStudioCore)
  import AMTStudioCore
#endif

public struct ContentView: View {
  @ObservedObject private var model: AppModel
  @State private var isShowingAppearanceSettings = false
  @State private var isConfirmingGapRecovery = false

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
        Menu(model.computeMode.label, systemImage: model.computeMode.icon) {
          ForEach(ComputeMode.allCases) { mode in
            Button {
              model.setComputeMode(mode)
            } label: {
              Label(
                mode.label,
                systemImage: model.computeMode == mode
                  ? "checkmark.circle.fill"
                  : mode.icon
              )
            }
          }
        }
        .disabled(model.isBetaBusy || model.hasActiveBetaJob)
        .help("选择下一首歌使用 Hyak、本机 GPU 或本机 CPU")
        .accessibilityIdentifier("compute-mode-menu")
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
            : transcriptionHelp
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
        Menu("项目", systemImage: "folder") {
          Button("打开已有项目", systemImage: "folder") {
            openProjectPanel()
          }
          .disabled(model.isLoadingProject)
          Button("在 Finder 中显示结果", systemImage: "folder.badge.gearshape") {
            model.revealCurrentProject()
          }
          .disabled(model.catalog == nil)
          Divider()
          Button("保存当前修改", systemImage: "tray.and.arrow.down") {
            model.save()
          }
          .disabled(model.editor == nil)
        }
        .accessibilityIdentifier("project-actions")
        Menu("导出", systemImage: "square.and.arrow.down") {
          Button("整个识别版本（完整多轨 MIDI）") {
            exportArrangementPanel()
          }
          .disabled(model.snapshot == nil || model.isLoadingSelection)
          Divider()
          Button("当前编辑音轨") {
            exportTrackPanel()
          }
          .disabled(model.editor == nil)
          Button("当前混音（静音与音量生效）") {
            exportMixPanel()
          }
          .disabled(model.editor == nil)
        }
        .help("导出完整多轨、当前音轨或当前可听混音")
        .accessibilityIdentifier("export-actions")
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
        Button("外观", systemImage: "slider.horizontal.3") {
          isShowingAppearanceSettings = true
        }
        .help("切换精密模式或炫酷模式")
        .accessibilityIdentifier("appearance-settings")
      }
    }
    .background(theme.canvasGradient)
    .tint(theme.accent)
    .preferredColorScheme(.dark)
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
    .sheet(isPresented: $isShowingAppearanceSettings) {
      AppearanceSettingsView(model: model)
    }
    .confirmationDialog(
      "重新分析所选空缺？",
      isPresented: $isConfirmingGapRecovery,
      titleVisibility: .visible
    ) {
      Button(
        "提交到 \(model.computeMode.label)",
        role: .none
      ) {
        model.recoverSelectedGaps()
      }
      Button("取消", role: .cancel) {}
    } message: {
      Text(
        "会把所选 \(model.selectedMelodyGaps.count) 段合并为一个任务，只重算这些片段并生成新版本；当前识别版本不会被覆盖。"
      )
    }
  }

  @ViewBuilder
  private var sidebar: some View {
    List {
      AMTBrandHeader(theme: theme)
        .listRowInsets(
          EdgeInsets(top: 18, leading: 14, bottom: 16, trailing: 14)
        )
        .listRowBackground(Color.clear)

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
            .listRowInsets(
              EdgeInsets(top: 5, leading: 12, bottom: 5, trailing: 10)
            )
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

      Section("计算") {
        Picker(
          "下一首歌",
          selection: Binding(
            get: { model.computeMode },
            set: { model.setComputeMode($0) }
          )
        ) {
          ForEach(ComputeMode.allCases) { mode in
            Text(mode.label).tag(mode)
          }
        }
        .disabled(model.isBetaBusy || model.hasActiveBetaJob)
        .accessibilityIdentifier("compute-mode-picker")
        Text(model.computeMode.detail)
          .font(.caption)
          .foregroundStyle(.secondary)

        if model.computeMode == .hyak {
          LabeledContent("Hyak 连接", value: hyakConnectionLabel)
        } else {
          Button("检查本机环境", systemImage: "checkmark.shield") {
            model.checkLocalCompute()
          }
          .disabled(model.isCheckingLocalCompute)
          if model.isCheckingLocalCompute {
            ProgressView()
              .controlSize(.small)
          }
          Text(model.localReadinessMessage)
            .font(.caption)
            .foregroundStyle(.secondary)
        }

        if let jobID = model.betaJobID {
          LabeledContent(
            model.activeComputeMode == .hyak ? "Job ID" : "任务 ID",
            value: jobID
          )
          LabeledContent(
            "运行位置",
            value: model.activeComputeMode?.label ?? "未知"
          )
          LabeledContent(
            "任务",
            value: model.betaSlurmState ?? "准备中"
          )
        }
        if model.activeComputeMode == .hyak
          && model.hyakConnectionState == .loginRequired
        {
          Label(
            "登录过期不会终止远端作业。重新登录后会自动查询并取回结果。",
            systemImage: "exclamationmark.arrow.triangle.2.circlepath"
          )
          .font(.caption)
          .foregroundStyle(.orange)
        } else if model.computeMode == .hyak {
          Text("Hyak 是默认方式；关闭 Mac 窗口不会终止已提交的 Slurm 作业。")
            .font(.caption)
            .foregroundStyle(.secondary)
        } else {
          Text("本机任务会降低 CPU 后台优先级，但仍可能明显占用处理器、GPU 和统一内存。")
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

          ForEach(model.visibleTrackChoices) { track in
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
              "默认只显示一条增强主旋律；合奏与标准完整多轨不会叠加原始、补漏和增强三个版本。"
            )
            .font(.caption2)
            .foregroundStyle(.secondary)
            Toggle(
              "显示主旋律诊断版本",
              isOn: Binding(
                get: { model.showMelodyVersions },
                set: { model.setShowMelodyVersions($0) }
              )
            )
            .toggleStyle(.switch)
          }
          Text("点名称编辑该轨；M 静音，S 独奏。乐器名称是模型预测，可能误分类。")
            .font(.caption2)
            .foregroundStyle(.secondary)
        }
      }

      if let selectedBundleID = model.selectedBundleID {
        Section("导出当前识别版本") {
          Button {
            exportArrangementPanel()
          } label: {
            Label(
              "导出整个版本 MIDI",
              systemImage: "square.and.arrow.down"
            )
            .frame(maxWidth: .infinity)
          }
          .buttonStyle(.borderedProminent)
          .accessibilityIdentifier("sidebar-export-version-midi")
          Text(
            "把版本 \(selectedBundleID) 的全部伴奏轨与一条默认主旋律保存到同一个 .mid 文件。"
          )
          .font(.caption)
          .foregroundStyle(.secondary)
          Text("此导出不受 M、S 和音量设置影响；要按当前试听状态导出，请用顶部“其他导出”。")
            .font(.caption2)
            .foregroundStyle(.secondary)
        }
      } else if model.hasActiveBetaJob {
        Section("导出") {
          Text("识别完成并取回结果后，这里会出现“导出整个版本 MIDI”。")
            .font(.caption)
            .foregroundStyle(.secondary)
        }
      }

      if !model.melodyGaps.isEmpty {
        Section("当前音轨空缺") {
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
          HStack {
            Button("全选") {
              model.selectAllGaps()
            }
            .disabled(
              model.selectedMelodyGaps.count == model.melodyGaps.count
            )
            Button("清除") {
              model.clearGapSelection()
            }
            .disabled(model.selectedMelodyGaps.isEmpty)
            Spacer()
            Text("已选 \(model.selectedMelodyGaps.count) 段")
              .font(.caption)
              .foregroundStyle(.secondary)
          }
          ForEach(model.melodyGaps) { gap in
            Toggle(
              isOn: Binding(
                get: { model.isGapSelected(gap) },
                set: { model.setGapSelected(gap, selected: $0) }
              )
            ) {
              VStack(alignment: .leading, spacing: 2) {
                Text(
                  "\(formatTime(gap.startSec))–\(formatTime(gap.endSec)) · \(formatTime(gap.duration))"
                )
                .font(.caption.monospacedDigit())
                Text(
                  "同期其他 \(gap.otherTrackCount) 轨有 \(gap.otherNoteCount) 个音符"
                )
                .font(.caption2)
                .foregroundStyle(.secondary)
              }
            }
            .toggleStyle(.checkbox)
            .accessibilityIdentifier("gap-selection-\(gap.id)")
          }
          Button {
            isConfirmingGapRecovery = true
          } label: {
            Label(
              model.hasActiveBetaJob
                && model.betaTaskKind == "targeted_gap_recovery"
                ? "所选空缺正在重算"
                : "重新分析所选 \(model.selectedMelodyGaps.count) 段",
              systemImage: "arrow.triangle.2.circlepath.circle"
            )
            .frame(maxWidth: .infinity)
          }
          .buttonStyle(.borderedProminent)
          .disabled(
            model.selectedMelodyGaps.isEmpty
              || model.selectedMelodyGaps.count > 16
              || model.isBetaBusy
              || model.hasActiveBetaJob
          )
          .accessibilityIdentifier("submit-selected-gap-recovery")
          Text(
            "多段会合并为一个 \(model.computeMode.label) 任务；只上传/读取所需项目数据，不重跑整首。结果作为新识别版本返回。"
          )
          .font(.caption2)
          .foregroundStyle(.secondary)
          if model.hasActiveBetaJob
            && model.betaTaskKind == "targeted_gap_recovery"
          {
            Label(
              "Job \(model.betaJobID ?? "—") · \(model.betaSlurmState ?? "准备中")",
              systemImage: "clock.arrow.circlepath"
            )
            .font(.caption)
            .foregroundStyle(.orange)
          }
          Text("当前识别版本不会被覆盖；空白也可能是原曲本来没有该乐器，结果仍需试听。")
            .font(.caption2)
            .foregroundStyle(.secondary)
        }
      }

      if let editor = model.editor {
        Section("当前编辑音轨") {
          LabeledContent("名称", value: editor.selectedTrack.label)
          LabeledContent("音符", value: "\(editor.notes.count)")
          Text("钢琴窗只编辑当前轨；合奏试听与标准完整多轨不会覆盖模型原始 JSONL。")
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
      .background(theme.raisedSurface.opacity(0.96))
      .overlay(alignment: .top) {
        Rectangle()
          .fill(theme.border)
          .frame(height: 1)
      }
      .accessibilityIdentifier("status-message")
    }
    .scrollContentBackground(.hidden)
    .background(theme.sidebar)
    .contentMargins(.horizontal, 8, for: .scrollContent)
  }

  private var theme: AMTTheme {
    AMTTheme(mode: model.appearanceMode)
  }

  private var hyakActionTitle: String {
    return switch model.hyakConnectionState {
    case .connected: "检查 Hyak"
    case .checking: "正在连接"
    case .unknown, .loginRequired: "连接 Hyak"
    }
  }

  private var hyakActionIcon: String {
    return switch model.hyakConnectionState {
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

  private var transcriptionHelp: String {
    switch model.computeMode {
    case .hyak:
      "选择音频并在 Hyak L40 GPU 上识别"
    case .localGPU:
      "选择音频并在本机 Apple GPU 后台识别"
    case .localCPU:
      "选择音频并在本机 CPU 低优先级后台识别"
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
        editor: editor,
        theme: theme
      )
    } else if model.hasActiveBetaJob {
      JobProgressView(model: model, theme: theme)
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
        computeMode: model.computeMode,
        theme: theme,
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
    panel.title = "导出整个识别版本 MIDI"
    if let selectedBundleID = model.selectedBundleID {
      panel.message =
        "当前版本：\(selectedBundleID)\n包含全部伴奏轨，并只保留一条默认主旋律。"
    }
    panel.nameFieldStringValue =
      "\(model.catalog?.manifest.projectID ?? "song").full-arrangement.mid"
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

private struct AMTBrandHeader: View {
  let theme: AMTTheme

  var body: some View {
    HStack(spacing: 11) {
      ZStack {
        RoundedRectangle(cornerRadius: 8, style: .continuous)
          .fill(theme.accentGradient.opacity(0.18))
        Image(systemName: "waveform.path")
          .font(.system(size: 19, weight: .semibold))
          .foregroundStyle(theme.accentGradient)
      }
      .frame(width: 38, height: 38)
      VStack(alignment: .leading, spacing: 2) {
        Text("AMT Studio")
          .font(.system(size: 17, weight: .semibold, design: .rounded))
        Text(
          theme.mode == .precision
            ? "PRECISION SIGNAL LAB"
            : "SPECTRUM SIGNAL LAB"
        )
        .font(.system(size: 9, weight: .semibold, design: .monospaced))
        .tracking(1.1)
        .foregroundStyle(theme.mutedText)
      }
    }
  }
}

private struct AppearanceSettingsView: View {
  @ObservedObject var model: AppModel
  @Environment(\.dismiss) private var dismiss

  var body: some View {
    let theme = AMTTheme(mode: model.appearanceMode)
    VStack(alignment: .leading, spacing: 22) {
      HStack {
        VStack(alignment: .leading, spacing: 5) {
          Text("外观")
            .font(.system(size: 24, weight: .bold, design: .rounded))
          Text("两种模式共用完全相同的功能、项目和识别结果。")
            .foregroundStyle(theme.mutedText)
        }
        Spacer()
        Button("完成") {
          dismiss()
        }
        .keyboardShortcut(.defaultAction)
      }

      HStack(spacing: 14) {
        ForEach(AMTAppearanceMode.allCases) { mode in
          let candidateTheme = AMTTheme(mode: mode)
          Button {
            model.setAppearanceMode(mode)
          } label: {
            VStack(alignment: .leading, spacing: 13) {
              HStack {
                Image(
                  systemName: mode == .precision
                    ? "scope"
                    : "sparkles"
                )
                .font(.title2)
                .foregroundStyle(candidateTheme.accentGradient)
                Spacer()
                Image(
                  systemName: model.appearanceMode == mode
                    ? "checkmark.circle.fill"
                    : "circle"
                )
                .foregroundStyle(
                  model.appearanceMode == mode
                    ? candidateTheme.accent
                    : candidateTheme.quietText
                )
              }
              VStack(alignment: .leading, spacing: 5) {
                Text(mode.label)
                  .font(.headline)
                Text(mode.detail)
                  .font(.caption)
                  .foregroundStyle(candidateTheme.mutedText)
                  .fixedSize(horizontal: false, vertical: true)
              }
              HStack(spacing: 5) {
                ForEach(0..<4, id: \.self) { index in
                  Capsule()
                    .fill(
                      index == 0
                        ? candidateTheme.accent
                        : index == 3
                          ? candidateTheme.active
                          : candidateTheme.raisedSurface
                    )
                    .frame(height: 6)
                }
              }
            }
            .padding(16)
            .frame(maxWidth: .infinity, minHeight: 172, alignment: .topLeading)
            .background(candidateTheme.surface)
            .overlay {
              RoundedRectangle(cornerRadius: 12, style: .continuous)
                .stroke(
                  model.appearanceMode == mode
                    ? candidateTheme.accent
                    : candidateTheme.border,
                  lineWidth: model.appearanceMode == mode ? 2 : 1
                )
            }
            .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
          }
          .buttonStyle(.plain)
          .accessibilityIdentifier("appearance-\(mode.rawValue)")
        }
      }

      Label(
        "外观切换不会重载歌曲、重新提交 Hyak 作业或改变任何 MIDI。",
        systemImage: "checkmark.shield"
      )
      .font(.callout)
      .foregroundStyle(theme.mutedText)
    }
    .padding(26)
    .frame(width: 570)
    .background(theme.canvasGradient)
    .preferredColorScheme(.dark)
  }
}

private struct JobProgressView: View {
  @ObservedObject var model: AppModel
  let theme: AMTTheme
  @State private var isConfirmingLocalStop = false

  private var phases: [(String, String)] {
    [
      (
        model.activeComputeMode == .hyak ? "arrow.up.circle" : "desktopcomputer",
        model.activeComputeMode == .hyak ? "上传并排队" : "创建本机任务"
      ),
      ("waveform", "整曲识别"),
      ("metronome", "速度与拍号"),
      ("scope", "检查缺口"),
      ("wand.and.stars", "自动补漏"),
      ("shippingbox", "打包结果"),
    ]
  }

  var body: some View {
    ZStack {
      theme.canvasGradient
      VStack(alignment: .leading, spacing: 28) {
        HStack(alignment: .top) {
          VStack(alignment: .leading, spacing: 8) {
            Text("CURRENT SESSION")
              .font(.system(size: 11, weight: .bold, design: .monospaced))
              .tracking(1.6)
              .foregroundStyle(theme.accent)
            Text(projectTitle)
              .font(.system(size: 30, weight: .bold, design: .rounded))
              .lineLimit(2)
            Text(stageDescription)
              .font(.title3)
              .foregroundStyle(theme.mutedText)
          }
          Spacer()
          VStack(alignment: .trailing, spacing: 7) {
            Label(
              model.betaSlurmState ?? "准备中",
              systemImage: "circle.fill"
            )
            .font(.caption.weight(.semibold))
            .foregroundStyle(theme.active)
            Text(
              "\(model.activeComputeMode == .hyak ? "JOB" : "TASK") \(model.betaJobID ?? "—")"
            )
            .font(.caption.monospaced())
            .foregroundStyle(theme.mutedText)
          }
        }

        VStack(alignment: .leading, spacing: 18) {
          Text("处理流程")
            .font(.headline)
          HStack(alignment: .top, spacing: 0) {
            ForEach(Array(phases.enumerated()), id: \.offset) { index, phase in
              VStack(spacing: 9) {
                ZStack {
                  Circle()
                    .fill(phaseFill(index))
                  Circle()
                    .stroke(phaseBorder(index), lineWidth: 1)
                  Image(systemName: phase.0)
                    .font(.system(size: 15, weight: .semibold))
                    .foregroundStyle(phaseForeground(index))
                }
                .frame(width: 38, height: 38)
                Text(phase.1)
                  .font(.caption.weight(index == currentPhase ? .semibold : .regular))
                  .foregroundStyle(
                    index <= currentPhase ? Color.white : theme.quietText
                  )
                  .multilineTextAlignment(.center)
                  .fixedSize(horizontal: false, vertical: true)
              }
              .frame(maxWidth: .infinity)
              if index < phases.count - 1 {
                Rectangle()
                  .fill(index < currentPhase ? theme.accent : theme.border)
                  .frame(maxWidth: 70, minHeight: 1, maxHeight: 1)
                  .padding(.top, 19)
              }
            }
          }
          .padding(.vertical, 10)
        }
        .padding(22)
        .background(theme.surface)
        .overlay {
          RoundedRectangle(cornerRadius: 12, style: .continuous)
            .stroke(theme.border, lineWidth: 1)
        }
        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))

        HStack(spacing: 12) {
          Button("刷新任务", systemImage: "arrow.clockwise") {
            model.refreshBetaJob()
          }
          .buttonStyle(.borderedProminent)
          .disabled(model.isBetaBusy)
          if model.activeComputeMode == .hyak {
            Button("检查 Hyak", systemImage: "network") {
              model.checkHyakConnection()
            }
            .buttonStyle(.bordered)
            .disabled(model.hyakConnectionState == .checking)
          } else {
            Button("停止本机任务", systemImage: "stop.circle") {
              isConfirmingLocalStop = true
            }
            .buttonStyle(.bordered)
            .disabled(model.isBetaBusy)
          }
          Spacer()
          Label(
            model.activeComputeMode == .hyak
              ? "完成后自动取回，不需要重新上传"
              : "本机完成后自动打开结果",
            systemImage: "arrow.down.to.line.compact"
          )
          .font(.callout)
          .foregroundStyle(theme.mutedText)
        }

        Spacer()

        HStack(spacing: 20) {
          Label(connectionLabel, systemImage: connectionIcon)
          Divider()
            .frame(height: 16)
          Text(
            "\(model.activeComputeMode == .hyak ? "Job" : "Task") \(model.betaJobID ?? "—")"
          )
          .monospaced()
          Divider()
            .frame(height: 16)
          Text(stageDescription)
            .lineLimit(1)
          Spacer()
          Label("结果尚未就绪", systemImage: "square.and.arrow.down")
            .foregroundStyle(theme.quietText)
        }
        .font(.caption)
        .foregroundStyle(theme.mutedText)
        .padding(.horizontal, 14)
        .frame(height: 42)
        .background(theme.raisedSurface)
        .overlay {
          RoundedRectangle(cornerRadius: 8, style: .continuous)
            .stroke(theme.border, lineWidth: 1)
        }
      }
      .frame(maxWidth: 980, alignment: .leading)
      .padding(42)
    }
    .confirmationDialog(
      "停止本机计算？",
      isPresented: $isConfirmingLocalStop,
      titleVisibility: .visible
    ) {
      Button("停止任务", role: .destructive) {
        model.cancelLocalCompute()
      }
      Button("继续运行", role: .cancel) {}
    } message: {
      Text("未完成的项目和日志会保留；模型进程将停止。")
    }
  }

  private var projectTitle: String {
    model.catalog?.manifest.title
      ?? model.betaProjectURL?.lastPathComponent
      ?? "正在识别的新歌曲"
  }

  private var currentPhase: Int {
    switch model.betaPipelineStage {
    case "full_transcription": 1
    case "rhythm_analysis": 2
    case "gap_planning": 3
    case "automatic_gap_recovery": 4
    case "packaging", "complete": 5
    default:
      ["RUNNING", "COMPLETING"].contains(model.betaSlurmState ?? "") ? 1 : 0
    }
  }

  private var stageDescription: String {
    switch model.betaPipelineStage {
    case "full_transcription": "正在识别完整多轨"
    case "rhythm_analysis": "正在估算 BPM、拍号与每拍位置"
    case "gap_planning": "正在检查主旋律覆盖"
    case "automatic_gap_recovery": "正在定向补回主旋律长缺口"
    case "packaging": "识别完成，正在校验并打包结果"
    case "complete": "结果已经完成"
    default:
      model.betaSlurmState == "PENDING"
        ? (model.activeComputeMode == .hyak
          ? "GPU 作业已排队，等待资源"
          : "本机后台任务正在启动")
        : (model.activeComputeMode == .hyak
          ? "正在准备远端任务"
          : "正在准备本机任务")
    }
  }

  private var connectionLabel: String {
    if model.activeComputeMode != .hyak {
      return model.activeComputeMode?.label ?? "本机计算"
    }
    return switch model.hyakConnectionState {
    case .connected: "Hyak 已连接"
    case .checking: "正在检查连接"
    case .loginRequired: "需要重新登录"
    case .unknown: "连接尚未检查"
    }
  }

  private var connectionIcon: String {
    if model.activeComputeMode != .hyak {
      return model.activeComputeMode?.icon ?? "desktopcomputer"
    }
    return switch model.hyakConnectionState {
    case .connected: "network.badge.shield.half.filled"
    case .checking: "arrow.triangle.2.circlepath"
    case .loginRequired: "network.slash"
    case .unknown: "network"
    }
  }

  private func phaseFill(_ index: Int) -> Color {
    if index < currentPhase {
      return theme.accent.opacity(0.18)
    }
    if index == currentPhase {
      return theme.active.opacity(0.22)
    }
    return theme.raisedSurface
  }

  private func phaseBorder(_ index: Int) -> Color {
    index == currentPhase
      ? theme.active
      : index < currentPhase
        ? theme.accent.opacity(0.8)
        : theme.border
  }

  private func phaseForeground(_ index: Int) -> Color {
    index == currentPhase
      ? theme.active
      : index < currentPhase
        ? theme.accent
        : theme.quietText
  }
}

private struct LibraryHomeView: View {
  let projects: [LocalProjectItem]
  let isBusy: Bool
  let computeMode: ComputeMode
  let theme: AMTTheme
  let onTranscribe: () -> Void
  let onOpenProject: () -> Void
  let onSelectProject: (URL) -> Void

  var body: some View {
    ScrollView {
      VStack(alignment: .leading, spacing: 26) {
        VStack(alignment: .leading, spacing: 8) {
          Text("SIGNAL TO SCORE")
            .font(.system(size: 11, weight: .bold, design: .monospaced))
            .tracking(1.6)
            .foregroundStyle(theme.accent)
          Label("AMT Studio", systemImage: "waveform.path")
            .font(.system(size: 34, weight: .bold, design: .rounded))
          Text(
            "把一首歌变成可以试听、分轨和编辑的 MIDI。下一首歌将使用\(computeMode.label)；默认仍是 Hyak GPU。"
          )
          .font(.title3)
          .foregroundStyle(theme.mutedText)
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
                  .background(theme.surface)
                  .overlay {
                    RoundedRectangle(cornerRadius: 10, style: .continuous)
                      .stroke(theme.border, lineWidth: 1)
                  }
                  .clipShape(RoundedRectangle(cornerRadius: 10))
                }
                .buttonStyle(.plain)
              }
            }
          }
        }

        Label(
          computeMode == .hyak
            ? "已经提交的 Hyak 作业在关闭窗口或 SSH 登录过期后仍会继续；重新连接只恢复查询，不会重复提交。"
            : "本机任务会在独立后台进程中继续；开始前请保存其他工作，必要时可以在任务页停止。",
          systemImage: "checkmark.shield"
        )
        .font(.callout)
        .foregroundStyle(theme.mutedText)
      }
      .frame(maxWidth: 920, alignment: .leading)
      .padding(44)
      .frame(maxWidth: .infinity, alignment: .top)
    }
    .background(theme.canvasGradient)
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
  let theme: AMTTheme
  @State private var pianoRollDisplayMode: PianoRollDisplayMode = .allTracks

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
          timelineDuration: timelineDuration,
          theme: theme
        )
        .frame(height: 90)
        Divider()
        PianoRollModeBar(
          mode: $pianoRollDisplayMode,
          trackCount: overviewTracks.count,
          selectedTrackLabel: editor.selectedTrack.label,
          isLoadingSelection: model.isLoadingSelection,
          theme: theme,
          onAddNote: model.createNoteAtPlayhead
        )
        Divider()
        if pianoRollDisplayMode == .allTracks {
          AllTracksPianoRollView(
            tracks: overviewTracks,
            notesByTrack: overviewNotesByTrack,
            selectedTrackID: editor.selectedTrack.id,
            transport: transport,
            duration: timelineDuration,
            theme: theme,
            onSelectTrack: model.chooseTrack
          )
        } else {
          PianoRollView(
            notes: editor.notes,
            transport: transport,
            duration: timelineDuration,
            selectedNoteID: $model.selectedNoteID,
            onCommit: model.commit,
            rhythm: editor.snapshot.canonicalProject.rhythm,
            theme: theme
          )
        }
      }
      .frame(minWidth: 760)
      .background(theme.canvas)

      inspector
        .frame(minWidth: 260, idealWidth: 300, maxWidth: 360)
        .background(theme.surface)
    }
    .background(theme.canvas)
  }

  private var timelineDuration: Double {
    max(
      transport.duration,
      editor.snapshot.notes.map(\.offsetSec).max() ?? 1,
      1
    )
  }

  private var overviewTracks: [EditorTrack] {
    model.visibleTrackChoices
  }

  private var overviewNotesByTrack: [String: [EditorNote]] {
    var notesByTrack = Dictionary(
      grouping: model.snapshot?.notes ?? [],
      by: \.trackID
    )
    notesByTrack[editor.selectedTrack.id] = editor.notes
    return notesByTrack
  }

  @ViewBuilder
  private var inspector: some View {
    VStack(spacing: 0) {
      ResultReviewPanel(model: model)
      Divider()
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
        VStack(spacing: 14) {
          EmptyStateView(
            icon: "cursorarrow.click",
            title: "选择或新增音符",
            message: "拖动音符可同时改变时间与音高；拖左右把手可调整长度。"
          )
          Button("在播放头新增音符", systemImage: "plus.rectangle.on.rectangle") {
            model.createNoteAtPlayhead()
          }
          .buttonStyle(.borderedProminent)
          .keyboardShortcut("n", modifiers: [.command, .shift])
          .accessibilityIdentifier("add-note-empty-inspector")
        }
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
      if let position = model.currentMusicalPosition {
        HStack(spacing: 10) {
          Label(
            position.displayLabel,
            systemImage: "music.note"
          )
          .font(.caption.monospacedDigit())
          Text(model.currentMeterLabel)
            .font(.caption.monospacedDigit().weight(.semibold))
          Text(
            model.representativeBPM.map {
              "\($0.formatted(.number.precision(.fractionLength(1)))) BPM"
            } ?? "BPM —"
          )
          .font(.caption.monospacedDigit())
          Text(model.rhythmSourceLabel)
            .font(.caption2)
            .foregroundStyle(.secondary)
          Spacer()
        }
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
  let theme: AMTTheme

  var body: some View {
    AudioWaveformView(
      samples: transport.waveformSamples,
      isLoading: transport.waveformLoading,
      errorMessage: transport.waveformErrorMessage,
      currentTime: transport.currentTime,
      audioDuration: transport.duration,
      timelineDuration: timelineDuration,
      tintColor: theme.accent
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
  let tintColor: Color

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
          context.fill(path, with: .color(tintColor.opacity(0.50)))
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

private struct ResultReviewPanel: View {
  @ObservedObject var model: AppModel

  var body: some View {
    VStack(alignment: .leading, spacing: 8) {
      HStack {
        Label("整曲验收", systemImage: "checklist")
          .font(.headline)
        Spacer()
        Text("\(model.snapshot?.tracks.count ?? 0) 轨")
          .font(.caption.monospacedDigit())
          .foregroundStyle(.secondary)
      }
      Text(model.projectReviewSummary)
        .font(.caption)
        .foregroundStyle(.secondary)
      Button("定位下一项", systemImage: "scope") {
        model.seekToNextProjectReviewIssue()
      }
      .buttonStyle(.bordered)
      .disabled(model.projectReviewIssues.isEmpty)
      .accessibilityIdentifier("review-next-project-issue")
      Text("这里只提示低置信度和异常短音；它们是复核线索，不会被自动删除。")
        .font(.caption2)
        .foregroundStyle(.secondary)
    }
    .padding(12)
  }
}

private enum PianoRollDisplayMode: String, CaseIterable, Identifiable {
  case allTracks
  case currentTrack

  var id: String { rawValue }

  var label: String {
    switch self {
    case .allTracks: "全部音轨"
    case .currentTrack: "当前音轨"
    }
  }
}

private struct PianoRollModeBar: View {
  @Binding var mode: PianoRollDisplayMode
  let trackCount: Int
  let selectedTrackLabel: String
  let isLoadingSelection: Bool
  let theme: AMTTheme
  let onAddNote: () -> Void

  var body: some View {
    HStack(spacing: 12) {
      Picker("卷帘视图", selection: $mode) {
        ForEach(PianoRollDisplayMode.allCases) { option in
          Text(option.label).tag(option)
        }
      }
      .labelsHidden()
      .pickerStyle(.segmented)
      .frame(width: 230)
      .accessibilityIdentifier("piano-roll-display-mode")

      if mode == .allTracks {
        Text("\(trackCount) 条产品音轨按行显示；点一行即可选中")
          .font(.caption)
          .foregroundStyle(theme.mutedText)
      } else {
        Text("当前正在精细编辑：\(selectedTrackLabel)")
          .font(.caption)
          .foregroundStyle(theme.mutedText)
          .lineLimit(1)
      }

      Spacer()

      if isLoadingSelection {
        ProgressView("正在切换音轨…")
          .controlSize(.small)
          .font(.caption)
      }

      if mode == .currentTrack {
        Button("新增音符", systemImage: "plus") {
          onAddNote()
        }
        .buttonStyle(.borderedProminent)
        .keyboardShortcut("n", modifiers: [.command, .shift])
        .accessibilityIdentifier("add-note-at-playhead")
      }

      Button(
        mode == .allTracks ? "编辑所选音轨" : "返回全部音轨",
        systemImage: mode == .allTracks ? "pencil.and.outline" : "rectangle.grid.1x2"
      ) {
        mode = mode == .allTracks ? .currentTrack : .allTracks
      }
      .buttonStyle(.bordered)
      .disabled(isLoadingSelection)
      .accessibilityIdentifier("toggle-piano-roll-detail")
    }
    .padding(.horizontal, 12)
    .frame(height: 44)
    .background(theme.raisedSurface)
  }
}

private struct AllTracksPianoRollView: View {
  let tracks: [EditorTrack]
  let notesByTrack: [String: [EditorNote]]
  let selectedTrackID: String
  let transport: AudioTransport
  let duration: Double
  let theme: AMTTheme
  let onSelectTrack: (String) -> Void

  private let labelWidth = 210.0

  var body: some View {
    GeometryReader { proxy in
      let timelineWidth = max(360, proxy.size.width - labelWidth - 24)
      VStack(spacing: 0) {
        HStack(spacing: 0) {
          Text("音轨")
            .font(.caption.weight(.semibold))
            .foregroundStyle(theme.mutedText)
            .frame(width: labelWidth, alignment: .leading)
            .padding(.leading, 12)
          MultiTrackTimeRuler(
            duration: duration,
            theme: theme
          )
          .frame(width: timelineWidth, height: 30)
        }
        .frame(height: 30)
        .background(theme.surface)

        ScrollView(.vertical) {
          LazyVStack(spacing: 7) {
            ForEach(Array(tracks.enumerated()), id: \.element.id) {
              index, track in
              TrackOverviewRow(
                track: track,
                notes: notesByTrack[track.id] ?? [],
                isSelected: track.id == selectedTrackID,
                transport: transport,
                duration: duration,
                labelWidth: labelWidth,
                timelineWidth: timelineWidth,
                color: trackColor(track, index: index),
                theme: theme,
                onSelect: { onSelectTrack(track.id) }
              )
            }
          }
          .padding(.vertical, 8)
          .padding(.trailing, 8)
        }
      }
    }
    .background(theme.canvas)
    .accessibilityElement(children: .contain)
    .accessibilityLabel("全部音轨卷帘")
    .accessibilityValue("\(tracks.count) 条音轨")
    .accessibilityIdentifier("piano-roll")
  }

  private func trackColor(_ track: EditorTrack, index: Int) -> Color {
    let instrument = track.instrument?.lowercased() ?? ""
    if instrument == "voice" || track.id.contains("voice") {
      return theme.active
    }
    if instrument.contains("drum") {
      return .orange
    }
    let palette: [Color] =
      theme.mode == .precision
      ? [theme.accent, .mint, .cyan, .green, .yellow]
      : [theme.accent, theme.active, .cyan, .purple, .pink]
    return palette[index % palette.count]
  }
}

private struct MultiTrackTimeRuler: View {
  let duration: Double
  let theme: AMTTheme

  var body: some View {
    GeometryReader { proxy in
      ZStack {
        ForEach(0..<5, id: \.self) { index in
          let fraction = Double(index) / 4
          let x = min(
            proxy.size.width - 24,
            max(24, proxy.size.width * fraction)
          )
          VStack(spacing: 2) {
            Text(formatTime(duration * fraction))
              .font(.caption2.monospacedDigit())
              .foregroundStyle(theme.mutedText)
            Rectangle()
              .fill(theme.border)
              .frame(width: 1, height: 6)
          }
          .position(x: x, y: 15)
        }
      }
    }
  }
}

private struct TrackOverviewRow: View {
  let track: EditorTrack
  let notes: [EditorNote]
  let isSelected: Bool
  let transport: AudioTransport
  let duration: Double
  let labelWidth: Double
  let timelineWidth: Double
  let color: Color
  let theme: AMTTheme
  let onSelect: () -> Void

  var body: some View {
    Button(action: onSelect) {
      HStack(spacing: 0) {
        HStack(spacing: 10) {
          ZStack {
            RoundedRectangle(cornerRadius: 7, style: .continuous)
              .fill(color.opacity(isSelected ? 0.24 : 0.12))
            Image(systemName: trackIcon)
              .font(.system(size: 15, weight: .semibold))
              .foregroundStyle(color)
          }
          .frame(width: 34, height: 34)

          VStack(alignment: .leading, spacing: 3) {
            Text(MelodyTrackSelector.displayLabel(for: track))
              .font(.callout.weight(isSelected ? .semibold : .regular))
              .lineLimit(1)
            Text("\(track.instrument ?? "未知乐器") · \(notes.count) 音符")
              .font(.caption2.monospacedDigit())
              .foregroundStyle(theme.mutedText)
              .lineLimit(1)
          }
          Spacer(minLength: 6)
          if isSelected {
            Image(systemName: "checkmark.circle.fill")
              .foregroundStyle(color)
          }
        }
        .padding(.horizontal, 10)
        .frame(width: labelWidth, height: 66)

        TrackNoteLane(
          notes: notes,
          transport: transport,
          duration: duration,
          color: color,
          theme: theme
        )
        .frame(width: timelineWidth, height: 66)
      }
      .background(
        isSelected
          ? color.opacity(0.075)
          : theme.surface.opacity(0.72)
      )
      .overlay {
        RoundedRectangle(cornerRadius: 8, style: .continuous)
          .stroke(
            isSelected ? color.opacity(0.82) : theme.border,
            lineWidth: isSelected ? 1.5 : 1
          )
      }
      .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
      .contentShape(Rectangle())
    }
    .buttonStyle(.plain)
    .accessibilityLabel(
      "\(MelodyTrackSelector.displayLabel(for: track))，\(notes.count) 个音符"
    )
    .accessibilityValue(isSelected ? "已选择" : "未选择")
    .accessibilityHint("点按选择这条音轨，然后可进入当前音轨精细编辑")
    .accessibilityIdentifier("overview-track-\(track.id)")
  }

  private var trackIcon: String {
    let instrument = track.instrument?.lowercased() ?? ""
    if instrument == "voice" || track.id.contains("voice") {
      return "music.microphone"
    }
    if instrument.contains("drum") {
      return "drum"
    }
    if instrument.contains("piano") || instrument.contains("keyboard") {
      return "pianokeys"
    }
    if instrument.contains("guitar") || instrument.contains("bass") {
      return "guitars"
    }
    if instrument.contains("flute") || instrument.contains("sax") {
      return "music.note"
    }
    return "waveform.path"
  }
}

private struct TrackNoteLane: View {
  let notes: [EditorNote]
  let transport: AudioTransport
  let duration: Double
  let color: Color
  let theme: AMTTheme

  var body: some View {
    GeometryReader { proxy in
      let pitchBounds = MultiTrackRollLayout.pitchBounds(notes)
      Canvas { context, size in
        for index in 0...4 {
          let x = size.width * Double(index) / 4
          context.stroke(
            Path(CGRect(x: x, y: 0, width: 0.5, height: size.height)),
            with: .color(theme.border),
            lineWidth: 0.5
          )
        }
        for note in notes {
          let frame = MultiTrackRollLayout.noteFrame(
            onset: note.onsetSec,
            offset: note.offsetSec,
            pitch: note.pitchMIDI,
            duration: duration,
            size: size,
            minimumPitch: pitchBounds.lowerBound,
            maximumPitch: pitchBounds.upperBound
          )
          let noteColor: Color
          if let confidence = note.confidence, confidence < 0.5 {
            noteColor = .orange
          } else {
            noteColor = color
          }
          context.fill(
            Path(roundedRect: frame, cornerRadius: 1.5),
            with: .color(noteColor.opacity(0.90))
          )
        }
      }
      .allowsHitTesting(false)

      MultiTrackPlayhead(
        transport: transport,
        duration: duration
      )
      .allowsHitTesting(false)
    }
  }
}

private struct MultiTrackPlayhead: View {
  @ObservedObject var transport: AudioTransport
  let duration: Double

  var body: some View {
    GeometryReader { proxy in
      Rectangle()
        .fill(.red.opacity(0.82))
        .frame(width: 1, height: proxy.size.height)
        .position(
          x: MultiTrackRollLayout.normalizedTime(
            transport.currentTime,
            duration: duration
          ) * proxy.size.width,
          y: proxy.size.height / 2
        )
    }
  }
}

enum MultiTrackRollLayout {
  static func normalizedTime(_ time: Double, duration: Double) -> Double {
    guard time.isFinite, duration.isFinite, duration > 0 else { return 0 }
    return min(1, max(0, time / duration))
  }

  static func normalizedPitch(
    _ pitch: Double,
    minimumPitch: Double,
    maximumPitch: Double
  ) -> Double {
    guard pitch.isFinite, minimumPitch.isFinite, maximumPitch.isFinite,
      maximumPitch > minimumPitch
    else {
      return 0.5
    }
    return min(
      1,
      max(0, (maximumPitch - pitch) / (maximumPitch - minimumPitch))
    )
  }

  static func pitchBounds(_ notes: [EditorNote]) -> ClosedRange<Double> {
    let pitches = notes.map(\.pitchMIDI).filter(\.isFinite)
    guard let minimumPitch = pitches.min(), let maximumPitch = pitches.max()
    else {
      return 48...84
    }
    if maximumPitch - minimumPitch < 1 {
      return (minimumPitch - 1)...(maximumPitch + 1)
    }
    return minimumPitch...maximumPitch
  }

  static func noteFrame(
    onset: Double,
    offset: Double,
    pitch: Double,
    duration: Double,
    size: CGSize,
    minimumPitch: Double,
    maximumPitch: Double
  ) -> CGRect {
    let start = normalizedTime(onset, duration: duration)
    let end = normalizedTime(max(onset, offset), duration: duration)
    let x = start * max(0, size.width)
    let proposedWidth = (end - start) * max(0, size.width)
    let width = min(max(1.5, proposedWidth), max(1.5, size.width - x))
    let usableHeight = max(1, size.height - 12)
    let y =
      4
      + normalizedPitch(
        pitch,
        minimumPitch: minimumPitch,
        maximumPitch: maximumPitch
      ) * usableHeight
    return CGRect(x: x, y: y, width: width, height: 4)
  }
}

private struct PianoRollView: View {
  let notes: [EditorNote]
  let transport: AudioTransport
  let duration: Double
  @Binding var selectedNoteID: String?
  let onCommit: (EditorNote) -> Void
  let rhythm: RhythmMap
  let theme: AMTTheme

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
          rhythm: rhythm,
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
              onCommit: onCommit,
              theme: theme
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
  let theme: AMTTheme

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
          onCommit: onCommit,
          theme: theme
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
  let rhythm: RhythmMap
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
      let beatMarkers = RhythmTimeline.markers(
        duration: duration,
        rhythm: rhythm
      )
      for marker in beatMarkers {
        let x = marker.timeSec * pointsPerSecond
        context.stroke(
          Path(CGRect(x: x, y: 0, width: 0.5, height: size.height)),
          with: .color(
            marker.isDownbeat
              ? Color.accentColor.opacity(0.50)
              : Color.secondary.opacity(0.16)
          ),
          lineWidth: marker.isDownbeat ? 1 : 0.5
        )
        if marker.isDownbeat {
          context.draw(
            Text("第\(marker.bar)小节")
              .font(.caption2)
              .foregroundColor(.accentColor),
            at: CGPoint(x: x + 3, y: 8),
            anchor: .leading
          )
        }
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
          at: CGPoint(x: x + 3, y: 22),
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
  let theme: AMTTheme

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
    .shadow(color: selected ? theme.accent.opacity(0.72) : .clear, radius: 3)
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
      return theme.active.opacity(0.86)
    }
    if confidence < 0.5 {
      return .orange.opacity(0.9)
    }
    return theme.accent.opacity(0.88)
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
