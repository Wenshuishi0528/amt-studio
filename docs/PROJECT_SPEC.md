# Product and research specification

## Product statement

AMT Studio is a local macOS application that accepts a complete stereo song and produces editable musical transcriptions. The long-term output is a multi-track arrangement. The minimum product promise is a useful main-melody transcription.

The system is designed for private academic use first. It must remain capable of replacing research-only weights later without rewriting the editor or project format.

## User-visible outputs

For every imported song, the project may contain:

```text
main_melody.performance.mid
main_melody.score.mid
main_melody.musicxml
vocals.mid
backing_vocals.mid
drums.mid
bass.mid
keys.mid
guitar.mid
strings_synth.mid
other.mid
full_arrangement.mid
transcription_report.json
```

Not every track is guaranteed to exist. The report must state what was attempted, confidence, coverage, model provenance, and known ambiguity.

## Product modes

### 1. Main melody

- If clear lead vocals exist, lead vocal melody is the default target.
- For instrumental music, the user can choose automatic lead, piano, guitar, strings, wind, or another candidate.
- The software keeps alternative candidates when the lead is ambiguous.

### 2. Instrument-targeted transcription

The user selects one or more targets. The system may run source separation, instrument-conditioned decoding, or a specialized model.

### 3. Full arrangement research mode

The system produces candidate tracks for all supported instrument families. This mode emphasizes editable coverage and transparent uncertainty rather than pretending every note is correct.

## Two timing representations

### Performance representation

Preserves expressive timing, pitch bends, vibrato summaries, unquantized onset/offset, and model confidence. This is the closest machine interpretation of the recording.

### Score representation

Maps notes to a tempo/meter grid, resolves notation pitch, creates rests, ties, tuplets, measures, and voices, and exports MIDI/MusicXML. Score processing must never overwrite the performance representation.

## Non-negotiable product behaviors

- Local processing by default.
- The original audio remains unchanged.
- Users can compare original audio, stems, and synthesized transcription.
- Low-confidence notes are visible and filterable.
- Every note can be moved, resized, split, merged, deleted, or reassigned to a track.
- A user correction can be saved as an annotation for later evaluation/training, with explicit opt-in.
- The application can reopen a project without rerunning models.
- A project remains readable even if a third-party model worker is removed.

## Quality objective

Do not use a single undefined “accuracy” number. Product quality consists of:

- main-melody note precision/recall/F1;
- onset and onset+offset F1;
- octave error rate;
- instrument assignment accuracy;
- tempo, beat, and downbeat accuracy;
- per-track coverage;
- high-confidence precision at stated coverage;
- manual corrections per minute of music;
- time required to obtain a satisfactory score;
- failure detection and uncertainty calibration.

A long-term “90%” target must always name the metric, target repertoire, instrument class, timing tolerance, and coverage.

## Initial reference song

The first private reference is `姫乃樹リカ - 硝子のキッス.mp3`.

Known technical metadata:

- duration: approximately 265.639 seconds;
- codec: MP3;
- sample rate: 44.1 kHz;
- channels: stereo;
- nominal audio bitrate: 320 kb/s;
- SHA-256: `3464cdb850fdb1796c2cc48e0580640f04c39062eb236143e1ff0f2bdc0d1dbe`.

The audio itself is private and must not be committed.
