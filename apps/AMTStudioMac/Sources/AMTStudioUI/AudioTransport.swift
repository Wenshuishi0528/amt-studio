import AVFoundation
import Foundation

@MainActor
public final class AudioTransport: ObservableObject {
  @Published public private(set) var currentTime = 0.0
  @Published public private(set) var duration = 0.0
  @Published public private(set) var isPlaying = false
  @Published public private(set) var audioURL: URL?
  @Published public private(set) var midiAvailable = false
  @Published public private(set) var midiLoading = false
  @Published public private(set) var originalEnabled = true
  @Published public private(set) var midiEnabled = true
  @Published public private(set) var originalVolume = 0.35
  @Published public private(set) var audioErrorMessage: String?
  @Published public private(set) var midiErrorMessage: String?
  @Published public private(set) var waveformSamples: [Float] = []
  @Published public private(set) var waveformLoading = false
  @Published public private(set) var waveformErrorMessage: String?

  private var audioPlayer: AVAudioPlayer?
  private var midiPlayer: AVMIDIPlayer?
  private var timer: Timer?
  private var waveformTask: Task<Void, Never>?
  private var waveformGeneration = UUID()

  public init() {}

  public var errorMessages: [String] {
    [audioErrorMessage, midiErrorMessage, waveformErrorMessage].compactMap {
      $0
    }
  }

  public func load(audioURL: URL) {
    if self.audioURL?.standardizedFileURL == audioURL.standardizedFileURL,
      audioPlayer != nil
    {
      return
    }
    stop()
    do {
      let player = try AVAudioPlayer(contentsOf: audioURL)
      player.volume = Float(originalVolume)
      player.prepareToPlay()
      audioPlayer = player
      self.audioURL = audioURL
      duration = player.duration
      audioErrorMessage = nil
      loadWaveform(audioURL: audioURL)
    } catch {
      audioErrorMessage = "原曲无法加载：\(error.localizedDescription)"
    }
  }

  public func loadMIDI(url: URL) {
    let position = currentTime
    let wasPlaying = isPlaying
    midiPlayer?.stop()
    do {
      let player = try AVMIDIPlayer(contentsOf: url, soundBankURL: nil)
      player.prepareToPlay()
      player.currentPosition = min(position, player.duration)
      midiPlayer = player
      midiAvailable = true
      midiLoading = false
      midiErrorMessage = nil
      if wasPlaying, midiEnabled {
        player.play {}
      }
    } catch {
      clearMIDI(
        message: "MIDI 预览暂不可用：\(error.localizedDescription)"
      )
    }
  }

  public func clearMIDI(message: String? = nil) {
    midiPlayer?.stop()
    midiPlayer = nil
    midiAvailable = false
    midiLoading = false
    midiErrorMessage = message
  }

  public func beginMIDILoading() {
    midiLoading = true
    midiErrorMessage = nil
  }

  public func setOriginalEnabled(_ enabled: Bool) {
    guard originalEnabled != enabled else { return }
    originalEnabled = enabled
    reconcileEnabledPlayers()
  }

  public func setOriginalVolume(_ value: Double) {
    let bounded = min(1, max(0, value))
    originalVolume = bounded
    audioPlayer?.volume = Float(bounded)
  }

  public func setMIDIEnabled(_ enabled: Bool) {
    guard midiEnabled != enabled else { return }
    midiEnabled = enabled
    reconcileEnabledPlayers()
  }

  public func togglePlayback() {
    isPlaying ? pause() : play()
  }

  public func play() {
    guard
      (originalEnabled && audioPlayer != nil)
        || (midiEnabled && midiPlayer != nil)
    else {
      return
    }
    if originalEnabled {
      audioPlayer?.currentTime = currentTime
      audioPlayer?.play()
    }
    if midiEnabled {
      midiPlayer?.currentPosition = currentTime
      midiPlayer?.play {}
    }
    isPlaying = true
    startTimer()
  }

  public func pause() {
    audioPlayer?.pause()
    midiPlayer?.stop()
    isPlaying = false
    timer?.invalidate()
    timer = nil
  }

  public func stop() {
    pause()
    waveformTask?.cancel()
    waveformTask = nil
    waveformGeneration = UUID()
    audioPlayer?.stop()
    midiPlayer?.stop()
    audioPlayer = nil
    midiPlayer = nil
    audioURL = nil
    midiAvailable = false
    midiLoading = false
    currentTime = 0
    duration = 0
    audioErrorMessage = nil
    midiErrorMessage = nil
    waveformSamples = []
    waveformLoading = false
    waveformErrorMessage = nil
  }

  public func seek(to value: Double) {
    let bounded = min(max(0, value), duration)
    currentTime = bounded
    audioPlayer?.currentTime = bounded
    midiPlayer?.currentPosition = bounded
    if isPlaying {
      if originalEnabled {
        audioPlayer?.play()
      }
      if midiEnabled {
        midiPlayer?.play {}
      }
    }
  }

  private func startTimer() {
    timer?.invalidate()
    timer = Timer.scheduledTimer(withTimeInterval: 1.0 / 20.0, repeats: true) {
      [weak self] _ in
      MainActor.assumeIsolated {
        guard let self else { return }
        if self.originalEnabled, let audioPlayer = self.audioPlayer {
          self.currentTime = audioPlayer.currentTime
          if !audioPlayer.isPlaying {
            self.pause()
          }
        } else if self.midiEnabled, let midiPlayer = self.midiPlayer {
          self.currentTime = midiPlayer.currentPosition
          if !midiPlayer.isPlaying {
            self.pause()
          }
        }
      }
    }
  }

  private func loadWaveform(audioURL: URL) {
    waveformTask?.cancel()
    waveformSamples = []
    waveformLoading = true
    waveformErrorMessage = nil
    let generation = UUID()
    waveformGeneration = generation
    waveformTask = Task { [weak self] in
      do {
        let samples = try await AudioWaveformLoader.load(url: audioURL)
        guard let self, self.waveformGeneration == generation else {
          return
        }
        self.waveformSamples = samples
        self.waveformLoading = false
      } catch is CancellationError {
        return
      } catch {
        guard let self, self.waveformGeneration == generation else {
          return
        }
        self.waveformLoading = false
        self.waveformErrorMessage =
          "原曲波形无法生成：\(error.localizedDescription)"
      }
    }
  }

  private func reconcileEnabledPlayers() {
    guard isPlaying else { return }
    if originalEnabled, let audioPlayer {
      audioPlayer.currentTime = currentTime
      audioPlayer.play()
    } else {
      audioPlayer?.pause()
    }
    if midiEnabled, let midiPlayer {
      midiPlayer.currentPosition = currentTime
      midiPlayer.play {}
    } else {
      midiPlayer?.stop()
    }
    if (!originalEnabled || audioPlayer == nil)
      && (!midiEnabled || midiPlayer == nil)
    {
      pause()
    }
  }
}
