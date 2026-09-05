# Changelog

## Web effects parity — 2026-09-05

- Restore the native main-bird movement trail, five-dot nectar capture bursts,
  shared color fade/lifetimes, transient planting marker and capture feedback.
- Match native effect layer ordering and unselected-perch tint; retain all 69
  original approved art tiles pixel-for-pixel. Effects use one-cell GPU quads.
- Native behavior is unchanged: the existing effect rules are now shared with web.

## 1.1.0 — 2026-09-05

- Playable web garden with the same Python/WASM flight engine and approved art.
- Worker-isolated simulation, batched transparent WebGL sprites and touch controls.
- Responsive layout, independent held keys, saved settings, pause-on-hidden tabs.
- Automatic tested website builds on main; live at hummingbird.akeyo.io.
- Shared native/browser flock target policy with seeded WASM/native parity tests.

- Mac app launcher uses WezTerm with a private, opaque-black RGB profile and Kitty
  key events. It no longer silently falls back to Apple Terminal, whose color handling
  corrupts the current RGB artwork. Missing WezTerm produces an install instruction.
- Existing terminal profiles, artwork, and saved game settings remain unchanged.
- Output-only truecolor/256/16 palette detection and explicit --color-mode override.

## 1.0.0 — 2026-09-05

- First portable release of the neon hummingbird terminal garden and animation studio.
- Approved 60-pose wing cycle, independent spinning hearts, animated grass perches.
- Pilot mode, screensaver waves, continuous-full nectar, 1–24 asynchronous birds.
- Common flight brain, soft boids, unique nectar targeting and stuck-target recovery.
- Responsive four-direction extended-world camera and saved garden preferences.
- Native Windows keyboard/mouse events alongside POSIX/Kitty terminal input.
- Installable Python package and self-contained macOS, Linux/WSL, Windows downloads.

Known limitations: unsigned/not-notarized downloads; font-dependent cell compositing;
precise held-key support on POSIX requires a release-event-capable terminal.
