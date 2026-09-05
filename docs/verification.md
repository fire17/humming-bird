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

v1.0.0 passed all three platform build jobs and the release publication job. A clean
pipx install from the published tag passes `--check` outside the source directory.
Homebrew install and `brew test fire17/tap/humming-bird` pass. The downloaded macOS
release ZIP matches its published SHA-256; the installed app's embedded binary passes
the same asset check. The frozen Mac game launched a five-bird flock through a PTY and
exited without orphaned workers.

The development garden has been visually iterated in a real macOS WezTerm window,
including multi-bird overlap, resize, extended-world camera, and approved artwork.
The frozen release build is exercised through a local PTY. Desktop-control access to
Terminal/WezTerm is blocked in the release session, so the new app window is **not yet
visually verified**; earlier development-session visual approval does not replace that.
Linux/Windows CI is automated verification, not a claim of human visual approval.
WSL runs the Linux build; an actual WSL desktop session is not available on this host.
The no-Python macOS release targets Apple Silicon; Intel Mac uses Python installation.

Font-specific seams may still appear in embedded chat output panes. Use a normal
truecolor terminal and a block/Braille-capable monospace font. Legacy POSIX terminals
without release events use repeated-key steering, not true independent held keys.
