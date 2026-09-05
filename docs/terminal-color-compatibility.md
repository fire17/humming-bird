# Terminal color compatibility

`hummingbird_colors.py` is a dependency-free output adapter, integrated into both
garden and studio output in v1.1.0. The Mac launcher uses WezTerm and its isolated
profile. `--color-mode auto|truecolor|256|16` selects output; RGB asset loading,
heart extraction and compositing remain unchanged. The original background
implementation notes below record the integration design and its limitations.

## Diagnosis and scope

The current `hummingbird_tui.cell_escape()` always emits semicolon-form 24-bit
foreground/background SGR (`38;2` and `48;2`). Garden HUD and studio status lines
also contain hardcoded RGB SGR, and the approved studio frame caches contain RGB
SGR. Adapting only the cell encoder would leave other output paths broken.

The supplied Apple Terminal screenshot is consistent with unsupported RGB SGR
being interpreted incorrectly. Setting `COLORTERM=truecolor` is only a claim of
capability, not an upgrade to a terminal's renderer. A truecolor terminal retains
the approved palette; indexed output provides a reduced-palette approximation.

The adapter changes color **at output**, not in asset loading, heart extraction,
hue shifting, masking, or composition. The exact-black color key remains RGB
`000000` throughout those operations. Geometry, glyphs, cursor sequences, input
protocols, and asset files are not changed.

## Mode selection

`select_color_mode(requested=None, env=None)` returns immutable `ColorSupport`
with `mode` and an explanatory `reason`. It reads the environment without
mutating it and performs no terminal queries, palette writes, subprocess calls,
or platform-specific imports. Resolve once per application run.

| Input | Selected output |
| --- | --- |
| Explicit `truecolor`, `256`, or `16` | The requested mode |
| No CLI selection, `HUMMINGBIRD_COLOR_MODE` set | Application environment override |
| Explicit CLI `auto` | Detection; ignores the application environment override |
| `TERM_PROGRAM=Apple_Terminal` | 256; limited to 16 through a non-extended multiplexer |
| Direct-color `TERM`, e.g. `tmux-direct` | Truecolor, except the Apple Terminal guard |
| tmux/screen hop without a direct-color `TERM` | 256 if its `TERM` says `256color`, otherwise 16 |
| `COLORTERM=truecolor` or `24bit` | Truecolor, after the guards above |
| Recognized modern terminal identity / `WT_SESSION` | Truecolor |
| Other `TERM` containing `256color` | 256 |
| No reliable extended-color advertisement | 16 |

Recognized identities are explicit, small allowlists in the source, not assumptions
based only on macOS/Linux/Windows. An inherited outer-terminal identity does not
prove a multiplexer supports RGB. Configured tmux installations that really pass
RGB can explicitly select truecolor. SSH, wrappers, and stale environment values
can still misrepresent capabilities. No environment-only heuristic can prove the
entire route; the explicit application override is the escape hatch. Future Apple
Terminal versions can opt in if their RGB support has actually been verified.

Basic ANSI output is not a promise that `TERM=dumb`, redirected output, or a
historical VT100 can run an interactive graphics application. Existing TTY and
console-mode checks remain necessary; integration should give a clear error for
a known non-ANSI surface instead of attempting the game. This is not a plain-text
or `NO_COLOR` renderer: removing color alone destroys the background-channel art.

## Encoding contract

```python
from hummingbird_colors import ColorEncoder, select_color_mode

support = select_color_mode()  # or the parsed --color-mode value
output_colors = ColorEncoder(support.mode)
cell_text = output_colors.cell_escape(composited_cell)
terminal_text = output_colors.ansi(complete_output_payload)
```

`cell_escape()` preserves the current encoder's reset, bold, italic, underline,
blink, reverse, strikethrough, glyph, and default-channel behavior. It does not
mutate its input `pyte.Char`. `ansi()` adapts complete SGR-bearing payloads,
including combined attribute/color sequences and the common colon RGB forms.
It preserves non-SGR output and complete OSC/DCS/APC/PM strings. It is an adapter
for complete trusted rendering payloads, not a streaming terminal parser or ANSI
sanitizer; malformed/unknown sequences are preserved rather than guessed.

Truecolor payload adaptation returns the original string immediately, without
scanning or allocation. Cell styles, SGR transformations, and palette decisions
use bounded caches shared by encoder instances. Do not create a new encoder per
cell or cache entire changing garden frames.

256-color quantization picks the nearest squared-RGB-distance entry from the
fixed xterm cube and gray ramp (indices 16–255), avoiding theme-dependent ANSI
entries 0–15. Black is index 16, white 231, cyan 51, and magenta 201. This also
means palette conversion cannot change the black color key *before* composition.
16-color output uses standard dark/bright SGR (including background colors) and
does not abuse bold to select brightness. Its palette is necessarily influenced
by terminal themes, and fine color/shadow detail is lost. No dithering is added;
that could alter geometry or shimmer during animation.

