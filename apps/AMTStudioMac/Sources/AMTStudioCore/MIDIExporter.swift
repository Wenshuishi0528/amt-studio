import Foundation

public struct MIDIExportReport: Sendable, Equatable {
  public let noteCount: Int
  public let trackCount: Int
  public let ticksPerBeat: Int

  public init(noteCount: Int, trackCount: Int, ticksPerBeat: Int) {
    self.noteCount = noteCount
    self.trackCount = trackCount
    self.ticksPerBeat = ticksPerBeat
  }
}

public enum MIDIExporter {
  public static func export(
    project: EditorProject,
    to outputURL: URL,
    ticksPerBeat: Int = 960
  ) throws -> MIDIExportReport {
    let notes = try project.materializedNotes()
    guard !notes.isEmpty else {
      throw AMTProjectError.noNotesToExport
    }
    guard ticksPerBeat > 0, ticksPerBeat <= 32_767 else {
      throw AMTProjectError.malformedManifest("MIDI ticksPerBeat 无效")
    }
    let timeline = try TempoTimeline(
      points: project.snapshot.canonicalProject.rhythm.tempoMap,
      ticksPerBeat: ticksPerBeat
    )
    let conductor = try conductorTrack(
      timeline: timeline,
      meters: project.snapshot.canonicalProject.rhythm.meterMap
    )
    let noteTrack = try performanceTrack(
      name: project.selectedTrack.label,
      notes: notes,
      timeline: timeline
    )
    var file = Data("MThd".utf8)
    appendUInt32(6, to: &file)
    appendUInt16(1, to: &file)
    appendUInt16(2, to: &file)
    appendUInt16(UInt16(ticksPerBeat), to: &file)
    file.append(trackChunk(conductor))
    file.append(trackChunk(noteTrack))
    try FileManager.default.createDirectory(
      at: outputURL.deletingLastPathComponent(),
      withIntermediateDirectories: true
    )
    try file.write(to: outputURL, options: [.atomic])
    return MIDIExportReport(
      noteCount: notes.count,
      trackCount: 1,
      ticksPerBeat: ticksPerBeat
    )
  }

  public static func exportArrangement(
    snapshot: ProjectSnapshot,
    bundleID: String,
    to outputURL: URL,
    includedTrackIDs: Set<String>? = nil,
    trackVolumes: [String: Double] = [:],
    ticksPerBeat: Int = 960
  ) throws -> MIDIExportReport {
    guard ticksPerBeat > 0, ticksPerBeat <= 32_767 else {
      throw AMTProjectError.malformedManifest("MIDI ticksPerBeat 无效")
    }
    let timeline = try TempoTimeline(
      points: snapshot.canonicalProject.rhythm.tempoMap,
      ticksPerBeat: ticksPerBeat
    )
    var tracks = [
      try conductorTrack(
        timeline: timeline,
        meters: snapshot.canonicalProject.rhythm.meterMap
      )
    ]
    var noteCount = 0
    var melodicChannels = Array(0...15).filter { $0 != 9 }
    let availableTrackIDs = Set(snapshot.tracks.map(\.id))
    let selectedTrackIDs = includedTrackIDs ?? availableTrackIDs
    guard !selectedTrackIDs.isEmpty,
      selectedTrackIDs.isSubset(of: availableTrackIDs)
    else {
      throw AMTProjectError.malformedManifest(
        "试听音轨为空或包含未知音轨"
      )
    }
    for (trackID, volume) in trackVolumes {
      guard availableTrackIDs.contains(trackID),
        volume.isFinite,
        (0...1).contains(volume)
      else {
        throw AMTProjectError.malformedManifest(
          "音轨音量无效"
        )
      }
    }
    let selectedTracks = snapshot.tracks.filter {
      selectedTrackIDs.contains($0.id)
    }
    for track in selectedTracks {
      let editor = try EditorProject(
        snapshot: snapshot,
        bundleID: bundleID,
        selectedTrackID: track.id
      )
      let notes = try editor.materializedNotes()
      noteCount += notes.count
      let instrument = track.instrument?.lowercased()
      let channel: UInt8
      if instrument == "drums" {
        channel = 9
      } else {
        guard !melodicChannels.isEmpty else {
          throw AMTProjectError.malformedManifest(
            "完整多轨 MIDI 最多支持 15 条旋律轨和 1 条鼓轨"
          )
        }
        channel = UInt8(melodicChannels.removeFirst())
      }
      tracks.append(
        try performanceTrack(
          name: track.label,
          notes: notes,
          timeline: timeline,
          channel: channel,
          program: generalMIDIProgram(instrument),
          volume: trackVolumes[track.id] ?? 1
        )
      )
    }
    guard noteCount > 0 else {
      throw AMTProjectError.noNotesToExport
    }
    var file = Data("MThd".utf8)
    appendUInt32(6, to: &file)
    appendUInt16(1, to: &file)
    appendUInt16(UInt16(tracks.count), to: &file)
    appendUInt16(UInt16(ticksPerBeat), to: &file)
    for track in tracks {
      file.append(trackChunk(track))
    }
    try FileManager.default.createDirectory(
      at: outputURL.deletingLastPathComponent(),
      withIntermediateDirectories: true
    )
    try file.write(to: outputURL, options: [.atomic])
    return MIDIExportReport(
      noteCount: noteCount,
      trackCount: selectedTracks.count,
      ticksPerBeat: ticksPerBeat
    )
  }

