"""Late-output terminal color adaptation; never quantize compositing inputs.

No probing, curses, console API, palette mutation, or platform-specific imports.
Environment detection is a heuristic; an explicit application override wins.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import os
import re
from typing import Mapping

COLOR_MODES = ("auto", "truecolor", "256", "16")
COLOR_ENV = "HUMMINGBIRD_COLOR_MODE"


@dataclass(frozen=True)
class ColorSupport:
    mode: str
    reason: str


def select_color_mode(
    requested: str | None = None,
    env: Mapping[str, str] | None = None,
) -> ColorSupport:
    """Select once at startup; CLI value takes precedence over application env.

    Inherited COLORTERM/TERM_PROGRAM cannot establish the capabilities of a
    multiplexer in between. A direct-color TERM explicitly advertises that hop.
    An unknown terminal gets basic ANSI colors, not an assumption of RGB.
    This does not establish that the stream is a TTY or supports cursor movement.
    """
    environment = os.environ if env is None else env
    mode = requested if requested is not None else environment.get(COLOR_ENV, "auto")
    mode = mode.strip().lower()
    if mode not in COLOR_MODES:
        raise ValueError(f"Invalid color mode {mode!r}; choose {', '.join(COLOR_MODES)}")
    if mode != "auto":
        return ColorSupport(mode, "explicit application color override")

    term = environment.get("TERM", "").lower()
    program = environment.get("TERM_PROGRAM", "").lower()
    colorterm = environment.get("COLORTERM", "").lower()
    multiplexed = bool(environment.get("TMUX") or environment.get("STY")) or term.startswith(("screen", "tmux"))
    # Terminal.app is a known counterexample to trusting a stale COLORTERM.
    if program == "apple_terminal":
        mode = "16" if multiplexed and "256color" not in term and not term.endswith(("-direct", "-truecolor", "-24bit")) else "256"
        return ColorSupport(mode, "Apple Terminal: use indexed colors, bounded by the multiplexer")
    if term.endswith(("-direct", "-truecolor", "-24bit")):
        return ColorSupport("truecolor", "TERM explicitly advertises direct color")
    if multiplexed:
        mode = "256" if "256color" in term else "16"
        return ColorSupport(mode, "multiplexer: use its TERM, not inherited outer-terminal hints")
    if term in {"dumb", "unknown"}:
        return ColorSupport("16", "limited TERM; ANSI cursor support must be checked separately")
    if colorterm in {"truecolor", "24bit"}:
        return ColorSupport("truecolor", "COLORTERM advertises RGB")
    if program in {"wezterm", "iterm.app", "ghostty", "kitty", "alacritty", "vscode", "warpterminal"}:
        return ColorSupport("truecolor", "recognized direct-color terminal")
    if environment.get("WT_SESSION"):
        return ColorSupport("truecolor", "Windows Terminal session")
    if term in {"xterm-kitty", "xterm-ghostty", "wezterm", "alacritty", "foot", "foot-extra"}:
        return ColorSupport("truecolor", "recognized direct-color TERM")
    if "256color" in term:
        return ColorSupport("256", "TERM advertises 256 colors")
    return ColorSupport("16", "no reliable extended-color advertisement")


_CUBE = (0, 95, 135, 175, 215, 255)
_BASIC = (
    (0, 0, 0), (128, 0, 0), (0, 128, 0), (128, 128, 0),
    (0, 0, 128), (128, 0, 128), (0, 128, 128), (192, 192, 192),
    (128, 128, 128), (255, 0, 0), (0, 255, 0), (255, 255, 0),
    (0, 0, 255), (255, 0, 255), (0, 255, 255), (255, 255, 255),
)


def _distance(a: tuple[int, int, int], b: tuple[int, int, int]) -> int:
    return sum((x - y) ** 2 for x, y in zip(a, b))


@lru_cache(maxsize=16384)
def rgb_to_256(red: int, green: int, blue: int) -> int:
    """Nearest fixed xterm cube/gray entry (never theme-dependent entries 0–15)."""
    rgb = (red, green, blue)
    if any(not 0 <= channel <= 255 for channel in rgb):
        raise ValueError("RGB channels must be in 0..255")
    cube = tuple(min(range(6), key=lambda i: abs(_CUBE[i] - channel)) for channel in rgb)
    cube_rgb = tuple(_CUBE[i] for i in cube)
    cube_index = 16 + 36 * cube[0] + 6 * cube[1] + cube[2]
    # Minimize squared distance: the closest gray is nearest the channel mean.
    gray = min(23, max(0, round((sum(rgb) / 3 - 8) / 10)))
    gray_rgb = (8 + 10 * gray,) * 3
    return 232 + gray if _distance(rgb, gray_rgb) < _distance(rgb, cube_rgb) else cube_index


@lru_cache(maxsize=16384)
def _rgb_to_16(red: int, green: int, blue: int) -> int:
    return min(range(16), key=lambda i: _distance((red, green, blue), _BASIC[i]))


def _indexed_rgb(index: int) -> tuple[int, int, int]:
    if index < 16:
        return _BASIC[index]
    if index >= 232:
        return (8 + 10 * (index - 232),) * 3
    value = index - 16
    return (_CUBE[value // 36], _CUBE[value // 6 % 6], _CUBE[value % 6])


@lru_cache(maxsize=16384)
def _color_code(mode: str, rgb: tuple[int, int, int], background: bool) -> str:
    if mode == "truecolor":
        return f"{48 if background else 38};2;{rgb[0]};{rgb[1]};{rgb[2]}"
    if mode == "256":
        return f"{48 if background else 38};5;{rgb_to_256(*rgb)}"
    index = _rgb_to_16(*rgb)
    return str((40 if background else 30) + index if index < 8 else (100 if background else 90) + index - 8)


_HEX = re.compile(r"[0-9a-fA-F]{6}\Z")
_SGR = re.compile(r"\x1b\[([0-9;:]*)m")
# Protect OSC/DCS/APC/PM strings: their content is not rendered cell styling.
_OUTPUT_TOKEN = re.compile(r"\x1b(?:\](?:[^\x07\x1b]|\x1b(?!\\))*(?:\x07|\x1b\\)|[P_^].*?\x1b\\|\[[0-9;:]*m)", re.DOTALL)


@lru_cache(maxsize=8192)
def _adapt_sgr(mode: str, sequence: str) -> str:
    match = _SGR.fullmatch(sequence)
    if match is None:
        return sequence
    fields = match[1].split(";")
    converted: list[str] = []
    index = 0
    while index < len(fields):
        field = fields[index]
        if ":" in field:
            parts = field.split(":")
            if parts[0] in {"38", "48"}:
                values = parts[2:]
                if parts[1] == "2" and len(values) == 4 and values[0] in {"", "0"}:
                    values = values[1:]
                if parts[1] == "2" and len(values) == 3 and all(v.isdecimal() and 0 <= int(v) <= 255 for v in values):
                    converted.append(_color_code(mode, tuple(map(int, values)), parts[0] == "48"))
                    index += 1
                    continue
                if parts[1] == "5" and len(values) == 1 and values[0].isdecimal() and 0 <= int(values[0]) <= 255:
                    color = int(values[0])
                    converted.append(_color_code(mode, _indexed_rgb(color), parts[0] == "48") if mode == "16" else f"{parts[0]};5;{color}")
                    index += 1
                    continue
        if field in {"38", "48"} and index + 1 < len(fields):
            kind = fields[index + 1]
            count = 3 if kind == "2" else 1 if kind == "5" else 0
            values = fields[index + 2:index + 2 + count]
            if count and len(values) == count and all(v.isdecimal() and 0 <= int(v) <= 255 for v in values):
                rgb = tuple(map(int, values)) if kind == "2" else _indexed_rgb(int(values[0]))
                converted.append(_color_code(mode, rgb, field == "48") if kind == "2" or mode == "16" else ";".join(fields[index:index + 2 + count]))
                index += 2 + count
                continue
            # Malformed/unsupported extended color: do not reinterpret its tail
            # as unrelated attributes/colors. Preserve the entire SGR unchanged.
            return sequence
        converted.append(field)
        index += 1
    return "\x1b[" + ";".join(converted) + "m"


@lru_cache(maxsize=8192)
def _cell_style(mode: str, fg: str, bg: str, attributes: tuple[bool, ...]) -> str:
    codes = ["0"]
    codes.extend(str(code) for code, enabled in zip((1, 3, 4, 5, 7, 9), attributes) if enabled)
    for color, background in ((fg, False), (bg, True)):
        if _HEX.fullmatch(color):
            codes.append(_color_code(mode, tuple(int(color[i:i + 2], 16) for i in (0, 2, 4)), background))
    return "\x1b[" + ";".join(codes) + "m"


class ColorEncoder:
    """One resolved output mode; cached styles, no mutation of source cells.

    cell_escape() replaces the TUI's current encoder. ansi() adapts cached studio
    frames and HUD strings; use it only after RGB asset parsing/compositing.
    The truecolor ansi() path returns the original string without scanning it.
    """

    def __init__(self, mode: str):
        if mode not in COLOR_MODES[1:]:
            raise ValueError("ColorEncoder needs a resolved truecolor, 256, or 16 mode")
        self.mode = mode

    def cell_escape(self, cell) -> str:
        attributes = (cell.bold, cell.italics, cell.underscore, cell.blink, cell.reverse, cell.strikethrough)
        return _cell_style(self.mode, cell.fg, cell.bg, attributes) + cell.data

    def ansi(self, payload: str) -> str:
        if self.mode == "truecolor":
            return payload
        return _OUTPUT_TOKEN.sub(lambda match: _adapt_sgr(self.mode, match[0]), payload)
