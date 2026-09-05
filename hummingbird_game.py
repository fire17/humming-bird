#!/usr/bin/env python3
"""Responsive, non-punitive terminal garden game for the hummingbird TUI."""

from __future__ import annotations

from dataclasses import dataclass
import colorsys
import math
import random
from typing import Callable, Sequence

from pyte.screens import Char

from hummingbird_brain import AutonomousBirdBrain, TargetMotionWatchdog


FRAME_COUNT = 60
BOTTOM_FRAME = 30
LEGACY_CYCLE_LENGTH = 16
DISPLAY_FPS = 30.0
SPEED_STEPS = {
    1: 0.25, 2: 0.5, 3: 0.75, 4: 1.25, 5: 2.0,
    6: 2.75, 7: 3.5, 8: 4.25, 9: 5.0,
}
REST_LEVELS = (4, 5, 6, 7, 8)
REST_WEIGHTS = (1.0, 1.0, 0.5, 1.0 / 3.0, 0.25)
DEFAULT_NECTAR_LIMIT = 50
MAX_NECTAR_LIMIT = 60
DOUBLE_CLICK_SECONDS = 0.38
TRAIL_COLORS = ("00b9d7", "086e91", "173e69")
RETICLE_CELL = Char(data="+", fg="7befff", bold=True)


def trail_cell(spark, now: float) -> Char:
    """One shared fade rule for terminal and browser movement/capture effects."""
    age = (now - spark.born_at) / spark.lifetime
    return Char(data="·", fg=TRAIL_COLORS[2 if age > 0.66 else (1 if age > 0.33 else 0)])


def perch_cell(cell: Char, selected: bool) -> Char:
    if selected or cell.fg in {"default", "000000"}:
        return cell
    red = int(cell.fg[0:2], 16) // 2
    green = int(cell.fg[2:4], 16) * 3 // 4
    blue = int(cell.fg[4:6], 16) // 2
    return cell._replace(fg=f"{red:02x}{green:02x}{blue:02x}")


@dataclass
class NectarHeart:
    ident: int
    x: int
    y: int
    born_at: float
    phase_offset: float


@dataclass
class TrailSpark:
    x: int
    y: int
    born_at: float
    lifetime: float = 0.60


@dataclass(frozen=True)
class LeafPerch:
    x: int
    y: int


@dataclass(frozen=True)
class RemoteBird:
    ident: int
    x: float
    y: float
    facing: int
    wing_position: float
    hue_shift: float
    state: str
    velocity_x: float = 0.0
    velocity_y: float = 0.0


def _distance(dx: float, dy: float) -> float:
    """Terminal rows are visually taller than columns, so weight Y accordingly."""
    return math.hypot(dx, dy * 1.8)


def _clamp(value: float, low: float, high: float) -> float:
    if high < low:
        return low
    return min(high, max(low, value))


