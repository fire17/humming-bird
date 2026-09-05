#!/usr/bin/env python3
"""Fast interactive terminal player for the hummingbird wingbeat."""

from __future__ import annotations

import argparse
from fractions import Fraction
import json
import math
import os
from pathlib import Path
import random
import re
import shutil
import signal
import subprocess
import sys
import time
from typing import Callable

import pyte
import humming_bird_assets
from hummingbird_terminal import read_input, start_input

from hummingbird_game import (
    DOUBLE_CLICK_SECONDS,
    MAX_NECTAR_LIMIT,
    GameRenderer,
    GameWorld,
)
from hummingbird_swarm import (
    SwarmManager,
    append_flock_digit,
    bounded_flock_count,
)


ROOT = Path(humming_bird_assets.__file__).resolve().parent
CHAFA = Path(shutil.which("chafa") or "chafa")
ANSI_CACHE = ROOT / "heart-spin/ansi"
TRUE60_ROOT = ROOT / "true60-cycle"
TRUE60_CACHE = TRUE60_ROOT / "heart-spin/ansi"
TRUE60_MANIFEST = TRUE60_ROOT / "manifest.json"
GAME_BIRD_CACHE = TRUE60_ROOT / "game-ansi"
LANDING_ANSI = ROOT / "landing/ansi-overlays"
WIDTH = 32
HEIGHT = 12
SIM_DISPLAY_FPS = 30.0
SIM_MOTION_FPS = 150.0
SPEED_RAMP_SECONDS = 0.45
HEART_PHASES = 8
LANDING_PHASES = 16
SETTLE_SECONDS = 1.0
FLUTTER_RETURN_SECONDS = 0.20
GAME_SETTINGS_PATH = (
    Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
    / "hummingbird-tui"
    / "settings.json"
)
GAME_SETTINGS_DEFAULTS = {
    "extended_board": False,
    "flock_count": 1,
    "nectar_limit": 50,
    "nectar_refill": False,
    "auto_spawn": False,
    "player_mode": False,
    "gravity_assist": True,
    "calm": False,
    "help_visible": True,
    "paused": False,
}

# Wing-cycle slots advanced per 30 Hz terminal repaint. Fractions deliberately
# use a phase accumulator: slow settings linger coherently, while non-integer
# fast settings avoid permanently skipping the same source poses.
SIM_SPEED_STEPS = {
    1: 0.25,
    2: 0.5,
    3: 0.75,
    4: 1.25,
    5: 2.0,
    6: 2.75,
    7: 3.5,
    8: 4.25,
    9: 5.0,
}
RANDOM_SPEED_LEVELS = (2, 3, 4, 5, 6, 7, 8, 9)
RANDOM_SPEED_WEIGHTS = (1.0, 1.0, 1.0, 1.0, 1.0, 0.5, 1.0 / 3.0, 0.25)
REST_FLUTTER_SPEED_LEVELS = (4, 5, 6, 7, 8)
REST_FLUTTER_SPEED_WEIGHTS = (1.0, 1.0, 0.5, 1.0 / 3.0, 0.25)

BIRD_GLYPHS = (
    # Natural monochrome/text glyphs first.
    "鳥", "鳶", "鷹", "鶴", "鴿", "雀",
    "燕", "鵬", "鴻", "鷺", "鶯", "鳳",
    "鷦", "鴟", "鵲", "鶲", "隹", "⿃",
    # VS15 requests text presentation; terminals may still use emoji fallback.
    "🐦︎", "🕊︎", "🦜︎", "🦅︎", "🐤︎", "🐥︎",
    "🐣︎", "🦆︎", "🦉︎", "🐧︎", "🦢︎", "🦩︎",
)

ANCHORS = (
    ROOT / "keyframes/00-wing-up-approved.png",
    ROOT / "keyframes/rework-kf02-backtail.png",
    ROOT / "keyframes/rework-kf03-backtail.png",
    ROOT / "keyframes/eighth-0375.png",
    ROOT / "keyframes/01-wing-mid-approved.png",
    ROOT / "keyframes/rework-kf06-angular.png",
    ROOT / "keyframes/rework-kf07-angular.png",
    ROOT / "keyframes/rework-kf08-angular.png",
    ROOT / "keyframes/02-wing-down-approved.png",
)

# Nine anchors form the downstroke. Reflect the inner seven to produce a
# seamless 16-frame upstroke without repeating either endpoint.
CYCLE = tuple(range(9)) + tuple(range(7, 0, -1))
MOUSE_EVENT_RE = re.compile(r"\x1b\[<(\d+);(\d+);(\d+)([Mm])")
KITTY_UNICODE_KEY_RE = re.compile(
    r"\x1b\[([0-9:]+)(?:;([0-9]+)(?::([123]))?)?(?:;([0-9:]+))?u"
)
KITTY_ARROW_KEY_RE = re.compile(r"\x1b\[1;([0-9]+)(?::([123]))?([ABCD])")
ANSI_INPUT_SEQUENCE_RE = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|.)")
KITTY_FUNCTIONAL_ARROWS = {
    57352: "up",
    57353: "down",
    57354: "right",
    57355: "left",
}


def random_speed_level(rng: random.Random, previous_level: int) -> int:
    if previous_level >= 6:
        return rng.choice((2, 3, 4, 5))
    return rng.choices(RANDOM_SPEED_LEVELS, RANDOM_SPEED_WEIGHTS, k=1)[0]


def load_game_settings(path: Path = GAME_SETTINGS_PATH) -> dict[str, int | bool]:
    settings = dict(GAME_SETTINGS_DEFAULTS)
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError, TypeError):
        loaded = {}
    if isinstance(loaded, dict):
        for key in (
            "auto_spawn", "nectar_refill", "player_mode", "gravity_assist",
            "calm", "help_visible", "paused", "extended_board",
        ):
            if isinstance(loaded.get(key), bool):
                settings[key] = loaded[key]
        value = loaded.get("flock_count")
        if isinstance(value, int) and not isinstance(value, bool):
            settings["flock_count"] = bounded_flock_count(value)
        value = loaded.get("nectar_limit")
        if isinstance(value, int) and not isinstance(value, bool):
            settings["nectar_limit"] = max(1, min(MAX_NECTAR_LIMIT, value))
    return settings


def save_game_settings(
    settings: dict[str, int | bool],
    path: Path = GAME_SETTINGS_PATH,
) -> None:
    payload = {"version": 1, **settings}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    except OSError:
        # Persistence must never interrupt animation or input handling.
        pass


def flock_delta_from_keys(keys: str) -> int:
    """Accept literal plus and Kitty implementations that report its base '='."""
    return keys.count("+") + keys.count("=") - keys.count("-")


def random_hold_seconds(rng: random.Random, level: int) -> float:
    maximum_centiseconds = 100 if level >= 6 else 300
    return rng.randrange(50, maximum_centiseconds + 1) / 100.0


def sampler_profile(frame_count: int, level: int) -> tuple[int, int]:
    """Return the nominal orbit length and distinct frames sampled in it."""
    step = Fraction(str(SIM_SPEED_STEPS[level])) * frame_count / len(CYCLE)
    period = frame_count * step.denominator // math.gcd(step.numerator, frame_count * step.denominator)
    coverage = len({int((tick * step) % frame_count) for tick in range(period)})
    return period, coverage


