import Foundation

public struct MusicalPosition: Sendable, Equatable {
  public let bar: Int
  public let beat: Int
  public let beatFraction: Double
  public let numerator: Int
  public let denominator: Int

  public init(
    bar: Int,
    beat: Int,
    beatFraction: Double,
    numerator: Int,
    denominator: Int
  ) {
    self.bar = bar
    self.beat = beat
    self.beatFraction = beatFraction
    self.numerator = numerator
    self.denominator = denominator
  }

  public var displayLabel: String {
    "第 \(bar) 小节 · 第 \(beat) 拍"
  }
}

public struct BeatMarker: Sendable, Equatable, Identifiable {
  public let timeSec: Double
  public let bar: Int
  public let beat: Int
  public let numerator: Int
  public let denominator: Int

  public var id: String {
    "\(timeSec)-\(bar)-\(beat)"
  }

  public var isDownbeat: Bool { beat == 1 }
}

public enum RhythmTimeline {
  public static func representativeBPM(_ rhythm: RhythmMap) -> Double? {
    let bpms =
      rhythm.tempoMap
      .map(\.bpm)
      .filter { $0.isFinite && (1...1_000).contains($0) }
      .sorted()
    guard !bpms.isEmpty else { return nil }
    let midpoint = bpms.count / 2
    return bpms.count.isMultiple(of: 2)
      ? (bpms[midpoint - 1] + bpms[midpoint]) / 2
      : bpms[midpoint]
  }

  public static func tempo(at timeSec: Double, rhythm: RhythmMap) -> Double {
    rhythm.tempoMap
      .last(where: { $0.timeSec <= timeSec && $0.bpm.isFinite && $0.bpm > 0 })?
      .bpm
      ?? representativeBPM(rhythm)
      ?? 120
  }

  public static func meter(at timeSec: Double, rhythm: RhythmMap) -> MeterPoint {
    rhythm.meterMap
      .last(where: {
        $0.timeSec <= timeSec
          && $0.numerator > 0
          && $0.denominator > 0
      })
      ?? MeterPoint(timeSec: 0, numerator: 4, denominator: 4)
  }

  public static func beatDuration(
    at timeSec: Double,
    rhythm: RhythmMap
  ) -> Double {
    let meter = meter(at: timeSec, rhythm: rhythm)
    return 60 / tempo(at: timeSec, rhythm: rhythm)
      * 4 / Double(meter.denominator)
  }

  public static func markers(
    duration: Double,
    rhythm: RhythmMap,
    maximumCount: Int = 20_000
  ) -> [BeatMarker] {
    guard duration.isFinite, duration > 0, maximumCount > 0 else { return [] }
    let events =
      rhythm.events
      .filter {
        $0.timeSec.isFinite && $0.timeSec >= 0 && $0.timeSec <= duration + 0.001
      }
      .sorted { $0.timeSec < $1.timeSec }
    if !events.isEmpty {
      var bar = 0
      return events.prefix(maximumCount).map { event in
        if event.isDownbeat || event.beatNumber == 1 {
          bar += 1
        }
        if bar == 0 { bar = 1 }
        let meter = meter(at: event.timeSec, rhythm: rhythm)
        return BeatMarker(
          timeSec: event.timeSec,
          bar: bar,
          beat: max(1, event.beatNumber),
          numerator: meter.numerator,
          denominator: meter.denominator
        )
      }
    }

    var result: [BeatMarker] = []
    var time = 0.0
    var bar = 1
    var beat = 1
    var lastMeterTime = -Double.infinity
    while time <= duration + 0.001, result.count < maximumCount {
      let currentMeter = meter(at: time, rhythm: rhythm)
      if currentMeter.timeSec > lastMeterTime && currentMeter.timeSec > 0 {
        bar += beat == 1 ? 0 : 1
        beat = 1
      }
      lastMeterTime = max(lastMeterTime, currentMeter.timeSec)
      result.append(
        BeatMarker(
          timeSec: time,
          bar: bar,
          beat: beat,
          numerator: currentMeter.numerator,
          denominator: currentMeter.denominator
        )
      )
      let interval = beatDuration(at: time, rhythm: rhythm)
      guard interval.isFinite, interval > 0 else { break }
      time += interval
      beat += 1
      if beat > currentMeter.numerator {
        beat = 1
        bar += 1
      }
    }
    return result
  }