  private static func conductorTrack(
    timeline: TempoTimeline,
    meters: [MeterPoint]
  ) throws -> [MIDIEvent] {
    var events = [
      MIDIEvent(
        tick: 0,
        order: 0,
        data: meta(type: 0x03, payload: Data("AMT Studio tempo and meter".utf8))
      )
    ]
    for segment in timeline.segments {
      let rawMicroseconds = (60_000_000 / segment.bpm).rounded()
      guard rawMicroseconds.isFinite,
        rawMicroseconds >= 1,
        rawMicroseconds <= Double(0xFF_FFFF)
      else {
        throw AMTProjectError.malformedManifest("tempo 超出 MIDI 范围")
      }
      let microseconds = Int(rawMicroseconds)
      let payload = Data([
        UInt8((microseconds >> 16) & 0xFF),
        UInt8((microseconds >> 8) & 0xFF),
        UInt8(microseconds & 0xFF),
      ])
      events.append(
        MIDIEvent(
          tick: segment.tick,
          order: 1,
          data: meta(type: 0x51, payload: payload)
        )
      )
    }
    let effectiveMeters =
      meters.isEmpty
      ? [MeterPoint(timeSec: 0, numerator: 4, denominator: 4)]
      : meters
    for point in effectiveMeters.sorted(by: { $0.timeSec < $1.timeSec }) {
      guard point.timeSec.isFinite,
        point.timeSec >= 0,
        (1...32).contains(point.numerator),
        point.denominator > 0,
        point.denominator.nonzeroBitCount == 1
      else {
        throw AMTProjectError.malformedManifest("拍号记录无效")
      }
      let power = UInt8(point.denominator.trailingZeroBitCount)
      events.append(
        MIDIEvent(
          tick: try timeline.tick(at: point.timeSec),
          order: 2,
          data: meta(
            type: 0x58,
            payload: Data([
              UInt8(point.numerator),
              power,
              24,
              8,
            ])
          )
        )
      )
    }
    return events
  }

  private static func performanceTrack(
    name: String,
    notes: [EditorNote],
    timeline: TempoTimeline,
    channel: UInt8 = 0,
    program: UInt8? = nil,
    volume: Double = 1
  ) throws -> [MIDIEvent] {
    guard volume.isFinite, (0...1).contains(volume) else {
      throw AMTProjectError.malformedManifest("音轨音量无效")
    }
    var events = [
      MIDIEvent(
        tick: 0,
        order: 0,
        data: meta(type: 0x03, payload: Data(name.utf8))
      )
    ]
    if channel != 9, let program {
      events.append(
        MIDIEvent(
          tick: 0,
          order: 1,
          data: Data([0xC0 | channel, program])
        )
      )
    }
    events.append(
      MIDIEvent(
        tick: 0,
        order: 2,
        data: Data([
          0xB0 | channel,
          7,
          UInt8((volume * 127).rounded()),
        ])
      )
    )
    for note in notes {
      _ = try note.validated()
      let onset = try timeline.tick(at: note.onsetSec)
      let offset = max(
        onset + 1,
        try timeline.tick(at: note.offsetSec)
      )
      let pitch = UInt8(min(127, max(0, Int(note.pitchMIDI.rounded()))))
      let velocity = UInt8(min(127, max(1, note.velocity ?? 64)))
      events.append(
        MIDIEvent(
          tick: offset,
          order: 1,
          data: Data([0x80 | channel, pitch, 0])
        )
      )
      events.append(
        MIDIEvent(
          tick: onset,
          order: 3,
          data: Data([0x90 | channel, pitch, velocity])
        )
      )
    }
    return events
  }

  private static func generalMIDIProgram(
    _ instrument: String?
  ) -> UInt8? {
    switch instrument?.replacingOccurrences(of: " ", with: "_") {
    case "acoustic_piano": 0
    case "electric_piano": 4
    case "chromatic_percussion": 11
    case "organ": 19
    case "acoustic_guitar": 24
    case "clean_electric_guitar": 27
    case "distorted_electric_guitar": 30
    case "acoustic_bass": 32
    case "electric_bass": 33
    case "violin": 40
    case "viola": 41
    case "cello": 42
    case "contrabass": 43
    case "orchestral_harp": 46
    case "timpani": 47
    case "string_ensemble": 48
    case "synth_strings": 50
    case "voice": 52
    case "orchestra_hit": 55
    case "trumpet": 56
    case "trombone": 57
    case "tuba": 58
    case "french_horn": 60
    case "brass_section": 61
    case "soprano_and_alto_sax", "sax": 64
    case "tenor_sax": 66
    case "baritone_sax": 67
    case "oboe": 68
    case "english_horn": 69
    case "bassoon": 70
    case "clarinet": 71
    case "flutes": 73
    case "synth_lead": 80
    case "synth_pad": 88
    default: nil
    }
  }

