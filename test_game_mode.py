#!/usr/bin/env python3

from __future__ import annotations

import math
import random
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from hummingbird_brain import AutonomousBirdBrain, nectar_capture_time_scale
from hummingbird_game import (
    GameRenderer, GameWorld, REST_LEVELS, RemoteBird, TargetMotionWatchdog,
    composite_bird_cell, hue_shift_color,
)
from pyte.screens import Char
from hummingbird_swarm import (
    MAX_FLOCK_SIZE, SwarmManager, append_flock_digit, bounded_flock_count,
)
from hummingbird_tui import (
    ANSI_INPUT_SEQUENCE_RE,
    flock_delta_from_keys,
    load_game_settings,
    save_game_settings,
    split_enhanced_key_events,
)


class GameWorldTests(unittest.TestCase):
    def test_extended_camera_tracks_four_directions_and_stops_on_reverse(self) -> None:
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, -1)):
            world = GameWorld(100, 36, 0.0, random.Random(120))
            world.toggle_extended_board(0.0)
            world.toggle_player(0.0)
            world.set_player_input(dx, dy)
            initial_x, initial_y = world._bird_center()
            for tick in range(240):
                world.update(tick / 30, 1 / 30)
                sx, sy = world.world_to_screen(*world._bird_center())
                self.assertTrue(0 <= sx < world.width, (dx, dy, sx))
                self.assertTrue(1 <= sy < world.height - 1, (dx, dy, sy))
            if dx:
                self.assertGreater(dx * world.camera_x, world.width)
                self.assertGreater(dx * (world._bird_center()[0] - initial_x), world.width)
            if dy:
                self.assertGreater(dy * world.camera_y, world.height)
                self.assertGreater(dy * (world._bird_center()[1] - initial_y), world.height)
            camera = (world.camera_x, world.camera_y)
            world.velocity_x, world.velocity_y = -dx * 10, -dy * 10
            world.update_camera(1 / 30)
            self.assertEqual((world.camera_x, world.camera_y), camera)

    def test_extended_plant_render_resize_preserve_world_coordinates(self) -> None:
        world = GameWorld(100, 36, 0.0, random.Random(121))
        world.toggle_extended_board(0.0)
        world.camera_x, world.camera_y = -123.25, 70.75
        world.bird_x, world.bird_y = -90.0, 81.0
        world.plant(45, 12, 0.1)
        heart = world.hearts[0]
        self.assertEqual(world.world_to_screen(heart.x + 2, heart.y + 1), (45, 12))
        pose = (world.bird_x, world.bird_y, heart.x, heart.y, tuple(world.leaves))
        world.resize(70, 25, 0.2)
        self.assertEqual((world.bird_x, world.bird_y, heart.x, heart.y, tuple(world.leaves)), pose)
        sx, sy = world.world_to_screen(*world._bird_center())
        self.assertTrue(0 <= sx < 70 and 1 <= sy < 24)

    def test_shared_brain_can_reach_nectar_outside_original_board(self) -> None:
        for target_x, target_y in ((240, 80), (-200, -70)):
            brain = AutonomousBirdBrain(2, random.Random(122), initialized=True)
            result = None
            for tick in range(1800):
                result = brain.step(
                    now=tick / 30, dt=1 / 30, width=100, compact=False,
                    play_top=2, play_bottom=34, count=2, primary_leaf=0,
                    hearts=((1, target_x, target_y),), leaves=(), assigned_target=1,
                    neighbors=(), extended_board=True,
                )
                if result.collected_id == 1:
                    break
            self.assertEqual(result.collected_id, 1)

    def test_nectar_capture_time_uses_requested_density_formula(self) -> None:
        self.assertAlmostEqual(nectar_capture_time_scale(50, 10), 1.0 / math.sqrt(5.0))
        self.assertAlmostEqual(nectar_capture_time_scale(9, 9), 1.0)
        self.assertAlmostEqual(nectar_capture_time_scale(1, 9), 3.0)

    def test_scene_never_draws_into_static_chrome_rows(self) -> None:
        scene: dict[tuple[int, int], Char] = {}
        cell = Char(data="█", fg="00ff00")
        GameRenderer._put(scene, 2, 0, cell, 20, 10)
        GameRenderer._put(scene, 2, 9, cell, 20, 10)
        GameRenderer._put(scene, 2, 1, cell, 20, 10)
        self.assertNotIn((0, 2), scene)
        self.assertNotIn((9, 2), scene)
        self.assertEqual(scene[(1, 2)], cell)

    def test_bird_overlap_color_keys_black_cell_channels(self) -> None:
        lower = Char(data="█", fg="00dd88", bg="001122")
        foreground_bird = Char(data="▄", fg="ff2299", bg="000000")
        background_bird = Char(data="▊", fg="000000", bg="ffaa00")
        self.assertEqual(composite_bird_cell(foreground_bird, lower).bg, "00dd88")
        self.assertEqual(composite_bird_cell(background_bird, lower).fg, "00dd88")
        opaque = Char(data="▄", fg="ff2299", bg="442288")
        self.assertEqual(composite_bird_cell(opaque, lower), opaque)
        self.assertEqual(composite_bird_cell(foreground_bird, None), foreground_bird)

    def test_bird_overlap_inherits_only_the_covered_glyph_region(self) -> None:
        lower_top = Char(data="▔", fg="00dd88", bg="000000")
        lower_bottom = Char(data="▁", fg="00dd88", bg="000000")
        upper_top = Char(data="▔", fg="ff2299", bg="000000")
        self.assertEqual(composite_bird_cell(upper_top, lower_top).bg, "000000")
        self.assertEqual(composite_bird_cell(upper_top, lower_bottom).bg, "00dd88")

    def test_primary_and_worker_brains_have_identical_motion(self) -> None:
        first = AutonomousBirdBrain(
            1, random.Random(91), x=20.0, y=5.0,
            wing_position=7.0, initialized=True,
        )
        second = AutonomousBirdBrain(
            1, random.Random(91), x=20.0, y=5.0,
            wing_position=7.0, initialized=True,
        )
        inputs = dict(
            now=1.0, dt=1.0 / 30.0, width=120, compact=False,
            play_top=2, play_bottom=38, count=4, primary_leaf=0,
            hearts=((3, 92.0, 12.0),), leaves=((10.0, 27.0),),
            assigned_target=3,
            neighbors=((1, 20.0, 5.0, 0.0, 0.0), (2, 24.0, 6.0, -1.0, 0.5)),
            calm=False,
        )
        self.assertEqual(first.step(**inputs), second.step(**inputs))

    def test_companion_collection_does_not_reset_primary_ai(self) -> None:
        world = GameWorld(120, 40, 0.0, random.Random(92))
        world.plant(20, 8, 0.0)
        world.plant(90, 12, 0.0)
        primary_heart, companion_heart = world.hearts
        world.state = "flying"
        world.target_id = primary_heart.ident
        world.assigned_target_id = primary_heart.ident
        self.assertTrue(world.collect_companion(companion_heart.ident, 2, 0.5))
        self.assertEqual(world.state, "flying")
        self.assertEqual(world.target_id, primary_heart.ident)
        self.assertEqual(world.assigned_target_id, primary_heart.ident)

    def test_nectar_limit_is_adjustable_and_responsive(self) -> None:
        world = GameWorld(240, 60, 0.0, random.Random(51))
        self.assertEqual(world.heart_limit, 50)
        world.adjust_nectar_limit(8, 0.1)
        self.assertEqual(world.heart_limit, 58)
        for index in range(58):
            self.assertTrue(world.plant(10 + index * 5, 8, 0.2 + index * 0.01))
        self.assertEqual(len(world.hearts), 58)

    def test_flock_count_accepts_multi_digit_range(self) -> None:
        self.assertEqual(bounded_flock_count(12), 12)
        self.assertEqual(bounded_flock_count(999), MAX_FLOCK_SIZE)
        self.assertEqual(bounded_flock_count(0), 1)
        self.assertEqual(append_flock_digit("", "1"), "1")
        self.assertEqual(append_flock_digit("1", "2"), "12")
        self.assertEqual(append_flock_digit("9", "1"), "1")

    def test_target_watchdog_detects_stationary_and_nonprogressing_birds(self) -> None:
        watchdog = TargetMotionWatchdog()
        self.assertFalse(watchdog.observe(7, 10.0, 5.0, 12.0, 0.0, 3.4))
        self.assertTrue(watchdog.observe(7, 10.0, 5.0, 12.0, 0.5, 3.4))
        self.assertFalse(watchdog.observe(8, 10.0, 5.0, 12.0, 0.6, 3.4))
        self.assertFalse(watchdog.observe(8, 12.0, 5.0, 12.0, 1.1, 3.4))
        self.assertFalse(watchdog.observe(8, 14.0, 5.0, 12.0, 1.6, 3.4))
        self.assertTrue(watchdog.observe(8, 16.0, 5.0, 12.0, 2.1, 3.4))

    def test_primary_ai_gets_same_recovery_window_as_companions(self) -> None:
        world = GameWorld(140, 40, 0.0, random.Random(58))
        world.plant(110, 10, 0.0)
        world.target_id = world.hearts[0].ident
        world.assigned_target_id = world.target_id
        world.state = "flying"
        world.update(0.1, 0.0)
        world.update(0.6, 0.0)
        self.assertGreater(world.recovery_until, 0.6)
        self.assertGreater(math.hypot(world.velocity_x, world.velocity_y), 5.0)
        self.assertEqual(world.wing_level, 7)

    def test_multiple_hearts_and_responsive_limits(self) -> None:
        world = GameWorld(100, 30, 0.0, random.Random(1))
        for index in range(6):
            self.assertTrue(world.plant(20 + index * 5, 8 + index, index * 0.01))
        self.assertEqual(len(world.hearts), 6)
        world.resize(24, 10, 1.0)
        self.assertTrue(world.compact)
        self.assertTrue(all(0 <= heart.x < 24 for heart in world.hearts))
        self.assertTrue(all(world.play_top <= heart.y <= world.play_bottom for heart in world.hearts))

    def test_heart_placement_wakes_landed_bird(self) -> None:
        world = GameWorld(80, 24, 0.0, random.Random(2))
        world.state = "landed"
        world.plant(60, 7, 1.0)
        self.assertEqual(world.state, "taking_off")

    def test_resize_keeps_every_perched_state_attached(self) -> None:
        for state in ("landed", "settling", "rest_flutter", "rest_folding"):
            world = GameWorld(80, 24, 0.0, random.Random(2))
            world.state = state
            world.target_leaf = len(world.leaves) - 1
            world.resize(120, 34, 1.0)
            perch = world.leaves[world.target_leaf]
            self.assertEqual((world.bird_x, world.bird_y), (float(perch.x), float(perch.y)))
            self.assertEqual(perch.y + 11, world.play_bottom)

    def test_full_collection_returns_to_leaf_and_rests(self) -> None:
        world = GameWorld(80, 24, 0.0, random.Random(3))
        world.plant(48, 8, 0.0)
        for tick in range(1, 5000):
            now = tick / 30.0
            world.update(now, 1.0 / 30.0)
            if world.state == "landed" and not world.hearts:
                break
        self.assertFalse(world.hearts)
        self.assertEqual(world.collected, 1)
        self.assertEqual(world.state, "landed")
        self.assertEqual(int(world.wing_position), 30)

    def test_resting_flutter_band(self) -> None:
        seen: set[int] = set()
        for seed in range(400):
            world = GameWorld(80, 24, 0.0, random.Random(seed))
            world.state = "landed"
            world.state_deadline = 0.0
            world.update(1.0, 1.0 / 30.0)
            self.assertIn(world.flutter_level, REST_LEVELS)
            seen.add(world.flutter_level or 0)
        self.assertEqual(seen, set(REST_LEVELS))

    def test_tiny_terminal_is_safe(self) -> None:
        world = GameWorld(4, 3, 0.0, random.Random(4))
        self.assertFalse(world.playable)
        world.update(1.0, 1.0)
        self.assertFalse(world.plant(1, 1, 1.0))

    def test_auto_mode_spawns_bounded_dynamic_wave(self) -> None:
        world = GameWorld(100, 30, 0.0, random.Random(12))
        world.toggle_auto(0.0)
        world.update(0.36, 1.0 / 30.0)
        self.assertTrue(world.auto_spawn)
        self.assertEqual(world.wave_number, 1)
        self.assertGreaterEqual(len(world.hearts), 1)
        self.assertLessEqual(len(world.hearts), min(world.heart_limit, 6))
        self.assertTrue(all(world.play_top <= heart.y < world.play_bottom for heart in world.hearts))
        first_deadline = world.next_wave_at
        first_count = len(world.hearts)
        world.update(first_deadline + 0.01, 1.0 / 30.0)
        self.assertEqual(world.wave_number, 2)
        self.assertGreater(len(world.hearts), first_count)
        self.assertLessEqual(len(world.hearts), world.heart_limit)

    def test_player_impulse_gravity_and_assist_toggle(self) -> None:
        assisted = GameWorld(100, 30, 0.0, random.Random(8))
        assisted.toggle_player(0.0)
        assisted.control_player(1, -1, 0.0)
        assisted.update(0.1, 0.1)
        self.assertEqual(assisted.state, "player")
        self.assertEqual(assisted.facing, 1)
        self.assertGreater(assisted.velocity_x, 0.0)

        unassisted = GameWorld(100, 30, 0.0, random.Random(8))
        unassisted.toggle_player(0.0)
        unassisted.toggle_gravity_assist(0.0)
        unassisted.update(0.1, 0.1)
        self.assertGreater(unassisted.velocity_y, assisted.velocity_y)

    def test_sustained_diagonal_player_input(self) -> None:
        world = GameWorld(100, 30, 0.0, random.Random(18))
        world.toggle_player(0.0)
        world.set_player_input(1, -1)
        for tick in range(1, 7):
            world.update(tick / 30.0, 1.0 / 30.0)
        self.assertGreater(world.velocity_x, 0.0)
        self.assertLess(world.velocity_y, 0.0)
        before_x = world.velocity_x
        world.set_player_input(0, -1)
        world.update(7 / 30.0, 1.0 / 30.0)
        self.assertGreater(world.velocity_x, 0.0)
        self.assertLess(world.velocity_x, before_x)

    def test_steering_intent_turns_before_momentum_reverses(self) -> None:
        world = GameWorld(180, 50, 0.0, random.Random(28))
        world.toggle_player(0.0)
        world.velocity_x = 40.0
        world.facing = 1
        world.set_player_input(-1, 0)
        world.update(1.0 / 60.0, 1.0 / 60.0)
        self.assertEqual(world.facing, -1)
        self.assertGreater(world.velocity_x, 0.0)

        for tick in range(2, 10):
            world.update(tick / 60.0, 1.0 / 60.0)
        self.assertLess(world.velocity_x, 0.0)
        self.assertGreaterEqual(world.wing_level, 8)

    def test_player_speed_has_high_but_bounded_ceiling(self) -> None:
        world = GameWorld(1000, 200, 0.0, random.Random(38))
        world.toggle_player(0.0)
        world.set_player_input(1, 0)
        for tick in range(1, 301):
            world.update(tick / 60.0, 1.0 / 60.0)
        self.assertGreater(world.velocity_x, 70.0)
        self.assertLessEqual(world.velocity_x, 105.0)

    def test_enhanced_keyboard_keeps_independent_key_releases(self) -> None:
        payload = "\x1b[119;1:1u\x1b[100;1:1u\x1b[100;1:3u\x1b[1;1:3A"
        plain, events, pending = split_enhanced_key_events(payload)
        self.assertEqual(plain, "")
        self.assertEqual(pending, "")
        self.assertEqual(events, [("w", 1), ("d", 1), ("d", 3), ("up", 3)])

        plain, events, pending = split_enhanced_key_events("x\x1b[119;")
        self.assertEqual(plain, "x")
        self.assertEqual(events, [])
        self.assertEqual(pending, "\x1b[119;")

    def test_enhanced_keyboard_accepts_functional_and_modified_arrows(self) -> None:
        payload = "\x1b[57352;1:1u\x1b[57354;1:1u\x1b[57352;1:3u\x1b[1;1D"
        plain, events, pending = split_enhanced_key_events(payload)
        self.assertEqual(plain, "")
        self.assertEqual(pending, "")
        self.assertEqual(events, [("up", 1), ("right", 1), ("up", 3), ("left", 1)])

    def test_enhanced_keyboard_uses_shifted_punctuation(self) -> None:
        payload = "\x1b[61:43;2:1u\x1b[61;2;43u\x1b[91:123;2:1u\x1b[93:125;2:1u"
        plain, events, pending = split_enhanced_key_events(payload)
        self.assertEqual(plain, "")
        self.assertEqual(pending, "")
        self.assertEqual(events, [("+", 1), ("+", 1), ("{", 1), ("}", 1)])
        self.assertEqual(flock_delta_from_keys("+"), 1)
        self.assertEqual(flock_delta_from_keys("="), 1)
        self.assertEqual(flock_delta_from_keys("-"), -1)

    def test_enhanced_keyboard_preserves_shift_n(self) -> None:
        plain, events, pending = split_enhanced_key_events("\x1b[110:78;2:1u")
        self.assertEqual((plain, pending), ("", ""))
        self.assertEqual(events, [("N", 1)])

    def test_game_settings_round_trip_and_validation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            expected = {
                "extended_board": True,
                "flock_count": 17,
                "nectar_limit": 55,
                "nectar_refill": True,
                "auto_spawn": True,
                "player_mode": True,
                "gravity_assist": False,
                "calm": True,
                "help_visible": False,
                "paused": True,
            }
            save_game_settings(expected, path)
            self.assertEqual(load_game_settings(path), expected)
            path.write_text('{"flock_count":999,"nectar_limit":999}', encoding="utf-8")
            loaded = load_game_settings(path)
            self.assertEqual(loaded["flock_count"], MAX_FLOCK_SIZE)
            self.assertEqual(loaded["nectar_limit"], 60)

    def test_continuous_nectar_refills_and_tracks_maximum(self) -> None:
        world = GameWorld(240, 60, 0.0, random.Random(61))
        world.toggle_nectar_refill(0.0)
        self.assertTrue(world.nectar_refill)
        self.assertEqual(len(world.hearts), world.heart_limit)
        consumed = world.hearts[0]
        world._collect(consumed, 0.5)
        self.assertEqual(len(world.hearts), world.heart_limit)
        self.assertNotIn(consumed.ident, {heart.ident for heart in world.hearts})
        world.adjust_nectar_limit(-10, 1.0)
        self.assertEqual(world.heart_limit, 40)
        self.assertEqual(len(world.hearts), 40)

    def test_terminal_responses_cannot_become_numeric_commands(self) -> None:
        payload = "\x1b[4;42R12"
        self.assertEqual(ANSI_INPUT_SEQUENCE_RE.sub("", payload), "12")

    def test_hue_shift_preserves_black_and_changes_bird_color(self) -> None:
        self.assertEqual(hue_shift_color("000000", 0.37), "000000")
        self.assertNotEqual(hue_shift_color("d52bb3", 0.37), "d52bb3")

    def test_swarm_reservations_are_unique_nearest_and_sticky(self) -> None:
        world = GameWorld(120, 36, 0.0, random.Random(48))
        world.toggle_player(0.0)
        world.plant(20, 8, 0.1)
        world.plant(90, 8, 0.2)
        manager = SwarmManager(random.Random(49))
        manager.workers = {
            2: SimpleNamespace(latest=RemoteBird(2, 0.0, 2.0, 1, 0.0, 0.2, "flying")),
            3: SimpleNamespace(latest=RemoteBird(3, 70.0, 2.0, 1, 0.0, 0.5, "flying")),
        }
        manager.prepare(world)
        self.assertEqual(set(manager.reservations), {2, 3})
        self.assertEqual(len(set(manager.reservations.values())), 2)
        original = dict(manager.reservations)
        manager.workers[2].latest = RemoteBird(2, 70.0, 2.0, 1, 0.0, 0.2, "flying")
        manager.workers[3].latest = RemoteBird(3, 0.0, 2.0, 1, 0.0, 0.5, "flying")
        manager.prepare(world)
        self.assertEqual(manager.reservations, original)

    def test_player_collects_without_losing_control(self) -> None:
        world = GameWorld(100, 30, 0.0, random.Random(9))
        world.toggle_player(0.0)
        mouth_x = round(world.bird_x + 26.0)
        mouth_y = round(world.bird_y + 5.5)
        world.plant(mouth_x, mouth_y, 0.01)
        world.update(0.02, 0.01)
        self.assertFalse(world.hearts)
        self.assertEqual(world.state, "player")
        self.assertGreaterEqual(world.score, 15)


if __name__ == "__main__":
    unittest.main()
