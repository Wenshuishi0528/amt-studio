# MuScriptor worker

Initial direct full-mix multi-instrument baseline.

Upstream installation currently documents:

```bash
uv venv --python 3.12 .venv
source .venv/bin/activate
uv pip install muscriptor
muscriptor transcribe audio.wav --model large --beam-size 4 -o out.mid
muscriptor transcribe audio.wav --model large --beam-size 4 --format jsonl -o events.jsonl
```

On Apple Silicon, upstream reports automatic MPS use. On Hyak use an isolated CUDA environment in persistent storage. Task 002 must pin the package version, identify downloaded weights, hash them, capture `--help`, and convert native events without losing instrument labels.
