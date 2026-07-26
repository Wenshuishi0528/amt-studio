import AVFoundation
import Foundation

enum AudioWaveformLoader {
  static let defaultBinCount = 2_048

  static func load(
    url: URL,
    binCount: Int = defaultBinCount
  ) async throws -> [Float] {
    let loaderTask = Task.detached(priority: .utility) {
      try loadSynchronously(url: url, binCount: binCount)
    }
    return try await withTaskCancellationHandler {
      try await loaderTask.value
    } onCancel: {
      loaderTask.cancel()
    }
  }

  static func loadSynchronously(
    url: URL,
    binCount: Int
  ) throws -> [Float] {
    precondition(binCount > 0)
    let file = try AVAudioFile(forReading: url)
    let frameCount = file.length
    guard frameCount > 0 else {
      return Array(repeating: 0, count: binCount)
    }

    let format = file.processingFormat
    guard format.commonFormat == .pcmFormatFloat32,
      !format.isInterleaved,
      format.channelCount > 0
    else {
      throw NSError(
        domain: "AMTStudio.AudioWaveform",
        code: 1,
        userInfo: [
          NSLocalizedDescriptionKey: "音频无法转换为波形所需的 PCM 数据"
        ]
      )
    }

    let chunkCapacity = AVAudioFrameCount(
      min(Int64(65_536), frameCount)
    )
    guard
      let buffer = AVAudioPCMBuffer(
        pcmFormat: format,
        frameCapacity: chunkCapacity
      )
    else {
      throw NSError(
        domain: "AMTStudio.AudioWaveform",
        code: 2,
        userInfo: [
          NSLocalizedDescriptionKey: "无法分配音频波形缓冲区"
        ]
      )
    }

    var peaks = Array(repeating: Float.zero, count: binCount)
    var processedFrames: AVAudioFramePosition = 0
    while processedFrames < frameCount {
      if Task.isCancelled {
        throw CancellationError()
      }
      let remaining = frameCount - processedFrames
      let requested = AVAudioFrameCount(
        min(Int64(chunkCapacity), remaining)
      )
      try file.read(into: buffer, frameCount: requested)
      let framesRead = Int(buffer.frameLength)
      guard framesRead > 0, let channels = buffer.floatChannelData else {
        break
      }

      for frameIndex in 0..<framesRead {
        var amplitude = Float.zero
        for channelIndex in 0..<Int(format.channelCount) {
          amplitude = max(
            amplitude,
            abs(channels[channelIndex][frameIndex])
          )
        }
        let absoluteFrame = processedFrames + AVAudioFramePosition(frameIndex)
        let binIndex = min(
          binCount - 1,
          Int(absoluteFrame * AVAudioFramePosition(binCount) / frameCount)
        )
        peaks[binIndex] = max(peaks[binIndex], amplitude)
      }
      processedFrames += AVAudioFramePosition(framesRead)
    }

    guard let maximum = peaks.max(), maximum > 0 else {
      return peaks
    }
    return peaks.map { sqrt(min(1, $0 / maximum)) }
  }
}
