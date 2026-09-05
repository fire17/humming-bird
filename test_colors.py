"""Pure fixtures; no terminal/global settings changes or real-console claims."""
from pathlib import Path
import random
import re
import unittest
from unittest.mock import patch

import pyte
import humming_bird_assets
from hummingbird_colors import (
    COLOR_ENV, ColorEncoder, _indexed_rgb, rgb_to_256, select_color_mode,
)


class DetectionTests(unittest.TestCase):
    def test_environment_matrix(self):
        cases = (
            ({"TERM_PROGRAM": "Apple_Terminal", "TERM": "xterm-256color"}, "256"),
            ({"TERM_PROGRAM": "Apple_Terminal", "COLORTERM": "truecolor"}, "256"),
            ({"TERM_PROGRAM": "Apple_Terminal", "TERM": "screen", "TMUX": "session"}, "16"),
            ({"TERM_PROGRAM": "Apple_Terminal", "TERM": "tmux-direct", "TMUX": "session"}, "256"),
            ({"TERM_PROGRAM": "WezTerm", "TERM": "xterm-256color"}, "truecolor"),
            ({"TERM_PROGRAM": "iTerm.app"}, "truecolor"),
            ({"TERM_PROGRAM": "ghostty"}, "truecolor"),
            ({"TERM_PROGRAM": "WarpTerminal"}, "truecolor"),
            ({"TERM": "xterm-kitty"}, "truecolor"),
            ({"TERM": "foot"}, "truecolor"),
            ({"WT_SESSION": "windows-session"}, "truecolor"),
            ({"OS": "Windows_NT"}, "16"),
            ({"COLORTERM": "24bit"}, "truecolor"),
            ({"COLORTERM": "TRUECOLOR"}, "truecolor"),
            ({"TERM": "xterm-256color"}, "256"),
            ({"TERM": "xterm-direct"}, "truecolor"),
            ({"TERM": "tmux-direct", "TMUX": "session"}, "truecolor"),
            ({"TERM": "screen-256color", "COLORTERM": "truecolor", "TERM_PROGRAM": "WezTerm"}, "256"),
            ({"TERM": "screen", "STY": "session", "COLORTERM": "truecolor"}, "16"),
            ({"TERM": "xterm-256color", "TMUX": "session", "WT_SESSION": "inherited"}, "256"),
            ({"TERM": "linux"}, "16"),
            ({"TERM": "vt100"}, "16"),
            ({"TERM": "dumb", "COLORTERM": "truecolor"}, "16"),
            ({"TERM": "unknown"}, "16"),
            ({}, "16"),
        )
        for env, expected in cases:
            with self.subTest(env=env):
                original = dict(env)
                result = select_color_mode(env=env)
                self.assertEqual(result.mode, expected)
                self.assertTrue(result.reason)
                self.assertEqual(env, original)

    def test_override_precedence(self):
        env = {"TERM_PROGRAM": "Apple_Terminal", COLOR_ENV: "16"}
        self.assertEqual(select_color_mode(env=env).mode, "16")
        self.assertEqual(select_color_mode("truecolor", env).mode, "truecolor")
        self.assertEqual(select_color_mode("auto", env).mode, "256")
        with patch.dict("os.environ", {COLOR_ENV: "256"}, clear=True):
            self.assertEqual(select_color_mode().mode, "256")
        for mode in ("", "wrong", "0"):
            with self.assertRaises(ValueError):
                select_color_mode(mode, {})
        with self.assertRaises(ValueError):
            ColorEncoder("auto")


class PaletteTests(unittest.TestCase):
    def test_fixed_black_white_and_neon(self):
        for rgb, expected in (((0, 0, 0), 16), ((255, 255, 255), 231),
                              ((0, 255, 255), 51), ((255, 0, 255), 201),
                              ((128, 128, 128), 244)):
            self.assertEqual(rgb_to_256(*rgb), expected)

    def test_nearest_fixed_palette_property(self):
        rng = random.Random(431)
        palette = [_indexed_rgb(i) for i in range(16, 256)]
        for _ in range(512):
            rgb = tuple(rng.randrange(256) for _ in range(3))
            index = rgb_to_256(*rgb)
            distance = lambda candidate: sum((a - b) ** 2 for a, b in zip(rgb, candidate))
            self.assertGreaterEqual(index, 16)
            self.assertEqual(distance(_indexed_rgb(index)), min(map(distance, palette)))

    def test_invalid_rgb(self):
        for rgb in ((-1, 0, 0), (0, 256, 0), (0, 0, 999)):
            with self.assertRaises(ValueError):
                rgb_to_256(*rgb)


