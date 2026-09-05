"""Packaging regression checks; do not open a GUI or change user configuration."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent


class MacLauncherTests(unittest.TestCase):
    @unittest.skipIf(os.name == "nt", "POSIX shell packaging")
    def test_shell_syntax(self):
        subprocess.run(["/bin/sh", "-n", str(ROOT / "packaging/launch-wezterm.sh")], check=True)

    def test_launcher_does_not_fall_back_to_apple_terminal(self):
        launcher = (ROOT / "packaging/macos-launcher.applescript").read_text()
        self.assertNotIn('tell application "Terminal"', launcher)
        self.assertIn("launch-wezterm.sh", launcher)
        self.assertIn("quoted form", launcher)

    def test_app_profile_is_isolated_and_opaque(self):
        launcher = (ROOT / "packaging/launch-wezterm.sh").read_text()
        profile = (ROOT / "packaging/humming-bird-wezterm.lua").read_text()
        self.assertIn('--config-file "$config_file"', launcher)
        self.assertIn("--always-new-process", launcher)
        self.assertIn("enable_kitty_keyboard = true", profile)
        self.assertIn("background = '#000000'", profile)
        self.assertIn("window_background_opacity = 1.0", profile)
        self.assertIn("check_for_updates = false", profile)

    @unittest.skipUnless(sys.platform == "darwin", "AppleScript compiler")
    def test_applescript_compiles_at_a_path_with_spaces(self):
        with tempfile.TemporaryDirectory(prefix="humming bird launcher ") as directory:
            app = Path(directory) / "Humming Bird.app"
            subprocess.run(["osacompile", "-o", str(app),
                            str(ROOT / "packaging/macos-launcher.applescript")], check=True)
            self.assertTrue((app / "Contents/Resources/Scripts/main.scpt").is_file())
