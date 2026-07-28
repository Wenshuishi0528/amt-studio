# AMT Studio Mac

This package is the Task 009 native shell. It deliberately contains no model
runtime.

Build and launch the real foreground `.app` bundle:

```bash
cd apps/AMTStudioMac
swift test
./scripts/build_app.sh
open -n "dist/AMT Studio.app" --args \
  --project /absolute/path/to/a/project
```

`swift run AMTStudio` is useful for compilation diagnostics, but a bare
SwiftPM executable is not a launchable foreground macOS app bundle.

The app can open a repository project that contains `manifest.json` and at
least one `exports/*/canonical_project.json`. Opening, editing, saving, and
MIDI export are local and do not start inference. Editor history is stored at:

```text
annotations/corrections/amt-studio-editor-v1.json
```

The original JSONL candidate events remain untouched.

When a project contains more than one canonical bundle or candidate track,
the user must choose the exact version and track. There is no implicit
`latest`, no automatic accuracy ranking, and no inference subprocess.

Task 009B1 adds a real waveform decoded from the existing canonical audio and
a review queue for confidence values already provided by the selected track.
Missing confidence stays explicitly unknown and is not treated as low
confidence. These features do not run inference or contact Hyak.

Task 009B2A adds a formal XCUITest target around the production Swift sources.
It generates a synthetic project at runtime, isolates the user's recent-project
preference, and covers project open, waveform/playback, confidence review,
editing, undo/redo, and restart restoration:

```bash
cd "$(git rev-parse --show-toplevel)"
make mac-ui-test
```

This target requires full Xcode and a logged-in macOS GUI session. It is kept
separate from the portable repository-level `make check`.

The private Beta can import one or many songs and submit the pinned workers to
Hyak Slurm. Upload and `sbatch` operations are serialized, while Slurm decides
whether submitted projects run together or remain pending. Every active project
is persisted across app restarts and monitored for result retrieval; local
CPU/GPU jobs remain serialized. If the SSH session expires, `连接 Hyak` opens
the local Terminal login flow; after password and Duo are completed, the app
detects the connection and resumes polling without resubmitting any job.

Fetched MuScriptor results open in `合奏` mode by default. The sidebar exposes
every predicted instrument track with note count, mute, solo, and volume
controls, while `当前音轨` isolates the track being edited. MIDI export offers
the current edited track, the current audible mix, or the complete multitrack.
The model labels are predictions, and all original canonical tracks remain
unchanged.

From `管理版本与音轨`, the current track can also be copied into an eligible
version of another completed song. The destination receives a new verified
custom bundle, source bundles remain immutable, and copied note timing is
preserved exactly even when it extends beyond the destination song timeline.
Single-track and whole-version MIDI exports retain those imported notes while
the target audio continues to use its truthful duration.

The app home screen and sidebar also list existing local song projects. Heavy
project/track loading and MIDI-preview generation run away from the UI thread,
the piano roll loads in bounded time segments, and selecting another track does
not decode the same source audio again. A project chosen outside the repository
can be reopened through a security-scoped bookmark.

`voice` is treated as a lead-vocal candidate, not proof of a complete main
melody. For that track the app reports gaps of at least three seconds, can seek
directly to each gap, and shows whether other predicted tracks contain notes
there. Those notes are diagnostic candidates only: the app never copies them
into `voice` automatically. Separate original-audio and MIDI-master controls
make the transcription audible during comparison.

`连接 Hyak` opens the login script through LaunchServices rather than
controlling Terminal with AppleScript. The build script uses an installed
Apple Development signing identity when available, which keeps the application
identity stable across rebuilds; system file-access prompts and Duo approval
still remain user-controlled.

Cancellation, MusicXML, training, and generic model-pack discovery remain
outside this private Beta. Inference is not embedded in the Mac app and never
runs on a Hyak login node.