  private static func trackChunk(_ events: [MIDIEvent]) -> Data {
    let sorted = events.sorted {
      if $0.tick != $1.tick {
        return $0.tick < $1.tick
      }
      if $0.order != $1.order {
        return $0.order < $1.order
      }
      return $0.data.lexicographicallyPrecedes($1.data)
    }
    var body = Data()
    var previousTick = 0
    for event in sorted {
      body.append(variableLength(event.tick - previousTick))
      body.append(event.data)
      previousTick = event.tick
    }
    body.append(0)
    body.append(contentsOf: [0xFF, 0x2F, 0x00])
    var chunk = Data("MTrk".utf8)
    appendUInt32(UInt32(body.count), to: &chunk)
    chunk.append(body)
    return chunk
  }

  private static func meta(type: UInt8, payload: Data) -> Data {
    var data = Data([0xFF, type])
    data.append(variableLength(payload.count))
    data.append(payload)
    return data
  }

  private static func variableLength(_ value: Int) -> Data {
    precondition(value >= 0)
    var value = value
    var bytes = [UInt8(value & 0x7F)]
    value >>= 7
    while value > 0 {
      bytes.append(UInt8(value & 0x7F) | 0x80)
      value >>= 7
    }
    return Data(bytes.reversed())
  }

  private static func appendUInt16(_ value: UInt16, to data: inout Data) {
    data.append(UInt8((value >> 8) & 0xFF))
    data.append(UInt8(value & 0xFF))
  }

  private static func appendUInt32(_ value: UInt32, to data: inout Data) {
    data.append(UInt8((value >> 24) & 0xFF))
    data.append(UInt8((value >> 16) & 0xFF))
    data.append(UInt8((value >> 8) & 0xFF))
    data.append(UInt8(value & 0xFF))
  }
}

private struct MIDIEvent {
  let tick: Int
  let order: Int
  let data: Data
}

private struct TempoSegment {
  let timeSec: Double
  let bpm: Double
  let tick: Int
}

private struct TempoTimeline {
  private static let maximumMIDITick = 0x0FFF_FFFF

  let segments: [TempoSegment]
  let ticksPerBeat: Int

  init(points: [TempoPoint], ticksPerBeat: Int) throws {
    let sorted = points.sorted(by: { $0.timeSec < $1.timeSec })
    let initialBPM = sorted.first?.bpm ?? 120
    guard initialBPM.isFinite, initialBPM > 0 else {
      throw AMTProjectError.malformedManifest("tempo map 为空或 BPM 无效")
    }
    var result = [TempoSegment(timeSec: 0, bpm: initialBPM, tick: 0)]
    var priorTime = 0.0
    var priorBPM = initialBPM
    var priorTick = 0
    for point in sorted {
      guard point.timeSec.isFinite,
        point.timeSec >= priorTime,
        point.bpm.isFinite,
        point.bpm > 0
      else {
        throw AMTProjectError.malformedManifest("tempo map 非单调或 BPM 无效")
      }
      let delta = point.timeSec - priorTime
      let deltaTicks = (delta * priorBPM * Double(ticksPerBeat) / 60).rounded()
      guard deltaTicks.isFinite,
        deltaTicks >= 0,
        deltaTicks <= Double(Self.maximumMIDITick - priorTick)
      else {
        throw AMTProjectError.malformedManifest(
          "tempo map 超出标准 MIDI 时间范围"
        )
      }
      let tick = priorTick + Int(deltaTicks)
      if point.timeSec == 0 {
        result[0] = TempoSegment(timeSec: 0, bpm: point.bpm, tick: 0)
      } else {
        result.append(
          TempoSegment(
            timeSec: point.timeSec,
            bpm: point.bpm,
            tick: tick
          )
        )
      }
      priorTime = point.timeSec
      priorBPM = point.bpm
      priorTick = tick
    }
    segments = result
    self.ticksPerBeat = ticksPerBeat
  }

  func tick(at timeSec: Double) throws -> Int {
    guard timeSec.isFinite, timeSec >= 0 else {
      throw AMTProjectError.malformedManifest("MIDI 事件时间无效")
    }
    let segment = segments.last(where: { $0.timeSec <= timeSec }) ?? segments[0]
    let delta = timeSec - segment.timeSec
    let deltaTicks = (delta * segment.bpm * Double(ticksPerBeat) / 60).rounded()
    guard deltaTicks.isFinite,
      deltaTicks >= 0,
      deltaTicks <= Double(Self.maximumMIDITick - segment.tick)
    else {
      throw AMTProjectError.malformedManifest(
        "音符时间超出标准 MIDI 时间范围"
      )
    }
    return segment.tick + Int(deltaTicks)
  }
}
