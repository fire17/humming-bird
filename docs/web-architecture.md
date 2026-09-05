# One game, two surfaces

The playable website is **https://hummingbird.akeyo.io/**. The terminal application
remains available on macOS, Linux, WSL and Windows. The website needs no Python
installation, account, backend game server, or image-generation service.

## No forked JavaScript physics

`hummingbird_game.py`, `hummingbird_brain.py` and `hummingbird_flock.py` are the
single source for movement, boids, targeting, feeding, landing and simulation.
The terminal hosts companions in native processes. `web/bridge.py` hosts the same
brains inside one dedicated browser Web Worker, running CPython through pinned
Pyodide/WASM. A single worker avoids multiplying the interpreter's memory by the
flock size. Rendering and input stay on the browser main thread.

`scripts/export_web.py` extracts all 60 bird poses, eight heart phases and the
complete game leaf from the approved ANSI assets. It uses the native compositor's
8×8 glyph masks to create an RGBA atlas. Exact black becomes transparent;
colored backgrounds stay visible. The physical cell aspect is 3:8, matching the
terminal baseline. WebGL batches the scene in one draw and performs HSL hue shifts
in a shader. A Canvas fallback is available (its hue rotation is approximate).
There is no per-frame raster generation or thousands-of-DOM-nodes renderer.

## Automatic update contract

Edit the canonical repository, not a historical `/sas` snapshot. Every push to
`main` triggers `.github/workflows/web.yml`: rebuild assets and source bundle,
run native tests, run the shipped WASM interpreter, compare a seeded 24-bird
simulation against native Python, then publish the tested build. The engine zip
and build manifest record source hashes; tests require byte-identical Python.

This automatically carries **shared game behavior and artwork** to the web. New
terminal-only menus, input protocols or animation-studio controls still need a
browser UI adapter; they cannot magically become HTML. The website currently
exposes the garden, not the terminal's complete standalone animation studio.

Open production tabs check for a new version once per minute and offer a reload,
preserving browser settings. They do not interrupt a live game without asking.
Local development reloads automatically after a successful source/art rebuild.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install .
bun install --frozen-lockfile
bun run dev                 # http://localhost:4173; source/art watch + reload
bun run build
bun run test                # actual WASM/native parity, not a JS mock
.venv/bin/python -m unittest discover -v
```

## Performance and boundaries

- Simulation and rendering target 30 Hz; wing motion is independently sampled.
- Approved art atlas: about 68 KB PNG. The locally hosted interpreter/runtime is
  about 13 MB before HTTP compression: first-load cost in exchange for zero
  duplicated simulation code. Subsequent visits benefit from HTTP caching.
- Browser tabs pause simulation when hidden; there is no catch-up burst.
- Settings use browser-local storage, separate from native preferences. Reduced
  motion starts a fresh garden paused and calm, with an explicit Resume button.
- Keyboard uses an independent held-key set, released on blur. Touch has a flight
  pad and tap-to-plant; desktop uses double-click-to-plant.
- Local measured desktop: 30 fps with 24 birds / 60 hearts, about 2.5 ms engine
  work and 0.08 ms render submission. Submission time excludes GPU execution;
  these are local observations, not a guarantee on every device.
- Visual checks: desktop and 390×844 responsive viewport in a Chromium browser.
  Actual iOS Safari, Android, and low-end GPU performance remain unverified.

No analytics. Runtime files come from this site's origin. Version checking is
the only periodic network activity after startup.

## Release / handoff

`/sas` keeps a private, hashed snapshot and complete conversation; no conversation
or local preferences belong in the public repo. Commit changes on `main` to
deploy the website. Bump the Python/CLI/app version together and create `vX.Y.Z`
for native release builds, then update the Homebrew formula's source checksum.
Do not hand-edit generated `web-dist`: it is intentionally git-ignored.