def ansi_grid(payload: str) -> tuple[tuple[pyte.screens.Char, ...], ...]:
    rows: list[tuple[pyte.screens.Char, ...]] = []
    for line in payload.splitlines()[:HEIGHT]:
        screen = pyte.Screen(WIDTH + 1, 1)
        pyte.Stream(screen).feed(line)
        rows.append(tuple(screen.buffer[0][column] for column in range(WIDTH)))
    blank = pyte.screens.Char(data=" ")
    while len(rows) < HEIGHT:
        rows.append(tuple(blank for _ in range(WIDTH)))
    return tuple(rows)


def color_energy(color: str) -> int:
    if color == "default" or len(color) != 6:
        return 0
    return max(int(color[index:index + 2], 16) for index in (0, 2, 4))


def colored(cell: pyte.screens.Char) -> bool:
    return max(color_energy(cell.fg), color_energy(cell.bg)) > 20


def cell_escape(cell: pyte.screens.Char) -> str:
    codes = ["0"]
    if cell.bold:
        codes.append("1")
    if cell.italics:
        codes.append("3")
    if cell.underscore:
        codes.append("4")
    if cell.blink:
        codes.append("5")
    if cell.reverse:
        codes.append("7")
    if cell.strikethrough:
        codes.append("9")
    if cell.fg != "default" and len(cell.fg) == 6:
        codes.append(
            f"38;2;{int(cell.fg[0:2], 16)};{int(cell.fg[2:4], 16)};{int(cell.fg[4:6], 16)}"
        )
    if cell.bg != "default" and len(cell.bg) == 6:
        codes.append(
            f"48;2;{int(cell.bg[0:2], 16)};{int(cell.bg[2:4], 16)};{int(cell.bg[4:6], 16)}"
        )
    return "\x1b[" + ";".join(codes) + "m" + cell.data


def load_leaf_overlays(frames: tuple[tuple[str, ...], ...]) -> tuple[str, ...]:
    missing = [
        LANDING_ANSI / f"leaf-phase-{phase:02d}.ansi"
        for phase in range(LANDING_PHASES)
        if not (LANDING_ANSI / f"leaf-phase-{phase:02d}.ansi").is_file()
    ]
    if missing:
        raise SystemExit("Missing landing overlays; run landing/build_landing.py")

    # Protect the union of every colored bird/heart cell so the leaf always
    # passes behind the approved subject at the feet and never paints over it.
    occupied: set[tuple[int, int]] = set()
    for frame_row in frames:
        for row, cells in enumerate(ansi_grid(frame_row[0])):
            for column, cell in enumerate(cells):
                if colored(cell):
                    occupied.add((row, column))

    overlays: list[str] = []
    for phase in range(LANDING_PHASES):
        payload = (LANDING_ANSI / f"leaf-phase-{phase:02d}.ansi").read_text(encoding="utf-8")
        pieces: list[str] = []
        for row, cells in enumerate(ansi_grid(payload)):
            for column, cell in enumerate(cells):
                if (row, column) not in occupied and colored(cell):
                    pieces.append(f"\x1b[{row + 1};{column + 1}H" + cell_escape(cell))
        overlays.append("".join(pieces) + "\x1b[0m")
    return tuple(overlays)


def chafa_frame(path: Path) -> str:
    command = (
        str(CHAFA),
        "--probe", "off",
        "--format", "symbols",
        "--colors", "full",
        "--bg", "000000",
        "--font-ratio", "3/8",
        "--size", f"{WIDTH}x{HEIGHT}",
        "--scale", "max",
        "--work", "9",
        "--symbols", "block+half+quad+braille+diagonal+border+space",
        str(path),
    )
    return subprocess.run(
        command,
        check=True,
        stdout=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    ).stdout.rstrip("\n")


def load_frames() -> tuple[tuple[tuple[str, ...], ...], tuple[dict[str, object], ...]]:
    if TRUE60_MANIFEST.is_file():
        metadata = tuple(json.loads(TRUE60_MANIFEST.read_text(encoding="utf-8")))
        cache_paths = tuple(
            tuple(
                TRUE60_CACHE / f"frame-{frame:02d}-heart-{heart:02d}.ansi"
                for heart in range(HEART_PHASES)
            )
            for frame in range(len(metadata))
        )
        missing_true60 = [str(path) for row in cache_paths for path in row if not path.is_file()]
        if missing_true60:
            raise SystemExit(
                "Missing true-60 runtime cache; run true60-cycle/build_runtime_cache.py. Missing:\n"
                + "\n".join(missing_true60[:10])
            )
        frames = tuple(
            tuple(path.read_text(encoding="utf-8").rstrip("\n") for path in row)
            for row in cache_paths
        )
        return frames, metadata

    missing = [str(path) for path in ANCHORS if not path.is_file()]
    if missing:
        raise SystemExit("Missing keyframe(s):\n" + "\n".join(missing))
    cache_paths = tuple(
        tuple(ANSI_CACHE / f"wing-{wing:02d}-heart-{heart:02d}.ansi" for heart in range(HEART_PHASES))
        for wing in range(len(ANCHORS))
    )
    missing_cache = [str(path) for row in cache_paths for path in row if not path.is_file()]
    if missing_cache:
        raise SystemExit(
            "Missing heart-spin cache; run build_heart_spin.sh. Missing:\n"
            + "\n".join(missing_cache)
        )
    anchor_frames = tuple(
        tuple(path.read_text(encoding="utf-8").rstrip("\n") for path in row)
        for row in cache_paths
    )
    frames = tuple(anchor_frames[anchor] for anchor in CYCLE)
    metadata = tuple(
        {
            "frame": slot,
            "position": f"{CYCLE[slot] + 1:.6f}",
            "direction": "down" if slot <= 8 else "up",
            "exact_anchor": True,
        }
        for slot in range(len(CYCLE))
    )
    return frames, metadata


