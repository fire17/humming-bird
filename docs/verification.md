# Release verification

The build workflow verifies each target independently; see its public run log for the
actual result. Do not equate a successful cross-platform import with native input testing.

## Automated gates

- Game physics, common AI, reservations, recovery, capture density, compositing, camera,
  resize, preferences, input parsing, and native Windows event translation tests.
- Windows console integration: allocate a console if needed, inject W/D press and D
  release, consume through ReadConsoleInputW, confirm mode restoration.
- Asset check: 60 wing poses × eight heart phases, 60 bird-only poses, eight extracted
  hearts, and the complete 36-cell leaf with expected bounds.
- Wheel build and frozen executable `--check` on macOS, Linux and Windows.

## Live boundaries

The development garden has been visually iterated in a real macOS WezTerm window,
including multi-bird overlap, resize, extended-world camera, and approved artwork.
The release build is also checked in a real local terminal before handoff.
Linux/Windows CI is automated verification, not a claim of human visual approval.
WSL runs the Linux build; an actual WSL desktop session is not available on this host.
The no-Python macOS release targets Apple Silicon; Intel Mac uses Python installation.

Font-specific seams may still appear in embedded chat output panes. Use a normal
truecolor terminal and a block/Braille-capable monospace font. Legacy POSIX terminals
without release events use repeated-key steering, not true independent held keys.