  public static func position(
    at timeSec: Double,
    duration: Double,
    rhythm: RhythmMap
  ) -> MusicalPosition {
    let markers = markers(duration: max(duration, timeSec + 1), rhythm: rhythm)
    guard !markers.isEmpty else {
      return MusicalPosition(
        bar: 1,
        beat: 1,
        beatFraction: 0,
        numerator: 4,
        denominator: 4
      )
    }
    let boundedTime = max(0, timeSec)
    let index =
      markers.lastIndex(where: { $0.timeSec <= boundedTime })
      ?? 0
    let marker = markers[index]
    let nextTime =
      index + 1 < markers.count
      ? markers[index + 1].timeSec
      : marker.timeSec + beatDuration(at: marker.timeSec, rhythm: rhythm)
    let interval = max(0.001, nextTime - marker.timeSec)
    let fraction = min(0.999, max(0, (boundedTime - marker.timeSec) / interval))
    return MusicalPosition(
      bar: marker.bar,
      beat: marker.beat,
      beatFraction: fraction,
      numerator: marker.numerator,
      denominator: marker.denominator
    )
  }
}

public struct SustainFragmentGroup: Sendable, Equatable, Identifiable {
  public let pitchMIDI: Double
  public let noteIDs: [String]
  public let onsetSec: Double
  public let offsetSec: Double

  public var id: String {
    "\(pitchMIDI)-\(noteIDs.first ?? "empty")"
  }

  public var fragmentCount: Int { noteIDs.count }
}

public enum CanonicalTimeline {
  public static func clippedNotes(
    _ notes: [EditorNote],
    duration: Double
  ) -> [EditorNote] {
    guard duration.isFinite, duration > 0 else { return notes }
    return notes.compactMap { note in
      guard note.onsetSec < duration else { return nil }
      var clipped = note
      clipped.offsetSec = min(note.offsetSec, duration)
      return clipped.offsetSec > clipped.onsetSec ? clipped : nil
    }
  }
}

public enum SustainFragmentAnalyzer {
  public static func fragmentedGroups(
    notes: [EditorNote],
    timelineEnd: Double,
    maximumGap: Double = 0.03,
    shortDurationThreshold: Double = 0.35
  ) -> [SustainFragmentGroup] {
    groups(
      notes: CanonicalTimeline.clippedNotes(
        notes,
        duration: timelineEnd
      ),
      timelineEnd: timelineEnd,
      maximumGap: maximumGap,
      shortDurationThreshold: shortDurationThreshold,
      requireTrailing: false
    )
  }

  public static func trailingGroups(
    notes: [EditorNote],
    timelineEnd: Double,
    maximumGap: Double = 0.03,
    shortDurationThreshold: Double = 0.35
  ) -> [SustainFragmentGroup] {
    groups(
      notes: notes,
      timelineEnd: timelineEnd,
      maximumGap: maximumGap,
      shortDurationThreshold: shortDurationThreshold,
      requireTrailing: true
    )
  }

  private static func groups(
    notes: [EditorNote],
    timelineEnd: Double,
    maximumGap: Double,
    shortDurationThreshold: Double,
    requireTrailing: Bool
  ) -> [SustainFragmentGroup] {
    guard timelineEnd.isFinite, timelineEnd > 0 else { return [] }
    var result: [SustainFragmentGroup] = []
    for pitchNotes in Dictionary(grouping: notes, by: \.pitchMIDI).values {
      let ordered = pitchNotes.sorted {
        ($0.onsetSec, $0.offsetSec, $0.id)
          < ($1.onsetSec, $1.offsetSec, $1.id)
      }
      var chain: [EditorNote] = []
      var chainEnd = -Double.infinity
      for note in ordered {
        if !chain.isEmpty, note.onsetSec > chainEnd + maximumGap {
          if let candidate = candidate(
            chain,
            effectiveEnd: timelineEnd,
            shortDurationThreshold: shortDurationThreshold,
            requireTrailing: requireTrailing
          ) {
            result.append(candidate)
          }
          chain = []
          chainEnd = -Double.infinity
        }
        chain.append(note)
        chainEnd = max(chainEnd, note.offsetSec)
      }
      if let candidate = candidate(
        chain,
        effectiveEnd: timelineEnd,
        shortDurationThreshold: shortDurationThreshold,
        requireTrailing: requireTrailing
      ) {
        result.append(candidate)
      }
    }
    return result.sorted {
      ($0.onsetSec, $0.pitchMIDI, $0.id)
        < ($1.onsetSec, $1.pitchMIDI, $1.id)
    }
  }

  private static func candidate(
    _ notes: [EditorNote],
    effectiveEnd: Double,
    shortDurationThreshold: Double,
    requireTrailing: Bool
  ) -> SustainFragmentGroup? {
    guard let first = notes.first, let last = notes.last,
      notes.count >= 4,
      last.offsetSec - first.onsetSec >= 2
    else {
      return nil
    }
    if requireTrailing {
      guard last.offsetSec >= effectiveEnd - 0.5,
        first.onsetSec >= effectiveEnd - 30
      else {
        return nil
      }
    }
    let shortCount = notes.lazy.filter {
      $0.offsetSec - $0.onsetSec <= shortDurationThreshold
    }.count
    guard shortCount >= 3, shortCount * 2 >= notes.count else {
      return nil
    }
    return SustainFragmentGroup(
      pitchMIDI: first.pitchMIDI,
      noteIDs: notes.map(\.id),
      onsetSec: first.onsetSec,
      offsetSec: min(effectiveEnd, last.offsetSec)
    )
  }
}