def load_game_assets(
    frames: tuple[tuple[str, ...], ...],
    leaf_overlays: tuple[str, ...],
) -> tuple[
    tuple[tuple[tuple[pyte.screens.Char, ...], ...], ...],
    tuple[dict[tuple[int, int], pyte.screens.Char], ...],
    dict[tuple[int, int], pyte.screens.Char],
]:
    cache_paths = tuple(GAME_BIRD_CACHE / f"bird-{index:02d}.ansi" for index in range(len(frames)))
    missing = [path for path in cache_paths if not path.is_file()]
    if missing:
        raise SystemExit(
            "Missing movable game cache; run true60-cycle/build_game_cache.py. Missing:\n"
            + "\n".join(str(path) for path in missing[:10])
        )
    bird_frames = tuple(
        ansi_grid(path.read_text(encoding="utf-8"))
        for path in cache_paths
    )

    # The production 60x8 cache differs from its matching bird-only frame only
    # in the small heart region. Extract that verified terminal-scale sprite so
    # game hearts preserve the exact approved visual language at any position.
    raw_hearts: list[dict[tuple[int, int], pyte.screens.Char]] = []
    union: set[tuple[int, int]] = set()
    bird_zero = bird_frames[0]
    for phase in range(HEART_PHASES):
        combined = ansi_grid(frames[0][phase])
        cells: dict[tuple[int, int], pyte.screens.Char] = {}
        for row in range(HEIGHT):
            for column in range(WIDTH):
                cell = combined[row][column]
                if cell != bird_zero[row][column] and colored(cell):
                    cells[(column, row)] = cell
                    union.add((column, row))
        raw_hearts.append(cells)
    if not union:
        raise SystemExit("Could not extract game heart sprites from the verified runtime cache")
    min_x = min(column for column, _ in union)
    min_y = min(row for _, row in union)
    heart_sprites = tuple(
        {(column - min_x, row - min_y): cell for (column, row), cell in cells.items()}
        for cells in raw_hearts
    )

    # Normal animation overlays mask the union of every possible bird/heart
    # cell because they are concatenated after the subject. Game mode composes
    # layers explicitly (leaf, then bird), so use the complete source artwork;
    # otherwise that protective mask leaves conspicuous holes in bare leaves.
    _ = leaf_overlays  # Kept in the signature to share the validated loader.
    final_leaf = ansi_grid(
        (LANDING_ANSI / f"leaf-phase-{LANDING_PHASES - 1:02d}.ansi")
        .read_text(encoding="utf-8")
        .rstrip("\n")
    )
    leaf_cells = {
        (column, row): cell
        for row, cells in enumerate(final_leaf)
        for column, cell in enumerate(cells)
        if colored(cell)
    }
    return bird_frames, heart_sprites, leaf_cells


def split_mouse_events(
    payload: str,
) -> tuple[str, list[tuple[int, int, int, str]], str]:
    """Return ordinary keys, complete SGR mouse events and an incomplete tail."""
    events: list[tuple[int, int, int, str]] = []
    pieces: list[str] = []
    cursor = 0
    for match in MOUSE_EVENT_RE.finditer(payload):
        pieces.append(payload[cursor:match.start()])
        events.append((int(match.group(1)), int(match.group(2)), int(match.group(3)), match.group(4)))
        cursor = match.end()
    remainder = payload[cursor:]
    incomplete = remainder.rfind("\x1b[<")
    if incomplete >= 0:
        pieces.append(remainder[:incomplete])
        pending = remainder[incomplete:]
    else:
        pieces.append(remainder)
        pending = ""
    return "".join(pieces), events, pending


def split_enhanced_key_events(payload: str) -> tuple[str, list[tuple[str, int]], str]:
    """Decode kitty/CSI-u press, repeat and release events."""
    found: list[tuple[int, int, str, int]] = []
    for match in KITTY_UNICODE_KEY_RE.finditer(payload):
        codes = tuple(int(value) for value in match.group(1).split(":"))
        event = int(match.group(3) or "1")
        modifiers = int(match.group(2) or "1")
        shift_held = bool((modifiers - 1) & 1)
        associated = tuple(int(value) for value in match.group(4).split(":")) if match.group(4) else ()
        if associated and associated[0]:
            code = associated[0]
        elif shift_held and len(codes) > 1 and codes[1]:
            code = codes[1]
        else:
            code = codes[0]
        if code in KITTY_FUNCTIONAL_ARROWS:
            key = KITTY_FUNCTIONAL_ARROWS[code]
        elif code == 13:
            key = "enter"
        elif code == 32:
            key = "space"
        elif 0 <= code <= 0x10FFFF:
            key = chr(code)
            if shift_held and key.isalpha():
                key = key.upper()
            elif key.isalpha():
                key = key.lower()
        else:
            continue
        found.append((match.start(), match.end(), key, event))
    arrow_names = {"A": "up", "B": "down", "C": "right", "D": "left"}
    for match in KITTY_ARROW_KEY_RE.finditer(payload):
        found.append(
            (match.start(), match.end(), arrow_names[match.group(3)], int(match.group(2) or "1"))
        )
    found.sort()

    pieces: list[str] = []
    events: list[tuple[str, int]] = []
    cursor = 0
    for start, end, key, event in found:
        if start < cursor:
            continue
        pieces.append(payload[cursor:start])
        events.append((key, event))
        cursor = end
    remainder = payload[cursor:]
    incomplete = remainder.rfind("\x1b[")
    if incomplete >= 0:
        pieces.append(remainder[:incomplete])
        pending = remainder[incomplete:]
    else:
        pieces.append(remainder)
        pending = ""
    return "".join(pieces), events, pending


def draw_game(
    scene: dict[tuple[int, int], pyte.screens.Char],
    previous: dict[tuple[int, int], pyte.screens.Char],
    world: GameWorld,
    now: float,
    paused: bool,
    clear: bool = False,
    previous_chrome: tuple[str, str] | None = None,
) -> tuple[str, str]:
    pieces = ["\x1b[?25l"]
    if clear:
        pieces.append("\x1b[2J")
        previous = {}
    for row, column in sorted(set(previous) | set(scene)):
        old = previous.get((row, column))
        new = scene.get((row, column))
        if old == new:
            continue
        pieces.append(f"\x1b[{row + 1};{column + 1}H")
        pieces.append("\x1b[0m " if new is None else cell_escape(new))

    top, bottom = world.status(now)
    if paused:
        top += "  PAUSED"
    if not world.playable:
        top = f" GARDEN · terminal {world.width}×{world.height} · resize to at least 8×6"
        bottom = "g exit"
    top = top[:world.width]
    old_top = previous_chrome[0] if previous_chrome else ""
    if clear or top != old_top:
        pieces.extend((
            "\x1b[1;1H\x1b[0m\x1b[48;2;0;0;0m\x1b[38;2;0;220;255m",
            top + " " * max(0, len(old_top) - len(top)),
        ))
    bottom = bottom[:world.width]
    old_bottom = previous_chrome[1] if previous_chrome else ""
    if world.height > 1:
        if clear or bottom != old_bottom:
            pieces.extend((
                f"\x1b[{world.height};1H\x1b[0m\x1b[48;2;0;0;0m"
                "\x1b[38;2;155;155;170m",
                bottom + " " * max(0, len(old_bottom) - len(bottom)),
            ))
    pieces.append("\x1b[0m")
    os.write(sys.stdout.fileno(), "".join(pieces).encode("utf-8"))
    return top, bottom