class EncodingTests(unittest.TestCase):
    def test_truecolor_is_byte_identical(self):
        payload = "\x1b[H\x1b[0;38;2;0;255;255;48;2;0;0;0m▀\x1b[0m"
        self.assertIs(ColorEncoder("truecolor").ansi(payload), payload)
        cell = pyte.screens.Char(data="▀", fg="00ffff", bg="000000", bold=True)
        self.assertEqual(ColorEncoder("truecolor").cell_escape(cell), "\x1b[0;1;38;2;0;255;255;48;2;0;0;0m▀")

    def test_cell_attributes_and_black_space_survive(self):
        cell = pyte.screens.Char(data=" ", fg="00ffff", bg="000000",
                                 bold=True, italics=True, underscore=True,
                                 blink=True, reverse=True, strikethrough=True)
        original = tuple(cell)
        self.assertEqual(ColorEncoder("256").cell_escape(cell), "\x1b[0;1;3;4;5;7;9;38;5;51;48;5;16m ")
        self.assertEqual(ColorEncoder("16").cell_escape(cell), "\x1b[0;1;3;4;5;7;9;96;40m ")
        self.assertEqual(tuple(cell), original)
        self.assertEqual(ColorEncoder("256").cell_escape(pyte.screens.Char(data="x")), "\x1b[0mx")

    def test_compound_and_indexed_sgr(self):
        payload = "\x1b[0;1;38;2;255;0;255;48;2;0;0;0;4m▀\x1b[39;49m"
        self.assertEqual(ColorEncoder("256").ansi(payload), "\x1b[0;1;38;5;201;48;5;16;4m▀\x1b[39;49m")
        self.assertEqual(ColorEncoder("16").ansi("\x1b[38;5;201;48;5;16m "), "\x1b[95;40m ")

    def test_colon_sgr(self):
        for color in ("38:2:255:0:255", "38:2::255:0:255", "38:2:0:255:0:255"):
            self.assertEqual(ColorEncoder("256").ansi(f"\x1b[1;{color};48:2::0:0:0m▀"), "\x1b[1;38;5;201;48;5;16m▀")
        self.assertEqual(ColorEncoder("16").ansi("\x1b[38:5:201m"), "\x1b[95m")

    def test_cursor_modes_and_osc_are_untouched(self):
        control = "\x1b[12;8H\x1b[2J\x1b[?25l\x1b[>1u\x1b]0;title\x07\x1b]8;;url\x1b\\link\x1b]8;;\x1b\\"
        self.assertEqual(ColorEncoder("256").ansi(control), control)
        for sequence in ("\x1bPtext\x1b[38;2;1;2;3m\x1b\\", "\x1b]title\x1b[38;2;1;2;3m\x07"):
            self.assertEqual(ColorEncoder("256").ansi(sequence), sequence)

    def test_malformed_and_unrelated_sgr_preserved(self):
        for sequence in ("\x1b[38;2;1;2m", "\x1b[48;2;999;0;0m", "\x1b[38;7;1;2;3m", "\x1b[4:3m", "\x1b[0m", "\x1b[m"):
            self.assertEqual(ColorEncoder("256").ansi(sequence), sequence)

    def test_cache_bounded_and_reused(self):
        before = rgb_to_256.cache_info()
        rgb_to_256(17, 31, 101)
        rgb_to_256(17, 31, 101)
        after = rgb_to_256.cache_info()
        self.assertGreater(after.hits, before.hits)
        self.assertLessEqual(after.currsize, after.maxsize)


class ApprovedAssetTests(unittest.TestCase):
    def test_runtime_assets_keep_glyphs_controls_and_truecolor_sources(self):
        root = Path(humming_bird_assets.__file__).parent
        paths = sorted((root / "true60-cycle/game-ansi").glob("*.ansi"))
        paths += sorted((root / "landing/ansi-overlays").glob("*.ansi"))
        paths += sorted((root / "true60-cycle/heart-spin/ansi").glob("*.ansi"))
        self.assertEqual(len(paths), 556)
        sgr = re.compile(r"\x1b\[[0-9;:]*m")
        for path in paths:
            payload = path.read_text(encoding="utf-8")
            with self.subTest(asset=path.name):
                self.assertIs(ColorEncoder("truecolor").ansi(payload), payload)
                for mode in ("256", "16"):
                    adapted = ColorEncoder(mode).ansi(payload)
                    self.assertEqual(sgr.sub("", adapted), sgr.sub("", payload))
                    self.assertNotRegex(adapted, r"(?:38|48);2;")
                    if mode == "16":
                        self.assertNotRegex(adapted, r"(?:38|48);5;")
                # Parsing stays RGB. Adapting for display must not mutate input.
                self.assertEqual(path.read_text(encoding="utf-8"), payload)

    def test_palette_output_decodes_with_same_cell_geometry(self):
        root = Path(humming_bird_assets.__file__).parent
        payload = (root / "true60-cycle/game-ansi/bird-00.ansi").read_text(encoding="utf-8")
        source = pyte.Screen(33, 12)
        indexed = pyte.Screen(33, 12)
        pyte.Stream(source).feed(payload.replace("\n", "\r\n"))
        pyte.Stream(indexed).feed(ColorEncoder("256").ansi(payload).replace("\n", "\r\n"))
        for row in range(12):
            for col in range(32):
                before, after = source.buffer[row][col], indexed.buffer[row][col]
                self.assertEqual(before.data, after.data)
                for channel in ("fg", "bg"):
                    rgb = getattr(before, channel)
                    if re.fullmatch(r"[0-9a-f]{6}", rgb):
                        values = tuple(int(rgb[i:i + 2], 16) for i in (0, 2, 4))
                        expected = "".join(f"{v:02x}" for v in _indexed_rgb(rgb_to_256(*values)))
                        self.assertEqual(getattr(after, channel), expected)


if __name__ == "__main__":
    unittest.main()
