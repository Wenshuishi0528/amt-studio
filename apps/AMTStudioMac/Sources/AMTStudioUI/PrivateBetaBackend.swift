import Foundation

struct PrivateBetaResponse: Decodable, Sendable {
  let ok: Bool
  let error: String?
  let needsHyakLogin: Bool?
  let status: String?
  let projectID: String?
  let localProjectDir: String?
  let jobID: String?
  let runID: String?
  let bundleID: String?
  let slurmState: String?
  let pipelineStage: String?
  let backend: String?
  let localDevice: String?
  let ready: Bool?
  let readinessMessage: String?
  let host: String?
  let user: String?
  let controlPath: String?
  let taskKind: String?
  let sourceBundleID: String?
  let sourceTrackID: String?
  let selectedGapCount: Int?
  let slurmGPUType: String?
  let slurmPartition: String?
  let gpuPreemptible: Bool?
  let gpuSelectionReason: String?
  let gpuEstimatedWaitSeconds: Int?

  enum CodingKeys: String, CodingKey {
    case ok
    case error
    case needsHyakLogin = "needs_hyak_login"
    case status
    case projectID = "project_id"
    case localProjectDir = "local_project_dir"
    case jobID = "job_id"
    case runID = "run_id"
    case bundleID = "bundle_id"
    case slurmState = "slurm_state"
    case pipelineStage = "pipeline_stage"
    case backend
    case localDevice = "local_device"
    case ready
    case readinessMessage = "readiness_message"
    case host
    case user
    case controlPath = "control_path"
    case taskKind = "task_kind"
    case sourceBundleID = "source_bundle_id"
    case sourceTrackID = "source_track_id"
    case selectedGapCount = "selected_gap_count"
    case slurmGPUType = "slurm_gpu_type"
    case slurmPartition = "slurm_partition"
    case gpuPreemptible = "gpu_preemptible"
    case gpuSelectionReason = "gpu_selection_reason"
    case gpuEstimatedWaitSeconds = "gpu_estimated_wait_seconds"
  }
}

enum PrivateBetaBackendError: Error, LocalizedError {
  case repositoryNotFound
  case uvNotFound
  case hyakLoginRequired(String)
  case operationFailed(String)
  case invalidResponse(String)

  var errorDescription: String? {
    switch self {
    case .repositoryNotFound:
      "找不到 AMT Studio 源码目录。请从仓库内的 dist 应用启动。"
    case .uvNotFound:
      "找不到 uv。请确认 /opt/homebrew/bin/uv 已安装。"
    case .hyakLoginRequired(let detail):
      detail
    case .operationFailed(let detail):
      detail
    case .invalidResponse(let detail):
      "后台返回无法读取：\(detail)"
    }
  }
}

struct PrivateBetaBackend: Sendable {
  let repositoryRoot: URL
  let uvURL: URL

  static func locate() throws -> PrivateBetaBackend {
    let environment = ProcessInfo.processInfo.environment
    if let override = environment["AMT_STUDIO_REPO_ROOT"] {
      let root = URL(fileURLWithPath: override, isDirectory: true)
      if isRepository(root) {
        return try PrivateBetaBackend(
          repositoryRoot: root,
          uvURL: locateUV(environment: environment)
        )
      }
    }

    var candidates: [URL] = []
    var bundleCandidate = Bundle.main.bundleURL
    for _ in 0..<7 {
      bundleCandidate.deleteLastPathComponent()
      candidates.append(bundleCandidate)
    }
    var workingCandidate = URL(
      fileURLWithPath: FileManager.default.currentDirectoryPath,
      isDirectory: true
    )
    for _ in 0..<6 {
      candidates.append(workingCandidate)
      workingCandidate.deleteLastPathComponent()
    }
    guard let root = candidates.first(where: isRepository) else {
      throw PrivateBetaBackendError.repositoryNotFound
    }
    return try PrivateBetaBackend(
      repositoryRoot: root,
      uvURL: locateUV(environment: environment)
    )
  }

  var localProjectsRoot: URL {
    repositoryRoot.appendingPathComponent(
      "projects/private",
      isDirectory: true
    )
  }

  var loginScriptURL: URL {
    repositoryRoot.appendingPathComponent(
      "scripts/hyak/login_hyak.command"
    )
  }

  func start(
    audioURL: URL,
    computeMode: ComputeMode,
    hyakTimeLimitHours: Int
  ) throws -> PrivateBetaResponse {
    try execute(
      Self.startArguments(
        audioURL: audioURL,
        computeMode: computeMode,
        hyakTimeLimitHours: hyakTimeLimitHours,
        repositoryRoot: repositoryRoot,
        localProjectsRoot: localProjectsRoot
      ))
  }

  func refresh(projectURL: URL) throws -> PrivateBetaResponse {
    try execute([
      "run",
      "amt-private-beta",
      "status",
      projectURL.path,
    ])
  }