def run_game_mode(
    fd: int,
    renderer: GameRenderer,
    rng: random.Random,
    should_continue: Callable[[], bool] = lambda: True,
) -> bool:
    """Run until G returns to animation mode or Q exits the application."""
    size = shutil.get_terminal_size()
    now = time.perf_counter()
    world = GameWorld(size.columns, size.lines, now, rng)
    swarm = SwarmManager(rng)
    settings = load_game_settings()
    world.nectar_limit_setting = int(settings["nectar_limit"])
    world.gravity_assist = bool(settings["gravity_assist"])
    world.calm = bool(settings["calm"])
    world.help_visible = bool(settings["help_visible"])
    world.extended_board = bool(settings["extended_board"])
    if bool(settings["auto_spawn"]):
        world.toggle_auto(now)
    if bool(settings["nectar_refill"]):
        world.toggle_nectar_refill(now)
    if bool(settings["player_mode"]):
        world.toggle_player(now)
    swarm.set_count(int(settings["flock_count"]))
    previous: dict[tuple[int, int], pyte.screens.Char] = {}
    previous_size = (size.columns, size.lines)
    last_update = now
    next_frame_at = now
    paused = bool(settings["paused"])
    pending = ""
    last_click: tuple[float, int, int] | None = None
    last_plant: tuple[float, int, int] | None = None
    held_directions: set[str] = set()
    bird_count_buffer = ""
    bird_count_deadline = 0.0
    first_draw = True
    previous_chrome: tuple[str, str] | None = None

    def persist() -> None:
        save_game_settings({
            "extended_board": world.extended_board,
            "flock_count": swarm.count,
            "nectar_limit": world.nectar_limit_setting,
            "nectar_refill": world.nectar_refill,
            "auto_spawn": world.auto_spawn,
            "player_mode": world.player_mode,
            "gravity_assist": world.gravity_assist,
            "calm": world.calm,
            "help_visible": world.help_visible,
            "paused": paused,
        })
    os.write(
        sys.stdout.fileno(),
        # Kitty progressive keyboard flags: disambiguation, event types,
        # alternate keys and all-key reporting. Supporting terminals now send
        # independent press/repeat/release events for genuine multi-key holds.
        b"\x1b[2J\x1b[H\x1b[?1000h\x1b[?1006h\x1b[>15u\x1b]0;Hummingbird Garden\x07",
    )
    try:
        while should_continue():
            now = time.perf_counter()
            size = shutil.get_terminal_size()
            current_size = (max(1, size.columns), max(1, size.lines))
            if current_size != previous_size:
                world.resize(*current_size, now)
                previous = {}
                previous_chrome = None
                previous_size = current_size
                first_draw = True
            dt = now - last_update
            last_update = now
            if paused:
                world.set_player_input(0, 0)
            else:
                world.set_player_input(
                    int("right" in held_directions) - int("left" in held_directions),
                    int("down" in held_directions) - int("up" in held_directions),
                )
            if not paused:
                swarm.prepare(world)
                world.update(now, dt)
                swarm.update(world, now, dt)
            if now >= next_frame_at:
                scene = renderer.scene(world, now)
                previous_chrome = draw_game(
                    scene, previous, world, now, paused,
                    clear=first_draw, previous_chrome=previous_chrome,
                )
                previous = scene
                first_draw = False
                interval = 1.0 / SIM_DISPLAY_FPS
                next_frame_at += interval
                if next_frame_at < now - interval:
                    next_frame_at = now + interval

            timeout = max(0.0, min(0.05, next_frame_at - time.perf_counter()))
            data = read_input(fd, 128, timeout, enhanced=True)
            if not data:
                continue
            keys, mouse_events, mouse_pending = split_mouse_events(
                pending + data.decode("utf-8", errors="ignore")
            )
            keys, enhanced_keys, key_pending = split_enhanced_key_events(keys)
            pending = mouse_pending or key_pending
            for key, event_type in enhanced_keys:
                normalized_key = key.lower()
                if normalized_key in {"w", "up"}:
                    direction = "up"
                elif normalized_key in {"s", "down"}:
                    direction = "down"
                elif normalized_key in {"a", "left"}:
                    direction = "left"
                elif normalized_key in {"d", "right"}:
                    direction = "right"
                else:
                    direction = ""
                if direction:
                    if event_type == 3:
                        held_directions.discard(direction)
                    else:
                        held_directions.add(direction)
                elif event_type == 1:
                    keys += "\r" if key == "enter" else (" " if key == "space" else key)
            event_now = time.perf_counter()
            for button, mouse_x, mouse_y, action in mouse_events:
                if action != "M" or (button & 3) != 0:
                    continue
                x, y = mouse_x - 1, mouse_y - 1
                world.set_reticle(x, y, event_now)
                if (
                    last_click is not None
                    and event_now - last_click[0] <= DOUBLE_CLICK_SECONDS
                    and abs(x - last_click[1]) <= 1
                    and abs(y - last_click[2]) <= 1
                ):
                    # Some terminal/OS accessibility paths expand one physical
                    # double-click into repeated press pairs. Collapse that burst
                    # so a single gesture always plants exactly one heart.
                    duplicate_burst = (
                        last_plant is not None
                        and event_now - last_plant[0] <= 0.60
                        and abs(x - last_plant[1]) <= 1
                        and abs(y - last_plant[2]) <= 1
                    )
                    if not duplicate_burst:
                        world.plant(x, y, event_now)
                        last_plant = (event_now, x, y)
                    last_click = None
                else:
                    last_click = (event_now, x, y)

            arrows = {
                "up": keys.count("\x1b[A"),
                "down": keys.count("\x1b[B"),
                "right": keys.count("\x1b[C"),
                "left": keys.count("\x1b[D"),
            }
            command_keys = ANSI_INPUT_SEQUENCE_RE.sub("", keys)
            lower = command_keys.lower()
            if "q" in lower:
                return False
            if "g" in lower:
                return True
            if " " in command_keys:
                paused = not paused
                world.say("Garden paused" if paused else "Garden resumed", event_now)
                persist()
            if "?" in command_keys:
                world.help_visible = not world.help_visible
                persist()
            if "o" in lower:
                world.toggle_auto(event_now)
                persist()
            if "p" in lower:
                world.toggle_player(event_now)
                persist()
            if "e" in lower:
                world.toggle_extended_board(event_now)
                persist()
            if "f" in lower:
                world.toggle_gravity_assist(event_now)
                persist()
            if "c" in lower:
                world.toggle_calm(event_now)
                persist()
            if "N" in command_keys:
                world.toggle_nectar_refill(event_now)
                persist()
            if "n" in command_keys:
                world.plant_random(event_now)
            if "x" in lower:
                world.clear_hearts(event_now)
            digits = "".join(character for character in command_keys if character in "0123456789")
            for digit in digits:
                if event_now > bird_count_deadline:
                    bird_count_buffer = ""
                # Once a completed count is followed by a fresh number, do not
                # turn e.g. 9 then 12 into 912 and silently clamp to the ceiling.
                bird_count_buffer = append_flock_digit(bird_count_buffer, digit)
                swarm.set_count(int(bird_count_buffer))
                bird_count_deadline = event_now + 0.70
                world.say(
                    f"Flock {swarm.count} · {swarm.count - 1} async companion"
                    + ("s" if swarm.count != 2 else ""),
                    event_now,
                    2.2,
                )
                persist()
            flock_delta = flock_delta_from_keys(command_keys)
            if flock_delta:
                bird_count_buffer = ""
                swarm.set_count(swarm.count + flock_delta)
                world.say(f"Flock {swarm.count}", event_now, 1.6)
                persist()
            nectar_delta = command_keys.count("]") - command_keys.count("[")
            nectar_delta += 5 * (command_keys.count("}") - command_keys.count("{"))
            if nectar_delta:
                world.adjust_nectar_limit(nectar_delta, event_now)
                persist()
            if "\r" in command_keys or "\n" in command_keys:
                world.plant(world.reticle_x, world.reticle_y, event_now)
            if world.player_mode:
                plain = command_keys.lower()
                dx = arrows["right"] - arrows["left"] + plain.count("d") - plain.count("a")
                dy = arrows["down"] - arrows["up"] + plain.count("s") - plain.count("w")
                world.control_player(max(-2, min(2, dx)), max(-2, min(2, dy)), event_now)
            else:
                if arrows["up"]:
                    world.move_reticle(0, -arrows["up"], event_now)
                if arrows["down"]:
                    world.move_reticle(0, arrows["down"], event_now)
                if arrows["right"]:
                    world.move_reticle(arrows["right"], 0, event_now)
                if arrows["left"]:
                    world.move_reticle(-arrows["left"], 0, event_now)
        return False
    finally:
        swarm.close()
        os.write(
            sys.stdout.fileno(),
            b"\x1b[<u\x1b[?1000l\x1b[?1006l\x1b[2J\x1b[H\x1b]0;Hummingbird TUI\x07",
        )


