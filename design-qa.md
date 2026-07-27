# AMT Studio dual-theme design QA

## Evidence

- Source visual truth, precision:
  `/Users/apple/.codex/generated_images/019f9103-ae3f-7c22-b0e2-4af71f31e6e1/call_tNn0AzLJnzePsR4jhnxrrn1A.png`
- Source visual truth, spectrum:
  `/Users/apple/.codex/generated_images/019f9103-ae3f-7c22-b0e2-4af71f31e6e1/call_LAP8d709XOKB7LKmHiUch8jK.png`
- Rendered precision window:
  `/tmp/amt-studio-precision-final-window.png`
- Rendered spectrum window:
  `/tmp/amt-studio-spectrum-final-window.png`
- Appearance settings:
  `/tmp/amt-studio-appearance-sheet-v1.png`
- Side-by-side precision comparison:
  `/tmp/amt-design-qa-precision-final.png`
- Side-by-side spectrum comparison:
  `/tmp/amt-design-qa-spectrum-final.png`

The source visuals are 1586 x 992 pixels. The live macOS window was set to
1400 x 900 points at Retina 2x density; the window-only capture includes the
native shadow. Both sides were normalized to 1000 pixels high before the
side-by-side comparison.

## State and scope

The source visual shows an in-progress Hyak task. The real task was already
`COMPLETED`, so the implementation evidence correctly shows the fetched
editing workspace instead of fabricating a running state. The comparison
therefore judges the shared shell, hierarchy, typography, sidebar, toolbar,
palette, waveform treatment, and theme distinction. The implemented
in-progress view uses the same shell and an explicit five-stage pipeline, but
no false progress percentage or estimated time.

Primary interactions tested in the signed app:

- open Appearance settings;
- switch from Precision to Spectrum without reloading the project;
- close and reopen the app to verify persistence;
- switch back to Precision as the current default;
- open the real completed project and render its waveform and piano roll;
- inspect the consolidated Project and Export toolbar menus.

## Full-view comparison

- Typography: the native SF family, rounded product title, monospaced
  uppercase signal-lab caption, and compact secondary labels preserve the
  hierarchy of the source without introducing a web-style display font.
- Spacing and layout: the sidebar/detail split, restrained 8-12 point radii,
  compact toolbar, and wide working canvas match the practical laboratory
  direction. The completed editor intentionally replaces the source's running
  pipeline.
- Colors and tokens: Precision uses graphite, teal, and lime; Spectrum uses
  midnight navy, cyan, and violet. Waveform and note colors now inherit the
  selected mode instead of retaining system blue.
- Image quality: the product does not need raster artwork. All controls use
  native SF Symbols, while the waveform is rendered from the real decoded
  audio samples.
- Copy: task state, Job ID, connection state, exports, and uncertainty labels
  are drawn from actual application state. No fabricated percentage, time
  estimate, codec metadata, or accuracy claim is shown.

## Focused comparison

The Appearance sheet was inspected separately because its text and selection
states are too small in the full-window capture. Both cards remain readable,
the selected mode has a clear border and checkmark, and the warning explicitly
states that appearance changes do not rerun Hyak or alter MIDI.

## Comparison history

1. First pass found two P2 issues: eleven unrelated toolbar controls made the
   header read like a demo, and the real waveform remained system blue in
   Precision mode.
2. The toolbar was consolidated into explicit Project and Export menus, with
   the full-version multi-track MIDI export named first. Waveform and note
   rendering were connected to the active theme tokens.
3. The revised signed app was recaptured in both modes. No actionable
   P0/P1/P2 issue remained in the compared surfaces.

## Findings

No actionable P0, P1, or P2 findings remain.

P3 follow-up polish: a future pass may add a compact overview/zoom control for
very long songs, because the current piano roll can devote substantial empty
space to tracks whose first notes begin late. This is an editor workflow
enhancement, not a blocker for the theme release.

final result: passed