  func startGapRecovery(
    projectURL: URL,
    sourceBundleID: String,
    sourceTrackID: String,
    gaps: [MelodyGap],
    computeMode: ComputeMode,
    hyakTimeLimitHours: Int
  ) throws -> PrivateBetaResponse {
    try execute(
      Self.gapRecoveryArguments(
        projectURL: projectURL,
        sourceBundleID: sourceBundleID,
        sourceTrackID: sourceTrackID,
        gaps: gaps,
        computeMode: computeMode,
        hyakTimeLimitHours: hyakTimeLimitHours,
        repositoryRoot: repositoryRoot
      ))
  }

  func connection() throws -> PrivateBetaResponse {
    try execute([
      "run",
      "amt-private-beta",
      "connection",
      "--repo-root",
      repositoryRoot.path,
    ])
  }

  func localReadiness(
    computeMode: ComputeMode
  ) throws -> PrivateBetaResponse {
    guard let device = computeMode.localDevice else {
      throw PrivateBetaBackendError.invalidResponse(
        "Hyak 模式不需要检查本机模型环境"
      )
    }
    return try execute([
      "run",
      "amt-private-beta",
      "local-readiness",
      "--repo-root",
      repositoryRoot.path,
      "--device",
      device,
    ])
  }

  func cancelLocal(projectURL: URL) throws -> PrivateBetaResponse {
    try execute([
      "run",
      "amt-private-beta",
      "cancel-local",
      projectURL.path,
    ])
  }

  static func startArguments(
    audioURL: URL,
    computeMode: ComputeMode,
    hyakTimeLimitHours: Int,
    repositoryRoot: URL,
    localProjectsRoot: URL
  ) -> [String] {
    var arguments = [
      "run",
      "amt-private-beta",
      computeMode == .hyak ? "start" : "start-local",
      audioURL.path,
      "--repo-root",
      repositoryRoot.path,
      "--local-root",
      localProjectsRoot.path,
    ]
    if let device = computeMode.localDevice {
      arguments.append(contentsOf: ["--device", device])
    } else {
      arguments.append(
        contentsOf: ["--time-limit-hours", String(hyakTimeLimitHours)])
    }
    return arguments
  }

  static func gapRecoveryArguments(
    projectURL: URL,
    sourceBundleID: String,
    sourceTrackID: String,
    gaps: [MelodyGap],
    computeMode: ComputeMode,
    hyakTimeLimitHours: Int,
    repositoryRoot: URL
  ) -> [String] {
    var arguments = [
      "run",
      "amt-private-beta",
      computeMode == .hyak
        ? "start-gap-recovery"
        : "start-local-gap-recovery",
      projectURL.path,
      "--repo-root",
      repositoryRoot.path,
      "--source-bundle",
      sourceBundleID,
      "--source-track",
      sourceTrackID,
    ]
    for gap in gaps {
      let start = String(
        format: "%.6f",
        locale: Locale(identifier: "en_US_POSIX"),
        gap.startSec
      )
      let end = String(
        format: "%.6f",
        locale: Locale(identifier: "en_US_POSIX"),
        gap.endSec
      )
      arguments.append(contentsOf: ["--gap", "\(start):\(end)"])
    }
    if let device = computeMode.localDevice {
      arguments.append(contentsOf: ["--device", device])
    } else {
      arguments.append(
        contentsOf: ["--time-limit-hours", String(hyakTimeLimitHours)])
    }
    return arguments
  }

  private func execute(_ arguments: [String]) throws -> PrivateBetaResponse {
    let process = Process()
    let stdout = Pipe()
    let stderr = Pipe()
    process.executableURL = uvURL
    process.arguments = arguments
    process.currentDirectoryURL = repositoryRoot
    process.standardOutput = stdout
    process.standardError = stderr
    try process.run()
    process.waitUntilExit()
    let output = stdout.fileHandleForReading.readDataToEndOfFile()
    let diagnostic = stderr.fileHandleForReading.readDataToEndOfFile()
    do {
      return try JSONDecoder().decode(PrivateBetaResponse.self, from: output)
    } catch {
      let text =
        String(data: diagnostic, encoding: .utf8)
        ?? String(data: output, encoding: .utf8)
        ?? error.localizedDescription
      throw PrivateBetaBackendError.invalidResponse(
        text.trimmingCharacters(in: .whitespacesAndNewlines))
    }
  }

  private static func isRepository(_ url: URL) -> Bool {
    FileManager.default.fileExists(
      atPath: url.appendingPathComponent("pyproject.toml").path
    )
      && FileManager.default.fileExists(
        atPath: url.appendingPathComponent(
          "scripts/hyak/login_hyak.command"
        ).path
      )
  }

  private static func locateUV(
    environment: [String: String]
  ) throws -> URL {
    let candidates = [
      environment["AMT_STUDIO_UV_PATH"],
      "/opt/homebrew/bin/uv",
      "/usr/local/bin/uv",
    ].compactMap { $0 }
    guard
      let path = candidates.first(where: {
        FileManager.default.isExecutableFile(atPath: $0)
      })
    else {
      throw PrivateBetaBackendError.uvNotFound
    }
    return URL(fileURLWithPath: path)
  }
}
