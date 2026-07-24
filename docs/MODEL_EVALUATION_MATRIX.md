# Candidate model matrix

This is an experimental matrix, not a conclusion that every candidate must ship.

| Component | Candidate | Role | Mac M4 | Hyak | First evidence required |
|---|---|---|---|---|---|
| Direct multi-instrument AMT | MuScriptor large | Full-mix candidate tracks and instrument-conditioned decoding | MPS | CUDA | Raw JSONL/MIDI, runtime, instrument coverage, blind note metrics |
| Singing transcription | GAME v1.0.3 + official medium model | Lead-vocal note boundaries and float pitch from selected vocal stem | Orchestration, statistics, and result rendering only | Verified full-song A100/CUDA 12.9 selected-stem baseline | Human-reference vocal metrics and independent repeatability |
| General single-source AMT | Basic Pitch 0.4.0 ONNX | Vocal/instrument stem baseline with raw model tensors preserved | Orchestration, statistics, and result rendering only | Verified full-song CPUExecutionProvider selected-stem baseline on Slurm compute node | Human-reference precision/recall plus independent repeatability |
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
