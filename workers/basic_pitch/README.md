# Basic Pitch worker

General instrument-agnostic baseline that is most appropriate one source/instrument at a time. Keep it in a separate Python 3.10 environment on Mac because the upstream compatibility matrix differs from the root Python 3.12 package.

Command pattern:

```bash
basic-pitch OUTPUT_DIR AUDIO \
  --save-model-outputs \
  --save-note-events \
  --sonify-midi
```

Record the actual serialization selected on Apple Silicon and preserve NPZ/CSV outputs.
