# Integration contract

The CLI defaults to the garden; `--studio` selects the original tuning screen.
`hummingbird_tui.py` loads approved cached artwork and owns terminal I/O.
`hummingbird_game.py` owns world state, camera transforms, physics, and cell composition.
`hummingbird_brain.py` is the common autonomous flight policy for bird 1 and companions.
`hummingbird_swarm.py` provides nonblocking process IPC and unique target reservations.
`hummingbird_terminal.py` is the POSIX / Windows input boundary.

## Embed in another TUI

1. Load frames with `load_frames()`, `load_leaf_overlays()`, and `load_game_assets()`.
2. Construct `GameRenderer` with those assets and `colored`, and `GameWorld` with
   terminal dimensions, monotonic time, and a random generator.
3. At 30 Hz, update inputs, call `swarm.prepare(world)`, `world.update(now, dt)`, then
   `swarm.update(world, now, dt)`. Render `renderer.scene(world, now)` through your TUI.
4. Resize the world whenever dimensions change. Use its world/screen conversion for
   pointer input. Do not apply camera offsets twice or bake them into saved positions.
5. Close worker processes and restore terminal modes on every exit path. For frozen
   executables, call `multiprocessing.freeze_support()` before imports/argument parsing.

Scene values are `pyte.screens.Char` objects keyed by cell `(x, y)` positions. Preserve
foreground/background colors, glyphs, and layer order. A space with a colored background
is not transparent. The compositor treats exact black channels as a color key and uses
approximate glyph coverage; this is not a general-purpose pixel-alpha implementation.

## Keep these invariants

- Approved bird raster ratio is represented by Chafa `--font-ratio 3/8`, canvas 32×12.
- There are 60 full-cycle poses. Original anchor poses remain unchanged.
- Wing and heart clocks are independent. Heart defaults to 1/3 rotation per second.
- Garden redraw rate is 30 Hz; virtual wing speed is separate from redraw rate.
- Bird 1 uses the common autonomous brain outside pilot mode. Resting animation state
  management still has primary/companion orchestration differences.
- Cell compositing does not hide the black scene background. HUD rows are excluded.
- Settings are atomic JSON. Do not overwrite a user's saved preferences for a demo.
- Input hooks are terminal-local. POSIX supports precise multi-holds only when the host
  terminal provides release events; no timeout can perfectly infer missing key releases.

## Handoff prompt

> Integrate Humming Bird into this TUI without replacing its approved assets. Read this
> architecture document and the source before editing. Keep a versioned copy of every
> art iteration; hold the body/head/tail/beak steady while wings articulate. Use the
> shared brain for all autonomous birds, retain async companions and nectar reservations,
> and keep 30 Hz rendering independent from perceived wing speed. Preserve mouse planting,
> native/Kitty held-key behavior, settings, viewport resize, and camera coordinates.
> Run unit and asset checks, then open a real terminal, inspect overlapping birds and
> leaves, test resizing/pilot/AI/camera, and iterate on visible defects. Report what was
> actually tested and any terminal-specific limitation. Never publish private captures
> or transcripts and never modify another running instance's settings for your tests.
