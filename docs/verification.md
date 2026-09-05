# Release verification

## v1.1.0 web / terminal verification — 2026-09-05

- Native/WASM comparison: 24 birds, 60 hearts, 120 ticks, matching score, heart
  count, positions and wing phases (tolerance 1e-9); 67 captures with seed 42.
- Browser: visually checked the live local canvas at 1280×720 and 390×844.
  24 birds / 60 hearts sustained 30 fps. Engine approximately 2.5 ms/step;
  WebGL submission approximately 0.08 ms, excluding GPU execution time.
- Unit coverage includes browser-host shared class identity, target uniqueness,
  full-flock collection, finite positions, resize, pause, pilot multi-key input,
  saved-setting bounds, byte-identical source bundle and both terminal output modes.
- Physical iOS/Android and non-Chromium browser checks are not yet performed.

## Local Mac launcher correction — 2026-09-05

User-supplied screenshot confirmed that the v1.0.0 app launched under Apple Terminal
with badly misinterpreted RGB colors. The installed local app now starts WezTerm via
an app-owned configuration: black/opaque background, Menlo, and Kitty key events.
Its previous app bundle was retained under private-evidence/mac-launcher-v1/.
WezTerm parsed the profile successfully; the running process command line confirms
the installed app's profile and executable. Signature verification and packaging tests
pass. Direct terminal-window screenshot inspection remains blocked; user screenshot
confirmation is requested. This correction is included in the v1.1.0 source/build.

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
