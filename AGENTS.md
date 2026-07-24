# Codex repository instructions

## Product objective

Build a local-first macOS automatic music transcription system. The long-term output is editable multi-track MIDI/MusicXML from a stereo song. The minimum guaranteed product path is a high-quality main-melody transcription. Treat main melody as a first-class output, not a by-product of multi-track transcription.

## Work discipline

- Read `00_START_HERE.md`, `docs/PROJECT_SPEC.md`, `docs/ARCHITECTURE.md`, `docs/DECISIONS.md`, and the active task file before changing code.
- Work on exactly one numbered task from `tasks/` at a time.
- Do not silently implement later tasks “for completeness.” Record useful future ideas in `docs/BACKLOG.md` instead.
- Before changing architecture, write or update an ADR in `docs/adr/`.
- Prefer the smallest reversible implementation that satisfies the current task's acceptance criteria.
- Do not claim a model, metric, command, license, or hardware behavior is verified unless it was actually checked. Put uncertain items in `status: unverified` and add a verification task.
- Never invent benchmark scores. Preserve raw outputs and compute metrics from fixed references.

## Dependency isolation

- The root `amt_core` package must remain lightweight and model-agnostic.
- Third-party ML stacks live in separate environments under `workers/<name>/`.
- Core code invokes workers through subprocesses and exchanges versioned JSON/JSONL files.
- Never install model dependencies into the root environment merely to make an import convenient.
- Basic Pitch may require a different Python version from the root environment. Keep it isolated.
- Pin model package versions, model identifiers, and weight checksums once verified.

## Data and privacy

- Never commit audio, stems, datasets, model weights, generated private transcriptions, credentials, or authorization correspondence.
- Private material belongs under `data/private/`, `projects/private/`, `weights/`, or external storage. These paths are ignored by Git.
- Every experiment must write a run manifest containing input hashes, commands, configuration, code commit, model version, weight hash, host, device, timestamps, and output hashes.
- Preserve raw model output. Derived/fused output must never overwrite raw output.
- Use song-level or artist-level splits. Never allow excerpts from the same song or artist to leak across training and test splits unless a documented experiment explicitly studies that setting.

## Canonical representation

- JSONL note events are the source of truth. MIDI and MusicXML are exports.
- Times are seconds in the original/canonical mix timeline.
- MIDI pitch may be floating-point for pitch-bend-aware events. Quantized notation pitch is a separate field.
- Every final note must retain provenance to one or more candidate notes.
- Keep performance timing and score timing as separate representations.
- Do not aggressively delete uncertain candidates. Preserve alternatives and confidence so the editor can expose them.

## Quality and evaluation

- Optimize for measured transcription quality and manual correction effort, not demo appearance.
- Report precision and recall together. A “90% accurate” high-confidence subset is invalid without coverage.
- Evaluate per instrument and per task: pitch/onset, offset, instrument assignment, tempo/downbeat, melody selection, and correction time.
- Use fixed blind references before tuning fusion rules.
- Do not start training a large end-to-end model until baselines, error taxonomy, and data coverage justify it.
- Prefer training a confidence/reranking/refinement model before retraining all audio encoders.

## Hyak rules

- Never run heavy computation on a `klone-login` node.
- Use Slurm jobs for all model inference, data preprocessing, and training beyond trivial inspection.
- Persistent code, environments, manifests, and important checkpoints belong in persistent group storage when available.
- Treat `/gscratch/scrubbed/$USER` as temporary compute storage. Sync important outputs back to the Mac and persistent storage.
- Checkpoint jobs must be resumable and idempotent.
- Job scripts must print environment diagnostics and write logs to a deterministic run directory.

## Engineering standards

- Python 3.12 for the root package unless a task documents otherwise.
- Use standard library first in `amt_core`; add dependencies only when they reduce real complexity.
- Type-hint public functions. Validate all boundary data.
- Use `pathlib`, explicit UTF-8, structured logging, and atomic file writes.
- Subprocess calls must use argument lists, not `shell=True`, unless a documented reason exists.
- Paths may contain spaces and non-ASCII characters. Tests must cover this.
- Run `make check` before declaring a task complete.
- Update the active task file with evidence, exact commands, and remaining limitations.

## Definition of done for a task

A task is complete only when:

1. Its acceptance criteria pass.
2. Tests and doctor checks pass or documented environmental blockers remain.
3. The implementation is reproducible from a fresh checkout.
4. Relevant docs and run commands are updated.
5. No private data or weights are staged for commit.
6. The final response lists changed files, commands run, test results, and known limitations.

## Code review rules

- Flag any change that mixes third-party model dependencies into the root environment.
- Flag loss of raw outputs or provenance.
- Flag evaluation on training/tuning material presented as blind performance.
- Flag a single aggregate “accuracy” number without metric definition and coverage.
- Flag hard-coded user paths, NetIDs, tokens, song names, or cluster node names.
- Flag compute performed on login nodes.