def phase(frame_info: dict[str, object]) -> str:
    position = float(frame_info["position"])
    if math.isclose(position, 1.0, abs_tol=1e-6):
        return "TOP"
    if math.isclose(position, 9.0, abs_tol=1e-6):
        return "BOTTOM"
    return "DOWNSTROKE" if frame_info["direction"] == "down" else "UPSTROKE"


def status_line(
    display_fps: float,
    motion_fps: float,
    actual_fps: float,
    anchor: int,
    frame_index: int,
    frame_count: int,
    phase_name: str,
    paused: bool,
    reversed_playback: bool,
    simulated: bool,
    sim_speed_level: int,
    show_phase: bool,
    random_mode: bool,
    dynamic_speed: bool,
) -> str:
    state = "PAUSED" if paused else (phase_name if show_phase else "WING")
    direction = "REV" if reversed_playback else "FWD"
    if simulated:
        modes = (" DYN" if dynamic_speed else " SNAP") + (" RND" if random_mode else "")
        return (
            f"  {state:<10} SIM30  act {actual_fps:>4.1f}  lvl {sim_speed_level}/9"
            f"  v {motion_fps:>5.1f} KF{anchor + 1:02d} F{frame_index + 1:02d}/{frame_count:02d}"
            f"{modes} {direction}"
        )
    return (
        f"  {state:<10} FPS {display_fps:>5.1f}  actual {actual_fps:>5.1f}"
        f"  KF {anchor + 1:02d}/09  frame {frame_index + 1:02d}/{frame_count:02d}  {direction}"
    )


def heart_status_line(
    heart_rps: float,
    heart_phase: int,
    heart_paused: bool,
    heart_reversed: bool,
    paused: bool,
    landing_state: str,
    perch_mode: str,
    landing_duration: float,
    flutter_active: bool,
    flutter_return_active: bool,
    flutter_level: int | None,
) -> str:
    state = "PAUSE" if paused or heart_paused else "SPIN"
    direction = "REV" if heart_reversed else "FWD"
    if landing_state == "landed":
        if perch_mode == "settling":
            leaf_state = "SETTLING"
        elif perch_mode == "resting":
            if flutter_active:
                leaf_state = f"FLUTTER L{flutter_level}"
            elif flutter_return_active:
                leaf_state = f"FOLDING L{flutter_level}"
            else:
                leaf_state = "REST" if flutter_level is None else f"REST last L{flutter_level}"
        else:
            leaf_state = "FLAPPING"
    else:
        leaf_state = landing_state.upper().replace("_", "-")
    return (
        f"  HEART {state} {heart_rps:>5.3f}rps {heart_phase + 1:02d}/{HEART_PHASES:02d} {direction}"
        f"   LEAF {leaf_state:<12} transit {landing_duration:>3.1f}s"
    )


