# Task 001: Mac bootstrap and deterministic song ingest

Status: complete (Mac verification 2026-07-23)

## Objective

Create a clean root development environment and initialize the private reference song as an auditable project. Do not install any ML model yet.

## Steps

1. Verify Git, Homebrew or equivalent, `uv`, Python 3.12, ffmpeg, and ffprobe.
2. Run `./scripts/bootstrap_mac.sh` and fix root-package issues only.
3. Initialize Git if this is not already a repository.
4. Confirm `.gitignore` protects private audio, private projects, weights, and model caches.
5. Locate the user-provided test MP3 under `data/private/inbox/`.
6. Initialize it with:

   ```bash
   uv run amt init-project \
     "data/private/inbox/姫乃樹リカ - 硝子のキッス.mp3" \
     --output "projects/private/glass-kiss"
   ```

7. Run `uv run amt show projects/private/glass-kiss`.
8. Verify the source SHA-256 equals the expected manifest hash.
9. Re-probe canonical FLAC and verify duration is close to the source.
10. Run `git status --short` and prove no private audio/project content is tracked.

## Acceptance criteria

- `make check` passes.
- The CLI works with spaces and Japanese characters.
- `projects/private/glass-kiss/manifest.json` exists.
- Original and canonical hashes are recorded.
- Canonical audio is 44.1 kHz stereo FLAC.
- A second attempt into the non-empty project refuses to overwrite it.
- No private data appears in `git status --short`.
- Exact commands and observed metadata are added under Evidence.

## Evidence

### Environment and bootstrap

Run on an Apple Silicon Mac from the repository root:

```bash
git init -b main
brew install uv
./scripts/bootstrap_mac.sh
```

Observed:

- Python `3.12.11`;
- Git `2.50.1 (Apple Git-155)`;
- ffmpeg and ffprobe `7.1.1`;
- uv `0.11.32` (`aarch64-apple-darwin`);
- platform `Darwin arm64`, macOS `15.7.5`;
- bootstrap unit tests: 4 passed;
- `fluidsynth` was not installed, but doctor reports it as optional.

The repository has its own `.git/` directory. No initial commit was created because
`docs/CODEX_WORKFLOW.md` reserves the commit for after user review.

### Private reference ingest

The user-provided source was copied into the ignored private inbox as:

```text
data/private/inbox/姫乃樹リカ - 硝子のキッス.mp3
```

Commands run:

```bash
shasum -a 256 "data/private/inbox/姫乃樹リカ - 硝子のキッス.mp3"
ffprobe -v error \
  -show_entries stream=codec_name,sample_rate,channels,channel_layout,duration,bit_rate \
  -show_entries format=duration,format_name,size,bit_rate \
  -of json "data/private/inbox/姫乃樹リカ - 硝子のキッス.mp3"
uv run amt init-project \
  "data/private/inbox/姫乃樹リカ - 硝子のキッス.mp3" \
  --output "projects/private/glass-kiss"
uv run amt show "projects/private/glass-kiss"
```

Observed source metadata:

- SHA-256: `3464cdb850fdb1796c2cc48e0580640f04c39062eb236143e1ff0f2bdc0d1dbe`;
- codec/container: MP3;
- sample rate: 44,100 Hz;
- channels/layout: 2, stereo;
- duration: `265.639184` seconds;
- audio bitrate: 320,000 bps;
- file size: 10,737,151 bytes.

Created private project:

```text
projects/private/glass-kiss
```

`projects/private/glass-kiss/manifest.json` exists and records both hashes.
Observed canonical audio:

- path: `projects/private/glass-kiss/audio/canonical/mix.flac`;
- SHA-256: `2c4ef424af20dd1eeb4c17b44ecb8da9a5f640ec26449e972ba4b45cb330ecde`;
- codec/container: FLAC;
- sample rate: 44,100 Hz;
- channels/layout: 2, stereo;
- duration: `265.614127` seconds;
- file size: 52,538,100 bytes;
- source/canonical duration difference: about `0.025057` seconds.

An independent initialization into a separate empty private project produced the
same canonical SHA-256, and `cmp -s` returned 0. The temporary comparison project
was then moved to the macOS Trash.

### Refusal to overwrite

The exact initialization command was run a second time against the non-empty
`projects/private/glass-kiss` directory. It returned exit code 1 with:

```text
error: Output directory is not empty: .../projects/private/glass-kiss
```

No existing project content was overwritten.

### Final checks and privacy

Commands run:

```bash
make check
git check-ignore -v \
  "data/private/inbox/姫乃樹リカ - 硝子のキッス.mp3" \
  "projects/private/glass-kiss/manifest.json" \
  "projects/private/glass-kiss/audio/canonical/mix.flac"
git ls-files "data/private/**" "projects/private/**" "weights/**" "datasets/**"
git status --short --untracked-files=all
```

Observed:

- `make check` passed: doctor passed all required tools, 4 unit tests passed,
  and source/tests compiled;
- ruff was not installed, so the Makefile used its documented compile-only
  lint fallback;
- all three private artifacts matched the intended `.gitignore` rules;
- `git ls-files` returned no private data;
- `git status --short --untracked-files=all` contained starter source files and
  `uv.lock`, but no private inbox audio or `glass-kiss` project artifacts.

Task 002 and all model installation/inference remain unstarted.
