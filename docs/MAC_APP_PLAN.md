# macOS application plan

## Product architecture

Use SwiftUI for the native interface and AVFoundation for media playback. Keep the transcription backend behind a versioned local job API.

During research, the app launches `amt` or a local Python service. Later, a model pack can use CoreML, ONNX Runtime, MPS-backed Python, or a bundled executable. The project file format must not depend on the deployment mechanism.

## Main windows

### Project browser

- import MP3/WAV/M4A/FLAC;
- show project status, duration, last run, and available exports;
- reopen without inference.

### Transcription workspace

- original waveform and optional stem waveforms;
- piano roll with per-track colors;
- score view when MusicXML is available;
- transport synchronized across original, stems, and synthesized MIDI;
- track mixer with mute/solo;
- confidence heat map and review queue;
- candidate alternatives around ambiguous passages.

### Note inspector

- pitch, onset, offset, velocity, instrument, melody status;
- confidence and contributing model paths;
- move, resize, split, merge, delete, reassign;
- audition note and local passage;
- mark reference/correction status.

## Non-destructive edit model

Store edits as operations over a base event set:

- create note;
- delete note;
- change pitch;
- move onset/offset;
- split/merge;
- change track/instrument;
- choose alternative candidate;
- mark ambiguity.

Support undo/redo and keep an audit trail. Exports are regenerated from the current project state.

## Backend API concept

```text
amt project init <audio>
amt run <project> --pipeline baseline
amt status <project>
amt export <project> --format midi,musicxml
amt validate <project>
```

A local service may expose equivalent endpoints plus streamed progress events. Avoid designing the SwiftUI interface around model-specific CLI output.

## Deployment progression

1. Research CLI on Mac and Hyak.
2. SwiftUI app calling local CLI.
3. Stable worker service with progress and cancellation.
4. Package verified model environments or convert selected models.
5. Hardware-aware model presets: quality, balanced, fast.
6. Signed/notarized local app after the private research version is stable.
