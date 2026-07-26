import AVFoundation
import Foundation

@MainActor
public final class AudioTransport: ObservableObject {
  @Published public private(set) var currentTime = 0.0
  @Published public private(set) var duration = 0.0
  @Published public private(set) var isPlaying = false
  @Published public private(set) var audioURL: URL?
  @Published public private(set) var midiAvailable = false
  @Published public private(set) var originalEnabled = true
  @Published public private(set) var midiEnabled = true
  @Published public private(set) var audioErrorMessage: String?
  @Published public private(set) var midiErrorMessage: String?

  private var audioPlayer: AVAudioPlayer?
  private var midiPlayer: AVMIDIPlayer?
  private var timer: Timer?

  public init() {}

  public var errorMessages: [String] {
    [audioErrorMessage, midiErrorMessage].compactMap { $0 }
  }

  public func load(audioURL: URL) {
    stop()
    do {
      let player = try AVAudioPlayer(contentsOf: audioURL)
      player.prepareToPlay()
      audioPlayer = player
      self.audioURL = audioURL
      duration = player.duration
      audioErrorMessage = nil
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
      midiErrorMessage = nil
      if wasPlaying, midiEnabled {
        player.play {}
      }
    } catch {
      clearMIDI(
        message: "钢琴预览暂不可用：\(error.localizedDescription)"
      )
    }
  }

  public func clearMIDI(message: String? = nil) {
    midiPlayer?.stop()
    midiPlayer = nil
    midiAvailable = false
    midiErrorMessage = message
  }

  public func setOriginalEnabled(_ enabled: Bool) {
    guard originalEnabled != enabled else { return }
    originalEnabled = enabled
    reconcileEnabledPlayers()
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
    audioPlayer?.stop()
    midiPlayer?.stop()
    audioPlayer = nil
    midiPlayer = nil
    midiAvailable = false
    currentTime = 0
    duration = 0
    audioErrorMessage = nil
    midiErrorMessage = nil
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
    timer = Timer.scheduledTimer(withTimeInterval: 1.0 / 30.0, repeats: true) {
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
