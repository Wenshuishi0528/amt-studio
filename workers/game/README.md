# GAME worker

Lead singing-voice transcription candidate. Use separated vocal stems and, as a controlled experiment, optionally the original mix.

Do not install until Task 004. Pin an authorized weight and its SHA-256. Preserve GAME native MIDI/TXT/CSV and convert to canonical events in a separate adapter.

Upstream command pattern:

```bash
python infer.py extract /path/to/audio.wav -m /path/to/model.pt --output-formats mid,txt,csv
```
