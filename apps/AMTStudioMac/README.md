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

Audio import, background inference progress/cancellation, worker/model-pack
integration, and production inference remain gated and are not embedded in
this package.