The encoder preserves existing default-background semantics. Consequently,
`SGR 0`, `39`, and `49` still refer to the terminal's defaults; the adapter does
not change the user's palette or background preference. Exact black for erased
canvas cells must be established explicitly by the renderer (reset, set a black
background, then erase/clear) or by an isolated application profile. Avoid palette
OSC writes or global profile edits. Restore ordinary defaults when leaving the
alternate screen. This is separate from quantizing explicit RGB black correctly.

## Integration design

The background task supplied the adapter; the primary implementation subsequently
wired the two output boundaries and CLI. The following checklist records that design.

1. Add `--color-mode {auto,truecolor,256,16}` to `parse_args()` in
   `hummingbird_tui.py`, with `default=None` so the application environment
   override works. Use `COLOR_MODES` for choices. Resolve once, before entering
   terminal mode; turn a bad environment override into a concise CLI error.
   Keep `ColorSupport.reason` available to a diagnostic/help path.
2. Keep `load_frames()`, `load_leaf_overlays()`, `ansi_grid()`, and
   `load_game_assets()` on original RGB. In particular, heart extraction compares
   original RGB combined frames against original RGB bird-only frames. Never
   quantize `frames` before this comparison. Existing `cell_escape()` is also used
   by the overlay loader; don't blindly replace it with a mode-dependent global.
3. Use the resolved encoder's `cell_escape()` specifically in `draw_game()` after
   `GameRenderer.scene()` has composited the scene. At both complete payload write
   boundaries (`draw_game()` and studio `draw()`), run `encoder.ansi(payload)`
   before UTF-8 encoding. This covers HUD, status, cached studio art and overlays;
   already-indexed garden cells remain indexed. The additional cached-SGR scan is
   small. Optionally preconvert *display-only copies* of the studio frame/overlay
   cache after all RGB asset extraction, but do not mutate the source grids.
4. Ensure clear/erase paths establish a black canvas explicitly where required;
   leave exit/reset output unmodified so terminal state is restored. Keep the
   existing Windows VT enabling/restoration adapter; this module neither replaces
   it nor needs `curses`/`termios` on Windows.
5. Add `hummingbird_colors` to setuptools `py-modules` in `pyproject.toml`, and
   confirm the frozen executable includes the imported module. CLI defaults and
   help/docs should explain auto, overrides, and reduced palette fidelity.
6. Add integration coverage for both actual output paths and release smoke tests
   for all modes. Test Apple Terminal at 256, WezTerm at truecolor, a configured
   tmux hop, and Windows Terminal/native console visually. Include overlaps,
   black clearing, the studio, resize, and clean exit. Environment fixtures and
   emulator parsing alone do not verify the visible terminal.

Examples: `humming-bird --color-mode 256` and
`humming-bird --color-mode truecolor` (available since v1.1.0).

## Verification evidence

On macOS 14.4 ARM64 / Python 3.11.14, on 2026-09-05:

- `.venv/bin/python -m unittest test_colors -v`: 14 passing tests.
- `.venv/bin/python -m unittest discover -v`: 56 tests, one native-Windows skip.
- 25 detection fixtures cover Apple Terminal, stale RGB hints, multiplexers,
  direct-color TERM, Linux/unknown TERM, modern identities, and Windows Terminal.
- 512 seeded random RGB samples match a brute-force nearest search over the
  entire fixed 240-entry palette by squared RGB distance.
- All 556 runtime ANSI assets (480 combined frames, 60 birds, 16 overlays) have
  identical glyph/control streams after either fallback, with no remaining RGB
  SGR; 16-color output also has no indexed SGR. Source files remain unchanged.
- A real approved bird is decoded through `pyte` before/after 256 conversion;
  all 32×12 cell glyphs match and each decoded RGB channel equals its expected
  palette entry. Explicit black backgrounds, colored spaces, all current style
  attributes, combined SGR, colon forms, malformed preservation, controls and
  bounded cache reuse have dedicated assertions.

Microbenchmark: approved `bird-00.ansi`, all 384 cells, warm caches, minimum of
three 1,000-pass runs using `timeit.repeat`; no terminal I/O or compositor cost:

| Encoder | Milliseconds per 384-cell pass | UTF-8 bytes |
| --- | ---: | ---: |
| Existing RGB encoder | 0.246 | 9,045 |
| Cached truecolor encoder | 0.074 | 9,045 |
| Cached 256-color encoder | 0.074 | 7,151 |
| Cached 16-color encoder | 0.076 | 4,716 |

Adapting that complete 3,553-character source ANSI payload costs approximately
0.036 ms at 256 and 0.038 ms at 16 with warm SGR caches. The truecolor passthrough
rounded to 0.000 ms at this reporting precision. These are local microbenchmarks,
not a promise of whole-game frame rate; cold/dynamic palettes and terminal redraw
can cost more.

No native Windows run or real Apple Terminal/WezTerm visual inspection was
performed by this background task. Desktop terminal access was unavailable;
it was not bypassed. No installed app, CLI, assets, registry, global terminal
settings, commit, or public release was changed by this module task.