def draw(
    frame: str,
    leaf_overlay: str,
    display_fps: float,
    motion_fps: float,
    actual_fps: float,
    anchor: int,
    frame_index: int,
    frame_count: int,
    phase_name: str,
    paused: bool,
    reversed_playback: bool,
    simulated: bool,
    heart_rps: float,
    heart_phase: int,
    heart_paused: bool,
    heart_reversed: bool,
    sim_speed_level: int,
    show_phase: bool,
    random_mode: bool,
    dynamic_speed: bool,
    landing_state: str,
    perch_mode: str,
    landing_duration: float,
    flutter_active: bool,
    flutter_return_active: bool,
    flutter_level: int | None,
    flutter_step: float,
) -> None:
    reported_level = flutter_level if flutter_active and flutter_level is not None else sim_speed_level
    reported_motion_fps = (
        SIM_DISPLAY_FPS * flutter_step
        if simulated and flutter_active
        else motion_fps
    )
    status = status_line(
        display_fps,
        reported_motion_fps,
        actual_fps,
        anchor,
        frame_index,
        frame_count,
        phase_name,
        paused,
        reversed_playback,
        simulated,
        reported_level,
        show_phase,
        random_mode,
        dynamic_speed,
    )
    heart_status = heart_status_line(
        heart_rps, heart_phase, heart_paused, heart_reversed, paused,
        landing_state, perch_mode, landing_duration, flutter_active,
        flutter_return_active, flutter_level,
    )
    controls_1 = "  1-9 speed  +/- nudge  r random  d ease  i phase  0 rest-land"
    controls_2 = "  g garden  l live-land  ,/. transit  [/] heart  h pause  v/w rev  q"
    glyph_rows = tuple(
        "  " + "   ".join(
            f"{index + 1:02d} {BIRD_GLYPHS[index]}"
            for index in range(start, min(start + 6, len(BIRD_GLYPHS)))
        )
        for start in range(0, len(BIRD_GLYPHS), 6)
    )
    payload = (
        "\x1b[H"
        + frame
        + leaf_overlay
        + "\x1b[14;1H\x1b[2K\x1b[38;2;0;210;255m"
        + status
        + "\x1b[15;1H\x1b[2K\x1b[38;2;150;150;165m"
        + heart_status
        + "\x1b[16;1H\x1b[2K\x1b[38;2;150;150;165m"
        + controls_1
        + "\x1b[17;1H\x1b[2K"
        + controls_2
        + "\x1b[18;1H\x1b[2K\x1b[38;2;255;190;60m"
        + "  ONE-GLYPH BIRDS — 01-18 text · 19-30 text-requested emoji"
        + "\x1b[19;1H\x1b[2K\x1b[38;2;190;190;205m"
        + glyph_rows[0]
        + "\x1b[20;1H\x1b[2K"
        + glyph_rows[1]
        + "\x1b[21;1H\x1b[2K"
        + glyph_rows[2]
        + "\x1b[22;1H\x1b[2K"
        + glyph_rows[3]
        + "\x1b[23;1H\x1b[2K"
        + glyph_rows[4]
        + "\x1b[24;1H\x1b[2K\x1b[38;2;110;110;125m"
        + "  VS15 requests monochrome; fallback color depends on the terminal font."
        + "\x1b[0m"
    )
    os.write(sys.stdout.fileno(), payload.encode("utf-8"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fps", type=float, default=60.0, help="initial target FPS (default: 60)")
    parser.add_argument(
        "--simulate-150-at-30",
        action="store_true",
        help="render at 30 FPS while advancing through the loop at 150 FPS",
    )
    parser.add_argument(
        "--heart-rps", type=float, default=1.0 / 3.0,
        help="initial heart rotations/sec (default: exactly 1/3)",
    )
    parser.add_argument(
        "--show-phase",
        action="store_true",
        help="show TOP/UPSTROKE/DOWNSTROKE/BOTTOM labels initially",
    )
    parser.add_argument(
        "--game",
        action="store_true",
        help="start directly in the responsive mouse-enabled garden game",
    )
    parser.add_argument("--check", action="store_true", help="validate and pre-render frames, then exit")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    normal_fps = min(240.0, max(1.0, args.fps))
    simulated = args.simulate_150_at_30
    sim_speed_level = 9
    current_speed_step = SIM_SPEED_STEPS[sim_speed_level]
    ramp_from_step = current_speed_step
    ramp_started_at: float | None = None
    dynamic_speed = True
    random_mode = False
    random_deadline = 0.0
    rng = random.Random()
    heart_rps = min(15.0, max(0.0, args.heart_rps))
    frames, frame_metadata = load_frames()
    leaf_overlays = load_leaf_overlays(frames)
    game_birds, game_hearts, game_leaf = load_game_assets(frames, leaf_overlays)
    game_renderer = GameRenderer(game_birds, game_hearts, game_leaf, colored)
    bottom_frame_index = next(
        index
        for index, info in enumerate(frame_metadata)
        if bool(info.get("exact_anchor"))
        and math.isclose(float(info["position"]), 9.0, abs_tol=1e-6)
    )

    if args.check:
        leaf_points = tuple(game_leaf)
        leaf_bbox = (
            min(x for x, _ in leaf_points),
            max(x for x, _ in leaf_points),
            min(y for _, y in leaf_points),
            max(y for _, y in leaf_points),
        )
        if len(game_leaf) != 36 or leaf_bbox != (5, 28, 8, 11):
            raise SystemExit(
                f"Incomplete/misaligned game leaf: {len(game_leaf)} cells, bbox {leaf_bbox}"
            )
        if any(not sprite for sprite in game_hearts):
            raise SystemExit("One or more extracted game heart phases is empty")
        slow_period, slow_coverage = sampler_profile(len(frames), 1)
        fast_period, fast_coverage = sampler_profile(len(frames), 9)
        fast_bank_count = math.ceil(len(frames) / fast_coverage)
        master_step = Fraction(str(SIM_SPEED_STEPS[9])) * len(frames) / len(CYCLE)
        banked_fast = {
            (int((tick * master_step) % len(frames)) + tick // fast_period) % len(frames)
            for tick in range(fast_period * fast_bank_count)
        }
        print(
            f"OK: {len(frames)} verified wing frames x {len(frames[0])} heart phases, "
            f"{WIDTH}x{HEIGHT}; level 1 visits {slow_coverage}/{len(frames)} in "
            f"{slow_period} displays; level 9 base orbit {fast_coverage}/{len(frames)}, "
            f"phase banks {len(banked_fast)}/{len(frames)}; "
            f"game cache {len(game_birds)} birds x {len(game_hearts)} hearts; "
            f"complete leaf {len(game_leaf)} cells bbox {leaf_bbox}"
        )
        return 0

    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise SystemExit("The player must run in an interactive terminal.")
    terminal_size = shutil.get_terminal_size()
    if not args.game and (terminal_size.columns < 78 or terminal_size.lines < 24):
        raise SystemExit("Terminal must be at least 78 columns by 24 rows.")

    fd = sys.stdin.fileno()
    terminal_input = None
    running = True

    def stop(_signum: int, _frame: object) -> None:
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    wing_position = 0.0
    speed_ticks = {level: 0 for level in SIM_SPEED_STEPS}
    paused = False
    reversed_playback = False
    heart_phase_position = 0.0
    heart_paused = False
    heart_reversed = False
    show_phase = args.show_phase
    actual_fps = 0.0
    frames_since_sample = 0
    sample_started = time.perf_counter()
    next_frame_at = sample_started
    landing_state = "flying"
    perch_mode = "continuous"
    landing_request_mode = "continuous"
    leaf_progress = 0.0
    landing_duration = 1.0
    leaf_motion_from = 0.0
    leaf_motion_target = 0.0
    leaf_motion_fraction = 0.0
    flutter_active = False
    flutter_return_active = False
    flutter_remaining = 0.0
    flutter_wait_remaining = rng.uniform(3.0, 5.0)
    flutter_step = SIM_SPEED_STEPS[5]
    flutter_level: int | None = None
    flutter_return_started_at = sample_started
    flutter_return_start_position = 0.0
    flutter_return_distance = 0.0
    flutter_return_direction = 1.0
    settle_started_at = sample_started
    settle_start_position = 0.0
    settle_distance = 0.0
    settle_direction = 1.0
    landing_updated_at = sample_started
    presets = {"1": 5.0, "2": 10.0, "3": 15.0, "4": 24.0, "5": 30.0,
               "6": 45.0, "7": 60.0, "8": 90.0, "9": 120.0}

    def display_fps() -> float:
        return SIM_DISPLAY_FPS if simulated else normal_fps

    def motion_fps() -> float:
        if simulated:
            return SIM_DISPLAY_FPS * current_speed_step
        return normal_fps

    def selected_frame_index() -> int:
        if (
            landing_state == "landed"
            and perch_mode == "resting"
            and not flutter_active
            and not flutter_return_active
        ):
            return bottom_frame_index
        base_index = int(wing_position) % len(frames)
        if not simulated or perch_mode == "settling" or flutter_return_active:
            return base_index
        period, coverage = sampler_profile(len(frames), sim_speed_level)
        bank_offset = 0 if coverage == len(frames) else speed_ticks[sim_speed_level] // period
        return (base_index + bank_offset) % len(frames)

    def frame_details(frame_index: int) -> tuple[int, str]:
        info = frame_metadata[frame_index]
        anchor = min(8, max(0, round(float(info["position"])) - 1))
        return anchor, phase(info)

    def update_speed(now: float) -> None:
        nonlocal current_speed_step, ramp_started_at
        if ramp_started_at is None:
            return
        progress = min(1.0, (now - ramp_started_at) / SPEED_RAMP_SECONDS)
        eased = progress * progress * (3.0 - 2.0 * progress)
        target_step = SIM_SPEED_STEPS[sim_speed_level]
        current_speed_step = ramp_from_step + (target_step - ramp_from_step) * eased
        if progress >= 1.0:
            current_speed_step = target_step
            ramp_started_at = None

    def set_speed_level(level: int, now: float) -> None:
        nonlocal sim_speed_level, current_speed_step, ramp_from_step, ramp_started_at
        update_speed(now)
        sim_speed_level = min(9, max(1, level))
        if dynamic_speed:
            ramp_from_step = current_speed_step
            ramp_started_at = now
        else:
            current_speed_step = SIM_SPEED_STEPS[sim_speed_level]
            ramp_started_at = None

    def choose_random_speed(now: float) -> None:
        nonlocal random_deadline
        next_level = random_speed_level(rng, sim_speed_level)
        set_speed_level(next_level, now)
        hold_seconds = random_hold_seconds(rng, next_level)
        transition_seconds = SPEED_RAMP_SECONDS if dynamic_speed else 0.0
        random_deadline = now + transition_seconds + hold_seconds

    def begin_settling(now: float) -> None:
        """Decelerate through the ordered master cycle and finish exactly at BOTTOM."""
        nonlocal perch_mode, flutter_active, flutter_return_active, settle_started_at
        nonlocal settle_start_position, settle_distance, settle_direction
        nonlocal random_mode, ramp_started_at
        perch_mode = "settling"
        flutter_active = False
        flutter_return_active = False
        random_mode = False
        ramp_started_at = None
        settle_started_at = now
        settle_start_position = wing_position % len(frames)
        settle_direction = -1.0 if reversed_playback else 1.0
        if settle_direction > 0:
            base_distance = (bottom_frame_index - settle_start_position) % len(frames)
        else:
            base_distance = (settle_start_position - bottom_frame_index) % len(frames)

        # An ease-out path starts at 2 * distance frames/sec. Choose a whole-cycle
        # extension that most closely matches the bird's current velocity, then
        # decelerate continuously to zero over exactly one second.
        if simulated:
            current_velocity = current_speed_step * len(frames) / len(CYCLE) * SIM_DISPLAY_FPS
        else:
            current_velocity = len(frames) / len(CYCLE) * normal_fps
        ideal_distance = current_velocity * SETTLE_SECONDS / 2.0
        extra_cycles = max(0, round((ideal_distance - base_distance) / len(frames)))
        settle_distance = base_distance + extra_cycles * len(frames)

    def enter_continuous_perch(now: float, enable_random: bool = False) -> None:
        nonlocal perch_mode, flutter_active, flutter_return_active, random_mode, random_deadline
        perch_mode = "continuous"
        flutter_active = False
        flutter_return_active = False
        if enable_random:
            random_mode = True
            choose_random_speed(now)
        random_deadline = max(random_deadline, now)

    def begin_leaf_motion(target: float, requested_mode: str | None = None) -> None:
        nonlocal landing_state, leaf_motion_from, leaf_motion_target, leaf_motion_fraction
        nonlocal flutter_active, flutter_return_active, landing_request_mode, perch_mode
        now = time.perf_counter()
        if requested_mode is not None:
            landing_request_mode = requested_mode
        if math.isclose(leaf_progress, target, abs_tol=1e-6):
            if (
                target == 1.0
                and landing_state == "landed"
                and landing_request_mode == "resting"
                and perch_mode in ("settling", "resting")
            ):
                return
            landing_state = "landed" if target == 1.0 else "flying"
            if target == 1.0:
                if landing_request_mode == "resting":
                    begin_settling(now)
                else:
                    enter_continuous_perch(now)
            else:
                perch_mode = "continuous"
            return
        leaf_motion_from = leaf_progress
        leaf_motion_target = target
        leaf_motion_fraction = 0.0
        flutter_active = False
        flutter_return_active = False
        if target == 0.0:
            # Takeoff immediately returns wing control to the retained live
            # fixed/random regime, beginning from whichever pose is on screen.
            perch_mode = "continuous"
        landing_state = "landing" if target == 1.0 else "taking_off"

    def update_landing(now: float) -> None:
        nonlocal landing_updated_at, leaf_progress, leaf_motion_fraction, landing_state
        nonlocal wing_position, flutter_active, flutter_remaining, flutter_wait_remaining
        nonlocal flutter_step, flutter_level, perch_mode, flutter_return_active
        nonlocal flutter_return_started_at, flutter_return_start_position
        nonlocal flutter_return_distance, flutter_return_direction
        elapsed = max(0.0, now - landing_updated_at)
        landing_updated_at = now
        if paused:
            return
        if landing_state in ("landing", "taking_off"):
            distance = max(0.001, abs(leaf_motion_target - leaf_motion_from))
            leaf_motion_fraction = min(
                1.0,
                leaf_motion_fraction + elapsed / (landing_duration * distance),
            )
            eased = leaf_motion_fraction * leaf_motion_fraction * (3.0 - 2.0 * leaf_motion_fraction)
            leaf_progress = leaf_motion_from + (leaf_motion_target - leaf_motion_from) * eased
            if leaf_motion_fraction >= 1.0:
                leaf_progress = leaf_motion_target
                if leaf_motion_target == 1.0:
                    landing_state = "landed"
                    if landing_request_mode == "resting":
                        begin_settling(now)
                    else:
                        enter_continuous_perch(now)
                else:
                    landing_state = "flying"
                    perch_mode = "continuous"
            return
        if landing_state != "landed":
            return
        if perch_mode == "settling":
            progress = min(1.0, (now - settle_started_at) / SETTLE_SECONDS)
            eased = 2.0 * progress - progress * progress
            wing_position = (
                settle_start_position + settle_direction * settle_distance * eased
            ) % len(frames)
            if progress >= 1.0:
                wing_position = float(bottom_frame_index)
                perch_mode = "resting"
                flutter_wait_remaining = rng.uniform(3.0, 5.0)
            return
        if perch_mode == "continuous":
            return
        if flutter_active:
            flutter_remaining -= elapsed
            if flutter_remaining <= 0.0:
                flutter_active = False
                flutter_return_active = True
                flutter_return_started_at = now
                flutter_return_start_position = wing_position % len(frames)
                flutter_return_direction = -1.0 if reversed_playback else 1.0
                if flutter_return_direction > 0:
                    flutter_return_distance = (
                        bottom_frame_index - flutter_return_start_position
                    ) % len(frames)
                else:
                    flutter_return_distance = (
                        flutter_return_start_position - bottom_frame_index
                    ) % len(frames)
        elif flutter_return_active:
            progress = min(
                1.0,
                (now - flutter_return_started_at) / FLUTTER_RETURN_SECONDS,
            )
            eased = 2.0 * progress - progress * progress
            wing_position = (
                flutter_return_start_position
                + flutter_return_direction * flutter_return_distance * eased
            ) % len(frames)
            if progress >= 1.0:
                flutter_return_active = False
                wing_position = float(bottom_frame_index)
                flutter_wait_remaining = rng.uniform(3.0, 5.0)
        else:
            flutter_wait_remaining -= elapsed
            if flutter_wait_remaining <= 0.0:
                flutter_active = True
                flutter_return_active = False
                flutter_remaining = rng.randrange(20, 101) / 100.0
                flutter_level = rng.choices(
                    REST_FLUTTER_SPEED_LEVELS,
                    REST_FLUTTER_SPEED_WEIGHTS,
                    k=1,
                )[0]
                flutter_step = SIM_SPEED_STEPS[flutter_level]

    try:
        terminal_input = start_input(fd)
        os.write(sys.stdout.fileno(), b"\x1b[?1049h\x1b[2J\x1b[?25l\x1b]0;Hummingbird TUI\x07")

        if args.game:
            running = run_game_mode(fd, game_renderer, rng, lambda: running)
            next_frame_at = time.perf_counter()
            sample_started = next_frame_at
            frames_since_sample = 0

        while running:
            now = time.perf_counter()
            update_speed(now)
            update_landing(now)
            continuous_wings = landing_state != "landed" or perch_mode == "continuous"
            if simulated and random_mode and continuous_wings and now >= random_deadline:
                choose_random_speed(now)
            due = not paused and now >= next_frame_at

            if due or frames_since_sample == 0:
                frame_index = selected_frame_index()
                anchor, phase_name = frame_details(frame_index)
                heart_phase = int(heart_phase_position) % HEART_PHASES
                leaf_phase = round(leaf_progress * (LANDING_PHASES - 1))
                draw(
                    frames[frame_index][heart_phase], leaf_overlays[leaf_phase],
                    display_fps(), motion_fps(), actual_fps,
                    anchor, frame_index, len(frames), phase_name,
                    paused, reversed_playback, simulated,
                    heart_rps, heart_phase, heart_paused, heart_reversed,
                    sim_speed_level, show_phase,
                    random_mode, dynamic_speed,
                    landing_state, perch_mode, landing_duration,
                    flutter_active, flutter_return_active, flutter_level, flutter_step,
                )
                if not paused:
                    wings_moving = continuous_wings or flutter_active
                    if wings_moving:
                        if landing_state == "landed" and perch_mode == "resting":
                            legacy_step = flutter_step
                        else:
                            legacy_step = current_speed_step if simulated else 1.0
                        phase_step = legacy_step * len(frames) / len(CYCLE)
                        signed_step = -phase_step if reversed_playback else phase_step
                        wing_position = (wing_position + signed_step) % len(frames)
                        if simulated and continuous_wings:
                            speed_ticks[sim_speed_level] += 1
                    if not heart_paused:
                        heart_step = heart_rps * HEART_PHASES / display_fps()
                        if heart_reversed:
                            heart_step = -heart_step
                        heart_phase_position = (heart_phase_position + heart_step) % HEART_PHASES
                    frames_since_sample += 1
                    interval = 1.0 / display_fps()
                    next_frame_at += interval
                    if next_frame_at < now - interval:
                        next_frame_at = now + interval

            elapsed = now - sample_started
            if elapsed >= 0.5:
                actual_fps = frames_since_sample / elapsed
                frames_since_sample = 0
                sample_started = now

            timeout = 0.05 if paused else max(0.0, min(0.05, next_frame_at - time.perf_counter()))
            data = read_input(fd, 32, timeout)
            if not data:
                continue
            text = data.decode("utf-8", errors="ignore")

            if "q" in text or "Q" in text:
                running = False
            elif " " in text:
                paused = not paused
                next_frame_at = time.perf_counter() + 1.0 / display_fps()
                frames_since_sample = 0
                sample_started = time.perf_counter()
            elif "w" in text or "W" in text:
                reversed_playback = not reversed_playback
            elif "h" in text or "H" in text:
                heart_paused = not heart_paused
            elif "v" in text or "V" in text:
                heart_reversed = not heart_reversed
            elif "g" in text or "G" in text:
                running = run_game_mode(fd, game_renderer, rng, lambda: running)
                next_frame_at = time.perf_counter()
                sample_started = next_frame_at
                frames_since_sample = 0
            elif "m" in text or "M" in text:
                simulated = not simulated
                random_mode = False
                set_speed_level(9, time.perf_counter())
                next_frame_at = time.perf_counter() + 1.0 / display_fps()
            elif "r" in text or "R" in text:
                if not simulated:
                    simulated = True
                now = time.perf_counter()
                if landing_state == "landed":
                    if perch_mode in ("resting", "settling"):
                        enter_continuous_perch(now, enable_random=True)
                    elif random_mode:
                        begin_settling(now)
                    else:
                        enter_continuous_perch(now, enable_random=True)
                else:
                    random_mode = not random_mode
                    if random_mode:
                        choose_random_speed(now)
                next_frame_at = time.perf_counter() + 1.0 / display_fps()
            elif "d" in text or "D" in text:
                dynamic_speed = not dynamic_speed
                if not dynamic_speed:
                    current_speed_step = SIM_SPEED_STEPS[sim_speed_level]
                    ramp_started_at = None
            elif "0" in text:
                begin_leaf_motion(1.0, requested_mode="resting")
            elif "l" in text or "L" in text:
                if landing_state in ("landed", "landing"):
                    begin_leaf_motion(0.0)
                else:
                    begin_leaf_motion(1.0, requested_mode="continuous")
            elif "." in text or ">" in text:
                landing_duration = max(0.2, landing_duration - 0.1)
            elif "," in text or "<" in text:
                landing_duration = min(3.0, landing_duration + 0.1)
            elif text in presets:
                if simulated:
                    random_mode = False
                    set_speed_level(int(text), time.perf_counter())
                    if landing_state == "landed":
                        enter_continuous_perch(time.perf_counter())
                else:
                    normal_fps = presets[text]
                next_frame_at = time.perf_counter() + 1.0 / display_fps()
            elif "+" in text or "=" in text or "\x1b[A" in text:
                if simulated:
                    random_mode = False
                    set_speed_level(sim_speed_level + 1, time.perf_counter())
                    if landing_state == "landed":
                        enter_continuous_perch(time.perf_counter())
                else:
                    normal_fps = min(240.0, normal_fps + 5.0)
                next_frame_at = time.perf_counter() + 1.0 / display_fps()
            elif "-" in text or "_" in text or "\x1b[B" in text:
                if simulated:
                    random_mode = False
                    set_speed_level(sim_speed_level - 1, time.perf_counter())
                    if landing_state == "landed":
                        enter_continuous_perch(time.perf_counter())
                else:
                    normal_fps = max(1.0, normal_fps - 5.0)
                next_frame_at = time.perf_counter() + 1.0 / display_fps()
            elif "}" in text:
                heart_rps = min(15.0, heart_rps + 0.25)
            elif "{" in text:
                heart_rps = max(0.0, heart_rps - 0.25)
            elif "]" in text:
                heart_rps = min(15.0, heart_rps + 0.05)
            elif "[" in text:
                heart_rps = max(0.0, heart_rps - 0.05)
            elif "i" in text or "I" in text:
                show_phase = not show_phase
            elif "\x1b[C" in text:
                wing_position = (int(wing_position) + 1) % len(frames)
                paused = True
                frames_since_sample = 0
            elif "\x1b[D" in text:
                wing_position = (int(wing_position) - 1) % len(frames)
                paused = True
                frames_since_sample = 0

            frame_index = selected_frame_index()
            anchor, phase_name = frame_details(frame_index)
            heart_phase = int(heart_phase_position) % HEART_PHASES
            leaf_phase = round(leaf_progress * (LANDING_PHASES - 1))
            draw(
                frames[frame_index][heart_phase], leaf_overlays[leaf_phase],
                display_fps(), motion_fps(), actual_fps,
                anchor, frame_index, len(frames), phase_name,
                paused, reversed_playback, simulated,
                heart_rps, heart_phase, heart_paused, heart_reversed,
                sim_speed_level, show_phase,
                random_mode, dynamic_speed,
                landing_state, perch_mode, landing_duration,
                flutter_active, flutter_return_active, flutter_level, flutter_step,
            )
    finally:
        os.write(sys.stdout.fileno(), b"\x1b[0m\x1b[?25h\x1b[?1049l")
        if terminal_input is not None:
            terminal_input.close()

    return 0


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    raise SystemExit(main())
