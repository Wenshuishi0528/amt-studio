# Source-separation worker

Use `audio-separator` as a model runner, not as a declaration that its default model is best. Benchmark at least one high-quality two-stem vocal model and one multi-stem model. Hash every downloaded model file and record its independent terms.

Mac installation pattern:

```bash
uv venv --python 3.12 .venv
source .venv/bin/activate
uv pip install "audio-separator[cpu]"
audio-separator --env_info
audio-separator --list_models
```

Task 003 must compare downstream transcription quality, not only separation listening quality.
