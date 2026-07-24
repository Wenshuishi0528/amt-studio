# Candidate model matrix

This is an experimental matrix, not a conclusion that every candidate must ship.

| Component | Candidate | Role | Mac M4 | Hyak | First evidence required |
|---|---|---|---|---|---|
| Direct multi-instrument AMT | MuScriptor large | Full-mix candidate tracks and instrument-conditioned decoding | MPS | CUDA | Raw JSONL/MIDI, runtime, instrument coverage, blind note metrics |
| Singing transcription | GAME | Lead-vocal note boundaries and pitch from vocal stem | uncertain until tested | CUDA | Compatible weight, exact preprocessing, blind vocal metrics |
| General single-source AMT | Basic Pitch | Vocal/instrument stem baseline and pitch bends | CoreML/Python 3.10 environment | CPU/GPU runtime dependent | Stem-specific precision/recall and fragmentation |
| Source separation | Audio Separator model candidates | Vocal/drum/bass/other stems and ensembles | CoreML/CPU depending model | CUDA | Leakage/deletion review and downstream AMT impact |
| Beat/downbeat | Beat This | Tempo grid and downbeats | CPU/MPS behavior to verify | CUDA | Beat/downbeat metrics and notation impact |
| Drums | ADTOF or another verified worker | Drum-event candidate track | verify | CUDA | Class-level drum F1 and timing |
| Alternative multi-track AMT | YourMT3/MT3 family | Independent candidate path | verify | CUDA | Installation reproducibility and blind metrics |

## Selection rule

A candidate remains in the pipeline only if it contributes one of:

- better blind quality;
- complementary errors that improve fusion;
- materially faster local inference at acceptable quality;
- a supported instrument unavailable elsewhere;
- useful uncertainty or expressive output.

Do not retain a model merely because it is famous or expensive.