class GameWorld:
    """Time-based game model; contains no terminal I/O."""

    def __init__(self, width: int, height: int, now: float, rng: random.Random | None = None):
        self.rng = rng or random.Random()
        self.width = max(1, width)
        self.height = max(1, height)
        self.extended_board = False
        self.camera_x = 0.0
        self.camera_y = 0.0
        self.compact = False
        self.play_top = 2
        self.play_bottom = max(2, height - 2)
        self.bird_x = width / 2.0 - 16.0
        self.bird_y = max(2.0, height / 3.0 - 5.0)
        self.velocity_x = 0.0
        self.velocity_y = 0.0
        self.muscle_load = 0.0
        self.facing = 1
        self.wing_position = 0.0
        self.autonomous_brain = AutonomousBirdBrain(
            1, self.rng, frame_count=FRAME_COUNT, bottom_frame=BOTTOM_FRAME,
            x=self.bird_x, y=self.bird_y, facing=self.facing,
            wing_position=self.wing_position, initialized=True,
        )
        self.wing_level = 5
        self.state = "surveying"
        self.state_started_at = now
        self.state_deadline = now + 0.65
        self.target_id: int | None = None
        self.assigned_target_id: int | None = None
        self.recovery_until = 0.0
        self.target_leaf = 0
        self.hearts: list[NectarHeart] = []
        self.trail: list[TrailSpark] = []
        self.next_heart_id = 1
        self.nectar_limit_setting = DEFAULT_NECTAR_LIMIT
        self.last_trail_at = now
        self.score = 0
        self.collected = 0
        self.combo = 0
        self.last_collect_at = -1000.0
        self.message = "Double-click to plant nectar"
        self.message_until = now + 5.0
        self.calm = False
        self.help_visible = True
        self.reticle_x = max(0, width // 2)
        self.reticle_y = max(0, height // 2)
        self.reticle_until = 0.0
        self.leaves: list[LeafPerch] = []
        self.settle_start = 0.0
        self.settle_distance = 0.0
        self.settle_direction = 1.0
        self.flutter_level: int | None = None
        self.auto_spawn = False
        self.nectar_refill = False
        self.next_wave_at = math.inf
        self.wave_number = 0
        self.wave_size = 0
        self.player_mode = False
        self.gravity_assist = True
        self.best_combo = 0
        self.companions: list[RemoteBird] = []
        self.player_input_x = 0
        self.player_input_y = 0
        self.resize(width, height, now, initial=True)

    @property
    def bird_count(self) -> int:
        return 1 + len(self.companions)

    @property
    def heart_limit(self) -> int:
        area_limit = max(2, (self.width * max(1, self.height - 3)) // 120)
        return min(MAX_NECTAR_LIMIT, self.nectar_limit_setting, area_limit)

    @property
    def playable(self) -> bool:
        return self.width >= 8 and self.height >= 6

    @property
    def camera_cell(self) -> tuple[int, int]:
        # Quantize once for the whole scene: independent sprite rounding makes
        # stationary objects wobble relative to each other during a camera pan.
        return round(self.camera_x), round(self.camera_y)

    def screen_to_world(self, x: int, y: int) -> tuple[int, int]:
        cx, cy = self.camera_cell
        return x + cx, y + cy

    def world_to_screen(self, x: float, y: float) -> tuple[int, int]:
        cx, cy = self.camera_cell
        return round(x) - cx, round(y) - cy

    def toggle_extended_board(self, now: float) -> None:
        self.extended_board = not self.extended_board
        if not self.extended_board:
            # Returning to a bounded garden restores its original coordinate
            # space. Workers receive bounded physics on their next snapshot.
            self.camera_x = self.camera_y = 0.0
            self.resize(self.width, self.height, now)
        self.say("Extended board on · fly into the outer 10% to scroll" if self.extended_board
                 else "Bounded garden · E to extend", now, 3.0)

    def update_camera(self, dt: float, *, reframe: bool = False) -> None:
        if not self.extended_board or not self.playable:
            return
        center_x, center_y = self._bird_center()
        # The visible leading edge triggers at 10%. Clamp the effective sprite
        # radius on small terminals so the two trigger zones never overlap.
        def follow(camera: float, position: float, velocity: float,
                   start: float, end: float, radius: float) -> float:
            span = max(1.0, end - start)
            radius = min(radius, span * 0.20)
            low, high = start + span * 0.10 + radius, end - span * 0.10 - radius
            screen = position - camera
            if screen < low and (velocity < -0.01 or reframe):
                error = screen - low
            elif screen > high and (velocity > 0.01 or reframe):
                error = screen - high
            else:
                return camera
            # Exponential tracking provides a continuous onset. A final outer
            # guard prevents a fast diagonal move or resize losing the bird.
            camera += error if reframe else error * -math.expm1(-18.0 * max(0.0, dt))
            return _clamp(camera, position - (end - radius), position - (start + radius))

        self.camera_x = follow(self.camera_x, center_x, self.velocity_x,
                               0.0, self.width - 1.0, 1.0 if self.compact else 11.5)
        self.camera_y = follow(self.camera_y, center_y, self.velocity_y,
                               1.0, self.height - 2.0, 0.0 if self.compact else 5.5)

    def resize(self, width: int, height: int, now: float, initial: bool = False) -> None:
        self.width = max(1, width)
        self.height = max(1, height)
        self.compact = self.width < 38 or self.height < 16
        self.play_top = 2 if self.height >= 8 else 1
        self.play_bottom = max(self.play_top, self.height - 2)
        if self.extended_board and not initial:
            # A viewport resize must not teleport the world, nectar, or perches.
            self.reticle_x = int(_clamp(self.reticle_x, 0, self.width - 1))
            self.reticle_y = int(_clamp(self.reticle_y, self.play_top, self.play_bottom))
            self.update_camera(0.0, reframe=True)
            if self.nectar_refill:
                self._maintain_nectar(now)
            self.say(f"Garden resized · {self.width}×{self.height}", now, 1.8)
            return
        leaf_count = max(1, min(5, self.width // (18 if self.compact else 30)))
        leaf_y = self.play_bottom - (1 if self.compact else 11)
        self.leaves = [
            LeafPerch(
                round((index + 0.5) * self.width / leaf_count - (2 if self.compact else 16)),
                leaf_y,
            )
            for index in range(leaf_count)
        ]
        self.target_leaf = min(self.target_leaf, len(self.leaves) - 1)
        self.bird_x = _clamp(self.bird_x, -26.0, max(0.0, self.width - 6.0))
        self.bird_y = _clamp(self.bird_y, self.play_top - 8.0, self.play_bottom - 2.0)
        self.reticle_x = int(_clamp(self.reticle_x, 0, self.width - 1))
        self.reticle_y = int(_clamp(self.reticle_y, self.play_top, self.play_bottom))
        for heart in self.hearts:
            heart.x = int(_clamp(heart.x, 0, max(0, self.width - (1 if self.compact else 5))))
            heart.y = int(_clamp(heart.y, self.play_top, max(self.play_top, self.play_bottom - 1)))
        if self.nectar_refill:
            self._maintain_nectar(now)
        # These are all physically perched states. A resize can arrive in the
        # middle of a flutter/fold, so keep the bird attached to the newly
        # laid-out leaf instead of waiting for the state machine to go idle.
        if self.state in {"landed", "settling", "rest_flutter", "rest_folding"} and self.leaves:
            perch = self.leaves[self.target_leaf]
            self.bird_x, self.bird_y = float(perch.x), float(perch.y)
        if not initial:
            self.say(f"Garden resized · {self.width}×{self.height}", now, 1.8)

    def say(self, text: str, now: float, duration: float = 2.0) -> None:
        self.message = text
        self.message_until = now + duration

    def set_reticle(self, x: int, y: int, now: float) -> None:
        self.reticle_x = int(_clamp(x, 0, self.width - 1))
        self.reticle_y = int(_clamp(y, self.play_top, self.play_bottom))
        self.reticle_until = now + 0.42

    def move_reticle(self, dx: int, dy: int, now: float) -> None:
        self.set_reticle(self.reticle_x + dx, self.reticle_y + dy, now)

    def plant(self, x: int, y: int, now: float) -> bool:
        if not self.playable or y < self.play_top or y > self.play_bottom:
            self.say("Plant inside the garden", now)
            return False
        sprite_width = 1 if self.compact else 5
        sprite_height = 1 if self.compact else 2
        x = int(_clamp(x - sprite_width // 2, 0, max(0, self.width - sprite_width)))
        y = int(_clamp(y - sprite_height // 2, self.play_top, max(self.play_top, self.play_bottom - sprite_height + 1)))
        screen_x, screen_y = x, y
        x, y = self.screen_to_world(x, y)
        if len(self.hearts) >= self.heart_limit:
            oldest = min(self.hearts, key=lambda item: item.born_at)
            self.hearts.remove(oldest)
            self.score += 1
            self.say("Garden full · oldest nectar became a seed +1", now, 2.4)
        heart = NectarHeart(self.next_heart_id, x, y, now, self.rng.random())
        self.next_heart_id += 1
        self.hearts.append(heart)
        self.set_reticle(screen_x + sprite_width // 2, screen_y, now)
        if self.state in {"landed", "settling", "rest_flutter", "rest_folding", "returning"}:
            self.state = "taking_off"
            self.state_started_at = now
            self.state_deadline = now + (0.48 if self.calm else 0.34)
            self.target_id = None
        elif self.state == "surveying":
            self.state_deadline = min(self.state_deadline, now + 0.10)
        self.say(f"Nectar planted · {len(self.hearts)}/{self.heart_limit}", now, 1.4)
        return True

    def plant_random(self, now: float) -> bool:
        x = self.rng.randrange(max(1, self.width))
        y = self.rng.randrange(self.play_top, max(self.play_top + 1, self.play_bottom + 1))
        return self.plant(x, y, now)

    def _maintain_nectar(self, now: float) -> None:
        """Keep the live heart count equal to the current effective maximum."""
        while len(self.hearts) > self.heart_limit:
            self.hearts.remove(min(self.hearts, key=lambda item: item.born_at))
        while self.playable and len(self.hearts) < self.heart_limit:
            before = len(self.hearts)
            self.plant_random(now)
            if len(self.hearts) <= before:
                break

    def toggle_nectar_refill(self, now: float) -> None:
        self.nectar_refill = not self.nectar_refill
        if self.nectar_refill:
            self._maintain_nectar(now)
            self.say(f"Continuous nectar on · {len(self.hearts)}/{self.heart_limit}", now, 2.2)
        else:
            self.say("Continuous nectar off", now, 2.0)

    def _schedule_wave(self, now: float, first: bool = False) -> None:
        if first:
            delay = 0.35
        else:
            # A fuller garden breathes longer before the next formation while
            # still guaranteeing activity if one awkward heart remains.
            pressure = len(self.hearts) / max(1, self.heart_limit)
            delay = self.rng.randrange(180, 601) / 100.0 + pressure * 2.0
        self.next_wave_at = now + delay

    def toggle_auto(self, now: float) -> None:
        self.auto_spawn = not self.auto_spawn
        if self.auto_spawn:
            self._schedule_wave(now, first=not self.hearts)
            self.say("Screensaver waves on", now)
        else:
            self.next_wave_at = math.inf
            self.say("Screensaver waves off", now)

    def _spawn_wave(self, now: float) -> None:
        available = self.heart_limit - len(self.hearts)
        if available <= 0:
            self._schedule_wave(now)
            return
        self.wave_number += 1
        growth = min(6, 2 + self.wave_number // 2)
        maximum = max(1, min(available, growth))
        minimum = 1 if maximum == 1 else 2
        size = self.rng.randint(minimum, maximum)
        self.wave_size = size

        left = 1 if self.compact else 4
        right = max(left, self.width - (2 if self.compact else 6))
        top = self.play_top + (0 if self.compact else 1)
        bottom = max(top, self.play_bottom - (2 if self.compact else 10))
        pattern = self.rng.choice(("arc", "ribbon", "scatter"))
        center_x = self.rng.randint(left, right)
        center_y = self.rng.randint(top, bottom)
        spacing = max(3, min(9, self.width // max(3, size + 1)))

        points: list[tuple[int, int]] = []
        for index in range(size):
            if pattern == "scatter":
                x = self.rng.randint(left, right)
                y = self.rng.randint(top, bottom)
            else:
                offset = index - (size - 1) / 2.0
                x = round(center_x + offset * spacing)
                if pattern == "arc":
                    y = round(center_y + abs(offset) * 1.4)
                else:
                    y = round(center_y + math.sin(index * 1.35) * 2.0)
                x = int(_clamp(x, left, right))
                y = int(_clamp(y, top, bottom))
            points.append((x, y))

        for x, y in points:
            self.plant(x, y, now)
        self.say(f"Wave {self.wave_number} · {size} nectar · {pattern}", now, 2.4)
        self._schedule_wave(now)

    def toggle_player(self, now: float) -> None:
        self.player_mode = not self.player_mode
        self.target_id = None
        if self.player_mode:
            self.state = "player"
            self.state_started_at = now
            self.velocity_x *= 0.35
            self.velocity_y *= 0.35
            self.say("Pilot mode · arrows/WASD fly", now, 2.4)
        else:
            self.player_input_x = self.player_input_y = 0
            self.state = "surveying"
            self.state_started_at = now
            self.state_deadline = now + 0.12
            self.say("Natural flight resumed", now)

    def toggle_gravity_assist(self, now: float) -> None:
        self.gravity_assist = not self.gravity_assist
        self.say(
            "Hover assist on" if self.gravity_assist else "Hover assist off · score bonus",
            now,
            2.2,
        )

    def control_player(self, dx: int, dy: int, now: float) -> None:
        if not self.player_mode:
            return
        horizontal_impulse = 9.0 if self.compact else 12.0
        vertical_impulse = 6.5 if self.compact else 9.0
        self.velocity_x += dx * horizontal_impulse
        self.velocity_y += dy * vertical_impulse
        if dx:
            self.facing = 1 if dx > 0 else -1
        self.state = "player"
        self.state_started_at = min(self.state_started_at, now)

    def set_player_input(self, dx: int, dy: int) -> None:
        self.player_input_x = max(-1, min(1, dx)) if self.player_mode else 0
        self.player_input_y = max(-1, min(1, dy)) if self.player_mode else 0
        if self.player_input_x:
            self.facing = 1 if self.player_input_x > 0 else -1

    def clear_hearts(self, now: float) -> None:
        self.hearts.clear()
        self.target_id = None
        self.assigned_target_id = None
        self.combo = 0
        self.state = "surveying"
        self.state_started_at = now
        self.state_deadline = now + 0.35
        self.say("Garden cleared · finding a leaf", now)
        if self.nectar_refill:
            self._maintain_nectar(now)
        if self.auto_spawn:
            self._schedule_wave(now)

    def adjust_nectar_limit(self, delta: int, now: float) -> None:
        self.nectar_limit_setting = int(_clamp(
            self.nectar_limit_setting + delta, 1, MAX_NECTAR_LIMIT,
        ))
        if self.nectar_refill:
            self._maintain_nectar(now)
        effective = self.heart_limit
        suffix = "" if effective == self.nectar_limit_setting else f" · screen fits {effective}"
        self.say(f"Nectar max {self.nectar_limit_setting}{suffix}", now, 2.0)

    def _bird_center(self) -> tuple[float, float]:
        if self.compact:
            return self.bird_x + 1.0, self.bird_y
        return self.bird_x + 15.5, self.bird_y + 5.5

    def _choose_heart(self, now: float) -> NectarHeart | None:
        if not self.hearts:
            return None
        assigned = next(
            (heart for heart in self.hearts if heart.ident == self.assigned_target_id),
            None,
        )
        if assigned is not None:
            return assigned
        center_x, center_y = self._bird_center()
        speed = math.hypot(self.velocity_x, self.velocity_y)
        heading_x = self.velocity_x / speed if speed > 0.5 else float(self.facing)

        def cost(heart: NectarHeart) -> float:
            hx = heart.x + (0.5 if self.compact else 2.5)
            hy = heart.y + (0.0 if self.compact else 0.5)
            dx, dy = hx - center_x, hy - center_y
            distance = _distance(dx, dy)
            direction_x = dx / max(0.001, math.hypot(dx, dy))
            turn_cost = max(0.0, heading_x * -direction_x) * 7.0
            age_bonus = min(8.0, (now - heart.born_at) * 0.18)
            return distance + turn_cost - age_bonus

        return min(self.hearts, key=cost)

    def _advance_wing(self, dt: float, level: int) -> None:
        self.wing_level = level
        frames_per_second = SPEED_STEPS[level] * FRAME_COUNT / LEGACY_CYCLE_LENGTH * DISPLAY_FPS
        self.wing_position = (self.wing_position + self.facing * frames_per_second * dt) % FRAME_COUNT

    def _begin_settle(self, now: float, duration: float = 0.80) -> None:
        self.state = "settling"
        self.state_started_at = now
        self.state_deadline = now + duration
        self.settle_start = self.wing_position % FRAME_COUNT
        self.settle_direction = 1.0 if self.facing > 0 else -1.0
        if self.settle_direction > 0:
            base = (BOTTOM_FRAME - self.settle_start) % FRAME_COUNT
        else:
            base = (self.settle_start - BOTTOM_FRAME) % FRAME_COUNT
        self.settle_distance = base + (FRAME_COUNT if base < 15.0 else 0.0)
        self.velocity_x = self.velocity_y = 0.0

    def _update_settle(self, now: float) -> None:
        duration = max(0.001, self.state_deadline - self.state_started_at)
        progress = min(1.0, (now - self.state_started_at) / duration)
        eased = 2.0 * progress - progress * progress
        self.wing_position = (
            self.settle_start + self.settle_direction * self.settle_distance * eased
        ) % FRAME_COUNT
        if progress >= 1.0:
            self.wing_position = float(BOTTOM_FRAME)
            self.state = "landed"
            self.state_started_at = now
            self.state_deadline = now + self.rng.uniform(3.0, 5.0)
            self.say("Garden clear · resting", now, 2.0)

    def _choose_leaf(self) -> int:
        if not self.leaves:
            return 0
        center_x, center_y = self._bird_center()
        return min(
            range(len(self.leaves)),
            key=lambda index: _distance(self.leaves[index].x - center_x, self.leaves[index].y - center_y),
        )

    def _collect(self, heart: NectarHeart, now: float, companion: int | None = None) -> None:
        self.hearts.remove(heart)
        self.collected += 1
        self.combo = min(5, self.combo + 1) if now - self.last_collect_at <= 4.0 else 1
        self.best_combo = max(self.best_combo, self.combo)
        player_collection = self.player_mode and companion is None
        player_bonus = 5 * self.combo if player_collection else 0
        no_assist_bonus = 5 * self.combo if player_collection and not self.gravity_assist else 0
        gained = 10 * self.combo + player_bonus + no_assist_bonus
        self.score += gained
        self.last_collect_at = now
        for offset in range(-2, 3):
            self.trail.append(TrailSpark(heart.x + 2 + offset, heart.y, now, 0.85))
        collector = "You" if player_collection else (f"Bird {companion}" if companion else "Nectar")
        self.say(f"{collector} +{gained} · flow ×{self.combo}", now, 1.8)
        # A companion collection is a world event, not a command to reset the
        # primary bird. The old shared score path interrupted bird 1 every time
        # another worker drank, which made its otherwise similar AI visibly
        # pause and retarget. Only the collecting primary changes its own state.
        if companion is None:
            self.target_id = None
            if self.assigned_target_id == heart.ident:
                self.assigned_target_id = None
            self.state = "player" if self.player_mode else "surveying"
            self.state_started_at = now
            self.state_deadline = now + (0.30 if self.hearts else 0.75)
        if self.nectar_refill:
            self._maintain_nectar(now)
        if self.auto_spawn and not self.hearts:
            wave_bonus = max(5, self.wave_size * 5)
            self.score += wave_bonus
            self.say(f"Wave {self.wave_number} clear +{wave_bonus}", now, 2.2)
            self._schedule_wave(now)

    def collect_companion(self, heart_id: int, companion: int, now: float) -> bool:
        heart = next((item for item in self.hearts if item.ident == heart_id), None)
        if heart is None:
            return False
        self._collect(heart, now, companion=companion)
        return True

    def _update_autonomous(self, now: float, dt: float) -> None:
        """Run bird 1 through the exact brain class used by worker processes."""
        if not self.hearts:
            self.target_leaf = self._choose_leaf()
        assigned_target = self.assigned_target_id
        # Standalone model tests and one-bird integrations do not have a swarm
        # reservation pass. Their sole bird can safely claim its own nearest
        # heart; flocked runtime assignments remain parent-authoritative.
        if assigned_target is None and not self.companions:
            heart = self._choose_heart(now)
            assigned_target = heart.ident if heart is not None else None
            self.assigned_target_id = assigned_target

        self.autonomous_brain.sync_kinematics(
            self.bird_x, self.bird_y, self.velocity_x, self.velocity_y,
            self.facing, self.wing_position,
        )
        neighbors = [(1, self.bird_x, self.bird_y, self.velocity_x, self.velocity_y)]
        neighbors.extend(
            (bird.ident, bird.x, bird.y, bird.velocity_x, bird.velocity_y)
            for bird in self.companions
        )
        result = self.autonomous_brain.step(
            now=now,
            dt=dt,
            width=self.width,
            compact=self.compact,
            play_top=self.play_top,
            play_bottom=self.play_bottom,
            count=self.bird_count,
            primary_leaf=self.target_leaf,
            hearts=tuple((heart.ident, heart.x, heart.y) for heart in self.hearts),
            leaves=tuple((leaf.x, leaf.y) for leaf in self.leaves),
            assigned_target=assigned_target,
            neighbors=tuple(neighbors),
            calm=self.calm,
            extended_board=self.extended_board,
            view_origin=self.camera_cell,
        )
        old_x, old_y = self.bird_x, self.bird_y
        self.bird_x, self.bird_y = result.x, result.y
        self.velocity_x, self.velocity_y = result.velocity_x, result.velocity_y
        self.facing = result.facing
        self.wing_position = result.wing_position
        self.recovery_until = self.autonomous_brain.recovery_until
        self.target_id = assigned_target
        speed = math.hypot(self.velocity_x, self.velocity_y)
        self.wing_level = 7 if result.recovering else (4 if speed < 7.0 else 6)

        if visual_movement := _distance(self.bird_x - old_x, self.bird_y - old_y):
            if visual_movement > 0.01 and now - self.last_trail_at >= (0.16 if self.calm else 0.09):
                center_x, center_y = self._bird_center()
                self.trail.append(TrailSpark(round(center_x), round(center_y), now))
                self.last_trail_at = now

        if result.collected_id is not None:
            heart = next((item for item in self.hearts if item.ident == result.collected_id), None)
            if heart is not None:
                self._collect(heart, now)
            return
        if result.state == "perched":
            if self.state not in {"settling", "landed", "rest_flutter", "rest_folding"}:
                self._begin_settle(now)
        else:
            self.state = result.state
            self.state_started_at = now

    def _update_player(self, now: float, dt: float) -> None:
        acceleration_x = 82.0 if self.compact else 120.0
        acceleration_y = 58.0 if self.compact else 84.0
        counter_x = bool(
            self.player_input_x
            and abs(self.velocity_x) > 3.0
            and self.player_input_x * self.velocity_x < 0.0
        )
        counter_y = bool(
            self.player_input_y
            and abs(self.velocity_y) > 2.0
            and self.player_input_y * self.velocity_y < 0.0
        )
        # A hummingbird can brake and redirect with startling authority.  The
        # opposing force is deliberately stronger than cruise thrust, while
        # remaining acceleration-based so the old velocity still produces a
        # brief, readable backward slide before the turn wins.
        if counter_x:
            acceleration_x *= 3.4
        if counter_y:
            acceleration_y *= 3.1
        demanded_load = max(
            min(1.0, abs(self.velocity_x) / 32.0) if counter_x else 0.0,
            min(1.0, abs(self.velocity_y) / 22.0) if counter_y else 0.0,
        )
        response = 18.0 if demanded_load > self.muscle_load else 7.5
        self.muscle_load += (demanded_load - self.muscle_load) * min(1.0, response * dt)
        self.velocity_x += self.player_input_x * acceleration_x * dt
        self.velocity_y += self.player_input_y * acceleration_y * dt
        gravity = 7.5 * (0.14 if self.gravity_assist else 1.0)
        self.velocity_y += gravity * dt
        horizontal_drag = math.exp(-(1.15 if self.gravity_assist else 0.50) * dt)
        vertical_drag = math.exp(-(1.65 if self.gravity_assist else 0.40) * dt)
        self.velocity_x *= horizontal_drag
        self.velocity_y *= vertical_drag
        self.velocity_x = _clamp(self.velocity_x, -105.0, 105.0)
        self.velocity_y = _clamp(self.velocity_y, -72.0, 72.0)
        self.bird_x += self.velocity_x * dt
        self.bird_y += self.velocity_y * dt

        if self.compact:
            min_x, max_x = 0.0, max(0.0, self.width - 2.0)
            min_y, max_y = float(self.play_top), float(self.play_bottom)
        else:
            min_x, max_x = -5.0, max(-5.0, self.width - 27.0)
            min_y, max_y = float(self.play_top - 2), max(float(self.play_top - 2), self.play_bottom - 9.0)
        if not self.extended_board and (self.bird_x < min_x or self.bird_x > max_x):
            self.bird_x = _clamp(self.bird_x, min_x, max_x)
            self.velocity_x *= -0.24
        if not self.extended_board and (self.bird_y < min_y or self.bird_y > max_y):
            self.bird_y = _clamp(self.bird_y, min_y, max_y)
            self.velocity_y *= -0.18

        speed = math.hypot(self.velocity_x, self.velocity_y * 1.8)
        if self.muscle_load >= 0.62:
            wing_level = 9
        elif self.muscle_load >= 0.24:
            wing_level = 8
        elif speed >= 48.0:
            wing_level = 7
        else:
            wing_level = 4 if speed < 4 else (5 if speed < 12 else 6)
        self._advance_wing(dt, wing_level)
        if now - self.last_trail_at >= (0.18 if self.gravity_assist else 0.10):
            center_x, center_y = self._bird_center()
            self.trail.append(TrailSpark(round(center_x), round(center_y), now))
            self.last_trail_at = now

        if self.compact:
            mouth_x = self.bird_x + (2.0 if self.facing > 0 else 0.0)
            mouth_y = self.bird_y
        else:
            mouth_x = self.bird_x + (26.0 if self.facing > 0 else 5.0)
            mouth_y = self.bird_y + 5.5
        for heart in tuple(self.hearts):
            hx = heart.x + (0.5 if self.compact else 2.5)
            hy = heart.y + (0.0 if self.compact else 0.5)
            if _distance(hx - mouth_x, hy - mouth_y) <= (2.4 if self.compact else 3.4):
                self._collect(heart, now)
                break

    def update(self, now: float, dt: float) -> None:
        dt = min(0.10, max(0.0, dt))
        self.trail = [spark for spark in self.trail if now - spark.born_at < spark.lifetime]
        if not self.playable:
            return
        if self.auto_spawn and now >= self.next_wave_at:
            self._spawn_wave(now)
        if self.player_mode:
            self.state = "player"
            self._update_player(now, dt)
            self.update_camera(dt)
            return
        if self.state == "settling" and not self.hearts:
            self._update_settle(now)
        elif self.state == "landed" and not self.hearts:
            self.wing_position = float(BOTTOM_FRAME)
            if now >= self.state_deadline:
                self.flutter_level = self.rng.choices(REST_LEVELS, REST_WEIGHTS, k=1)[0]
                self.state = "rest_flutter"
                self.state_started_at = now
                self.state_deadline = now + self.rng.uniform(0.20, 1.00)
        elif self.state == "rest_flutter" and not self.hearts:
            self._advance_wing(dt, self.flutter_level or 5)
            if now >= self.state_deadline:
                self.state = "rest_folding"
                self.state_started_at = now
                self.state_deadline = now + 0.20
                self.settle_start = self.wing_position % FRAME_COUNT
                self.settle_direction = 1.0 if self.facing > 0 else -1.0
                if self.settle_direction > 0:
                    self.settle_distance = (BOTTOM_FRAME - self.settle_start) % FRAME_COUNT
                else:
                    self.settle_distance = (self.settle_start - BOTTOM_FRAME) % FRAME_COUNT
        elif self.state == "rest_folding" and not self.hearts:
            progress = min(1.0, (now - self.state_started_at) / 0.20)
            eased = 2.0 * progress - progress * progress
            self.wing_position = (
                self.settle_start + self.settle_direction * self.settle_distance * eased
            ) % FRAME_COUNT
            if progress >= 1.0:
                self.wing_position = float(BOTTOM_FRAME)
                self.state = "landed"
                self.state_deadline = now + self.rng.uniform(3.0, 5.0)
        else:
            self._update_autonomous(now, dt)

        if not self.extended_board:
            self.bird_x = _clamp(self.bird_x, -26.0, max(0.0, self.width - 6.0))
            self.bird_y = _clamp(self.bird_y, self.play_top - 8.0, self.play_bottom - 1.0)
        self.update_camera(dt)

    def toggle_calm(self, now: float) -> None:
        self.calm = not self.calm
        self.say("Calm flight" if self.calm else "Lively flight", now)

    def status(self, now: float) -> tuple[str, str]:
        state = self.state.replace("rest_", "").replace("_", "-").upper()
        if self.state in {"rest_flutter", "rest_folding"} and self.flutter_level:
            state += f" L{self.flutter_level}"
        mode = "CALM" if self.calm else "ALIVE"
        driver = "PILOT" if self.player_mode else "AI"
        waves = f"AUTO W{self.wave_number}" if self.auto_spawn else "MANUAL"
        if self.nectar_refill:
            waves += " FULL"
        if self.player_mode:
            vectors = {
                (-1, -1): "↖", (0, -1): "↑", (1, -1): "↗",
                (-1, 0): "←", (0, 0): "·", (1, 0): "→",
                (-1, 1): "↙", (0, 1): "↓", (1, 1): "↘",
            }
            speed = math.hypot(self.velocity_x, self.velocity_y * 1.8)
            assist = "ASSIST" if self.gravity_assist else "GRAVITY"
            flight = f"{assist} {vectors[(self.player_input_x, self.player_input_y)]} v{speed:.0f}"
        else:
            flight = mode
        top = (
            f" GARDEN  score {self.score}  nectar {len(self.hearts)}/{self.heart_limit}"
            f"  flow ×{self.combo}  birds {self.bird_count}  {driver}  {waves}  {flight}"
        )
        if self.extended_board:
            cx, cy = self.camera_cell
            top += f"  EXT {cx:+d},{cy:+d}"
        if now < self.message_until:
            bottom = self.message
        elif self.help_visible:
            if self.player_mode:
                bottom = "arrows/WASD fly · N full nectar · digits/± flock · [ ] max · f assist · o waves · p AI · g exit"
            else:
                bottom = "N full nectar · digits/± flock · [ ] max · o waves · p pilot · double-click plant · g exit"
        else:
            bottom = "? help · g exit"
        if self.help_visible and now >= self.message_until:
            bottom = "E scroll board · " + bottom
        return top, bottom


def mirror_braille(character: str) -> str:
    codepoint = ord(character)
    if not 0x2800 <= codepoint <= 0x28FF:
        return character
    bits = codepoint - 0x2800
    pairs = ((0, 3), (1, 4), (2, 5), (6, 7))
    mirrored = bits
    for left, right in pairs:
        left_on, right_on = bits & (1 << left), bits & (1 << right)
        mirrored &= ~((1 << left) | (1 << right))
        if left_on:
            mirrored |= 1 << right
        if right_on:
            mirrored |= 1 << left
    return chr(0x2800 + mirrored)


MIRROR_GLYPHS = str.maketrans({
    "▏": "▕", "▕": "▏", "▖": "▗", "▗": "▖", "▘": "▝", "▝": "▘",
    "▙": "▟", "▟": "▙", "▛": "▜", "▜": "▛", "▌": "▐", "▐": "▌",
    "◢": "◣", "◣": "◢", "◤": "◥", "◥": "◤", "╺": "╸", "╸": "╺",
    "╶": "╴", "╴": "╶", "/": "\\", "\\": "/", "<": ">", ">": "<",
})


def mirrored_character(character: str) -> str:
    return mirror_braille(character).translate(MIRROR_GLYPHS)


def hue_shift_color(color: str, shift: float) -> str:
    if color == "default" or len(color) != 6 or math.isclose(shift % 1.0, 0.0, abs_tol=1e-9):
        return color
    red, green, blue = (int(color[index:index + 2], 16) / 255.0 for index in (0, 2, 4))
    hue, lightness, saturation = colorsys.rgb_to_hls(red, green, blue)
    red, green, blue = colorsys.hls_to_rgb((hue + shift) % 1.0, lightness, saturation)
    return f"{round(red * 255):02x}{round(green * 255):02x}{round(blue * 255):02x}"


def hue_shift_cell(cell: Char, shift: float) -> Char:
    return cell._replace(
        fg=hue_shift_color(cell.fg, shift),
        bg=hue_shift_color(cell.bg, shift),
    )


_MASK_WIDTH = 8
_MASK_HEIGHT = 8


def _rect_mask(left: int, top: int, right: int, bottom: int) -> tuple[bool, ...]:
    return tuple(
        left <= x < right and top <= y < bottom
        for y in range(_MASK_HEIGHT)
        for x in range(_MASK_WIDTH)
    )


def _glyph_foreground_mask(glyph: str) -> tuple[bool, ...]:
    """Approximate a Chafa glyph's foreground region at sub-cell resolution."""
    empty = (False,) * (_MASK_WIDTH * _MASK_HEIGHT)
    full = (True,) * (_MASK_WIDTH * _MASK_HEIGHT)
    if not glyph or glyph == " ":
        return empty
    code = ord(glyph[0])
    if glyph == "█":
        return full
    if 0x2581 <= code <= 0x2587:  # lower one-eighth through seven-eighths
        rows = code - 0x2580
        return _rect_mask(0, _MASK_HEIGHT - rows, _MASK_WIDTH, _MASK_HEIGHT)
    if glyph == "▀":
        return _rect_mask(0, 0, _MASK_WIDTH, 4)
    if glyph == "▄":
        return _rect_mask(0, 4, _MASK_WIDTH, 8)
    if glyph == "▔":
        return _rect_mask(0, 0, _MASK_WIDTH, 1)
    if glyph == "▕":
        return _rect_mask(7, 0, 8, 8)
    vertical_blocks = {"▏": 1, "▎": 2, "▍": 3, "▌": 4, "▋": 5, "▊": 6, "▉": 7, "▐": 4}
    if glyph in vertical_blocks:
        columns = vertical_blocks[glyph]
        if glyph == "▐":
            return _rect_mask(4, 0, 8, 8)
        return _rect_mask(0, 0, columns, 8)
    quadrants = {
        "▘": ((0, 0),), "▝": ((1, 0),), "▖": ((0, 1),), "▗": ((1, 1),),
        "▚": ((0, 0), (1, 1)), "▞": ((1, 0), (0, 1)),
        "▛": ((0, 0), (1, 0), (0, 1)), "▜": ((0, 0), (1, 0), (1, 1)),
        "▙": ((0, 0), (0, 1), (1, 1)), "▟": ((1, 0), (0, 1), (1, 1)),
    }
    if glyph in quadrants:
        selected = quadrants[glyph]
        return tuple(
            (x // 4, y // 4) in selected
            for y in range(8)
            for x in range(8)
        )
    if 0x2800 <= code <= 0x28FF:  # Braille: two columns by four rows.
        bits = code - 0x2800
        dots = ((0, 0, 0), (1, 0, 1), (2, 0, 2), (3, 0, 6),
                (0, 1, 3), (1, 1, 4), (2, 1, 5), (3, 1, 7))
        selected = {(column, row) for row, column, bit in dots if bits & (1 << bit)}
        return tuple(
            (x // 4, y // 2) in selected
            for y in range(8)
            for x in range(8)
        )
    # Border and diagonal glyphs are thin strokes, not filled cells.
    horizontal = set("─━╴╶╺╸╼╾╌╍")
    vertical = set("│┃╵╷╹╻")
    corners = {
        "┐": ("left", "down"), "┛": ("left", "up"),
        "┙": ("right", "up"), "┗": ("right", "up"),
        "┕": ("right", "up"), "┻": ("left_right", "up"),
    }
    if glyph in horizontal:
        return _rect_mask(0, 3, 8, 5)
    if glyph in vertical:
        return _rect_mask(3, 0, 5, 8)
    if glyph in corners:
        horizontal_part, vertical_part = corners[glyph]
        return tuple(
            ((3 <= y < 5) and (
                horizontal_part == "left_right" or
                (horizontal_part == "left" and x <= 4) or
                (horizontal_part == "right" and x >= 3)
            )) or ((3 <= x < 5) and (
                (vertical_part == "up" and y <= 4) or
                (vertical_part == "down" and y >= 3)
            ))
            for y in range(8)
            for x in range(8)
        )
    return full


def _visible_region_color(cell: Char, region: tuple[bool, ...]) -> str | None:
    """Choose the lower color actually present beneath an upper glyph region."""
    mask = _glyph_foreground_mask(cell.data)
    foreground, background = cell.fg, cell.bg
    if getattr(cell, "reverse", False):
        foreground, background = background, foreground
    counts: dict[str, int] = {}
    for include, foreground_pixel in zip(region, mask):
        if not include:
            continue
        color = foreground if foreground_pixel else background
        if color in {"default", "000000"} or len(color) != 6:
            continue
        counts[color] = counts.get(color, 0) + 1
    if not counts:
        return None
    return max(
        counts,
        key=lambda color: (
            counts[color],
            max(int(color[index:index + 2], 16) for index in (0, 2, 4)),
        ),
    )


def composite_bird_cell(upper: Char, lower: Char | None) -> Char:
    """Color-key black glyph regions against the actual lower sub-cell region."""
    if lower is None:
        return upper
    mask = _glyph_foreground_mask(upper.data)
    foreground_clear = upper.fg in {"default", "000000"}
    background_clear = upper.bg in {"default", "000000"}
    if foreground_clear and background_clear:
        return lower
    inherited_foreground = _visible_region_color(lower, mask) if foreground_clear else None
    inherited_background = _visible_region_color(
        lower, tuple(not pixel for pixel in mask),
    ) if background_clear else None
    return upper._replace(
        fg=inherited_foreground or upper.fg,
        bg=inherited_background or upper.bg,
    )


class GameRenderer:
    """Compose a GameWorld into sparse terminal cells."""

    def __init__(
        self,
        bird_frames: Sequence[Sequence[Sequence[Char]]],
        heart_sprites: Sequence[dict[tuple[int, int], Char]],
        leaf_cells: dict[tuple[int, int], Char],
        colored: Callable[[Char], bool],
    ):
        self.bird_frames = bird_frames
        self.heart_sprites = heart_sprites
        self.leaf_cells = leaf_cells
        self.colored = colored

    @staticmethod
    def _put(scene: dict[tuple[int, int], Char], x: int, y: int, cell: Char, width: int, height: int) -> None:
        # Rows 0 and height-1 belong exclusively to the HUD chrome. Preventing
        # animated scene cells from touching them removes the colored flashes
        # that occurred just before each status repaint.
        if 0 <= x < width and (height <= 2 or 1 <= y < height - 1):
            scene[(y, x)] = cell

    def _draw_bird(
        self,
        scene: dict[tuple[int, int], Char],
        world: GameWorld,
        x: float,
        y: float,
        facing: int,
        wing_position: float,
        hue_shift: float = 0.0,
    ) -> None:
        cx, cy = world.camera_cell
        x, y = round(x) - cx, round(y) - cy
        if world.compact:
            glyphs = "◆›" if facing > 0 else "‹◆"
            for offset, glyph in enumerate(glyphs):
                color = "00bfe8" if glyph == "◆" else "d52bb3"
                color = hue_shift_color(color, hue_shift)
                self._put(
                    scene, round(x) + offset, round(y),
                    Char(data=glyph, fg=color, bold=True), world.width, world.height,
                )
            return

        frame = self.bird_frames[int(wing_position) % len(self.bird_frames)]
        origin_x, origin_y = round(x), round(y)
        for local_y, row in enumerate(frame):
            for local_x, cell in enumerate(row):
                if not self.colored(cell):
                    continue
                if facing > 0:
                    draw_x, glyph = local_x, cell.data
                else:
                    draw_x, glyph = 31 - local_x, mirrored_character(cell.data)
                draw_cell = cell if glyph == cell.data else cell._replace(data=glyph)
                if hue_shift:
                    draw_cell = hue_shift_cell(draw_cell, hue_shift)
                target = (origin_y + local_y, origin_x + draw_x)
                draw_cell = composite_bird_cell(draw_cell, scene.get(target))
                self._put(
                    scene, origin_x + draw_x, origin_y + local_y,
                    draw_cell, world.width, world.height,
                )

    def scene(self, world: GameWorld, now: float) -> dict[tuple[int, int], Char]:
        scene: dict[tuple[int, int], Char] = {}
        width, height = world.width, world.height
        cx, cy = world.camera_cell
        if not world.playable:
            return scene

        back_effects, front_effects = self.effect_layers(world, now)
        scene.update(back_effects)

        if world.compact:
            for perch in world.leaves:
                for offset, glyph in enumerate("╱━╯"):
                    self._put(scene, perch.x + offset - cx, perch.y + 1 - cy, Char(data=glyph, fg="54d50a"), width, height)
        else:
            for index, perch in enumerate(world.leaves):
                for (local_x, local_y), cell in self.leaf_cells.items():
                    tint = perch_cell(cell, index == world.target_leaf)
                    self._put(scene, perch.x + local_x - cx, perch.y + local_y - cy, tint, width, height)

        for heart in world.hearts:
            if world.compact:
                pulse = (int((now + heart.phase_offset) * 6.0) % 2) == 0
                cell = Char(data="♥", fg="ff33ad" if pulse else "b51c86", bold=pulse)
                self._put(scene, heart.x - cx, heart.y - cy, cell, width, height)
            else:
                phase = int(((now * (1.0 / 3.0) + heart.phase_offset) % 1.0) * len(self.heart_sprites))
                for (local_x, local_y), cell in self.heart_sprites[phase].items():
                    self._put(scene, heart.x + local_x - cx, heart.y + local_y - cy, cell, width, height)

        for companion in world.companions:
            self._draw_bird(
                scene, world, companion.x, companion.y, companion.facing,
                companion.wing_position, companion.hue_shift,
            )

        scene.update(front_effects)

        self._draw_bird(
            scene, world, world.bird_x, world.bird_y, world.facing,
            world.wing_position,
        )
        return scene

    @staticmethod
    def effect_layers(world: GameWorld, now: float):
        """Screen-cell effects in the exact native order, also consumed by web."""
        back, front = {}, {}
        if not world.playable:
            return back, front
        cx, cy = world.camera_cell
        for spark in world.trail:
            GameRenderer._put(back, spark.x-cx, spark.y-cy, trail_cell(spark, now),
                              world.width, world.height)
        if now < world.reticle_until:
            GameRenderer._put(front, world.reticle_x, world.reticle_y, RETICLE_CELL,
                              world.width, world.height)
        return back, front