public enum PercussionRepeatAnalyzer {
  public static func trailingGroups(
    notes: [EditorNote],
    timelineEnd: Double,
    maximumOnsetGap: Double = 0.5,
    shortDurationThreshold: Double = 0.1
  ) -> [SustainFragmentGroup] {
    guard timelineEnd.isFinite, timelineEnd > 0 else { return [] }
    let timelineNotes = CanonicalTimeline.clippedNotes(
      notes,
      duration: timelineEnd
    )
    var result: [SustainFragmentGroup] = []
    for pitchNotes in Dictionary(
      grouping: timelineNotes,
      by: \.pitchMIDI
    ).values {
      let ordered = pitchNotes.sorted {
        ($0.onsetSec, $0.offsetSec, $0.id)
          < ($1.onsetSec, $1.offsetSec, $1.id)
      }
      var sequence: [EditorNote] = []
      for note in ordered {
        if let previous = sequence.last,
          note.onsetSec - previous.onsetSec > maximumOnsetGap
        {
          if let candidate = candidate(
            sequence,
            timelineEnd: timelineEnd,
            shortDurationThreshold: shortDurationThreshold
          ) {
            result.append(candidate)
          }
          sequence = []
        }
        sequence.append(note)
      }
      if let candidate = candidate(
        sequence,
        timelineEnd: timelineEnd,
        shortDurationThreshold: shortDurationThreshold
      ) {
        result.append(candidate)
      }
    }
    return result.sorted {
      ($0.onsetSec, $0.pitchMIDI, $0.id)
        < ($1.onsetSec, $1.pitchMIDI, $1.id)
    }
  }

  private static func candidate(
    _ notes: [EditorNote],
    timelineEnd: Double,
    shortDurationThreshold: Double
  ) -> SustainFragmentGroup? {
    guard let first = notes.first, let last = notes.last,
      notes.count >= 5,
      last.offsetSec >= timelineEnd - 0.5,
      first.onsetSec >= timelineEnd - 15,
      last.offsetSec - first.onsetSec >= 1
    else {
      return nil
    }
    let shortCount = notes.lazy.filter {
      $0.offsetSec - $0.onsetSec <= shortDurationThreshold
    }.count
    guard shortCount * 2 >= notes.count else { return nil }
    return SustainFragmentGroup(
      pitchMIDI: first.pitchMIDI,
      noteIDs: notes.map(\.id),
      onsetSec: first.onsetSec,
      offsetSec: min(timelineEnd, last.offsetSec)
    )
  }
}

public struct ProjectReviewIssue: Sendable, Equatable, Identifiable {
  public enum Kind: String, Sendable, Hashable {
    case lowConfidence
    case veryShort

    public var label: String {
      switch self {
      case .lowConfidence: "低置信度"
      case .veryShort: "音符过短"
      }
    }
  }

  public let kind: Kind
  public let trackID: String
  public let noteID: String
  public let timeSec: Double
  public let detail: String

  public var id: String {
    "\(kind.rawValue)-\(trackID)-\(noteID)"
  }
}

public enum ProjectReviewAnalyzer {
  public static func issues(
    notes: [EditorNote],
    confidenceThreshold: Double = 0.5,
    shortDurationThreshold: Double = 0.04
  ) -> [ProjectReviewIssue] {
    var result: [ProjectReviewIssue] = []
    result.reserveCapacity(notes.count / 10)
    for note in notes {
      if let confidence = note.confidence,
        confidence <= confidenceThreshold
      {
        result.append(
          ProjectReviewIssue(
            kind: .lowConfidence,
            trackID: note.trackID,
            noteID: note.id,
            timeSec: note.onsetSec,
            detail: confidence.formatted(
              .percent.precision(.fractionLength(0))
            )
          )
        )
      }
      let duration = note.offsetSec - note.onsetSec
      if duration < shortDurationThreshold {
        result.append(
          ProjectReviewIssue(
            kind: .veryShort,
            trackID: note.trackID,
            noteID: note.id,
            timeSec: note.onsetSec,
            detail: "\(duration.formatted(.number.precision(.fractionLength(3)))) 秒"
          )
        )
      }
    }
    return result.sorted {
      ($0.timeSec, $0.trackID, $0.noteID, $0.kind.rawValue)
        < ($1.timeSec, $1.trackID, $1.noteID, $1.kind.rawValue)
    }
  }
}
