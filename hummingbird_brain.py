#!/usr/bin/env python3
"""One autonomous flight brain shared by the primary bird and every worker."""

from __future__ import annotations

from dataclasses import dataclass
import math
import random
from typing import Sequence


def visual_distance(dx: float, dy: float) -> float:
    """Terminal rows are visually taller than columns, so weight Y."""
    return math.hypot(dx, dy * 1.8)


def clamp(value: float, low: float, high: float) -> float:
    if high < low:
        return low
    return min(high, max(low, value))


def nectar_capture_time_scale(nectar_count: int, bird_count: int) -> float:
    """Scale sip time by 1/sqrt(nectar per bird), as requested."""
    if nectar_count <= 0:
        return 1.0
    return 1.0 / math.sqrt(nectar_count / max(1, bird_count))


@dataclass
class TargetMotionWatchdog:
    """Detect a bird that has nectar but is neither moving nor progressing."""

    target_id: int | None = None
    anchor_x: float = 0.0
    anchor_y: float = 0.0
    checked_at: float = 0.0
    best_distance: float = math.inf
    last_progress_at: float = 0.0

    def reset(self) -> None:
        self.target_id = None
        self.best_distance = math.inf

    def observe(
        self,
        target_id: int | None,
        x: float,
        y: float,
        distance: float,
        now: float,
        arrival_distance: float,
    ) -> bool:
        if target_id is None:
            self.reset()
            return False
        if target_id != self.target_id:
            self.target_id = target_id
            self.anchor_x, self.anchor_y = x, y
            self.checked_at = self.last_progress_at = now
            self.best_distance = distance
            return False
        if distance < self.best_distance - 0.20:
            self.best_distance = distance
            self.last_progress_at = now
        if now - self.checked_at < 0.45:
            return False
        movement = visual_distance(x - self.anchor_x, y - self.anchor_y)
        self.anchor_x, self.anchor_y = x, y
        self.checked_at = now
        outside = distance > arrival_distance + 0.15
        stalled = outside and movement < 0.30
        circling = outside and now - self.last_progress_at >= 1.20
        if stalled or circling:
            self.best_distance = distance
            self.last_progress_at = now
            return True
        return False


@dataclass(frozen=True)
class AutonomousResult:
    x: float
    y: float
    velocity_x: float
    velocity_y: float
    facing: int
    wing_position: float
    state: str
    collected_id: int | None
    recovering: bool


class AutonomousBirdBrain:
    """Stateful autonomous movement used identically by all hummingbirds."""

    def __init__(
        self,
        ident: int,
        rng: random.Random,
        *,
        frame_count: int = 60,
        bottom_frame: int = 30,
        x: float = 0.0,
        y: float = 0.0,
        facing: int = 1,
        wing_position: float | None = None,
        initialized: bool = False,
    ) -> None:
        self.ident = ident
        self.rng = rng
        self.frame_count = frame_count
        self.bottom_frame = bottom_frame
        self.x = x
        self.y = y
        self.velocity_x = 0.0
        self.velocity_y = 0.0
        self.facing = facing
        self.wing_position = rng.random() * frame_count if wing_position is None else wing_position
        self.initialized = initialized
        self.sip_target: int | None = None
        self.sip_until = 0.0
        self.recovery_until = 0.0
        self.watchdog = TargetMotionWatchdog()

    def sync_kinematics(
        self,
        x: float,
        y: float,
        velocity_x: float,
        velocity_y: float,
        facing: int,
        wing_position: float,
    ) -> None:
        """Adopt parent-owned pose changes without replacing brain state."""
        self.x = x
        self.y = y
        self.velocity_x = velocity_x
        self.velocity_y = velocity_y
        self.facing = facing
        self.wing_position = wing_position
        self.initialized = True

    def step(
        self,
        *,
        now: float,
        dt: float,
        width: int,
        compact: bool,
        play_top: int,
        play_bottom: int,
        count: int,
        primary_leaf: int,
        hearts: Sequence[tuple[int, float, float]],
        leaves: Sequence[tuple[float, float]],
        assigned_target: int | None,
        neighbors: Sequence[tuple[int, float, float, float, float]],
        calm: bool = False,
        extended_board: bool = False,
        view_origin: tuple[int, int] = (0, 0),
    ) -> AutonomousResult:
        dt = min(0.10, max(0.0, dt))
        if not self.initialized:
            self.x = ((self.ident - 0.35) * width / max(2, count)) - (1.0 if compact else 16.0)
            self.y = play_top + 1.0 + (self.ident % 3) * (1.0 if compact else 2.0)
            self.x += view_origin[0]
            self.y += view_origin[1]
            self.initialized = True

        collected_id: int | None = None
        state = "flying"
        if self.sip_target is not None:
            if not any(int(item[0]) == self.sip_target for item in hearts):
                self.sip_target = None
            elif now >= self.sip_until:
                collected_id = self.sip_target
                self.sip_target = None
            else:
                state = "sipping"

        target_x, target_y = self.x, self.y
        returning = False
        target_heart = next(
            (item for item in hearts if int(item[0]) == assigned_target),
            None,
        )
        if state != "sipping" and target_heart is not None:
            _, heart_x, heart_y = target_heart
            center_x = self.x + (1.0 if compact else 15.5)
            relative_x = float(heart_x) - center_x
            if abs(relative_x) > (1.0 if compact else 4.0):
                self.facing = 1 if relative_x > 0.0 else -1
            if compact:
                min_x, max_x = 0.0, max(0.0, width - 2.0)
                min_y, max_y = float(play_top), float(play_bottom)
                right_x, left_x = float(heart_x) - 2.0, float(heart_x) + 2.0
                target_y = clamp(float(heart_y), min_y, max_y)
            else:
                min_x, max_x = -5.0, max(-5.0, width - 27.0)
                min_y = float(play_top - 2)
                max_y = max(min_y, play_bottom - 9.0)
                right_x, left_x = float(heart_x) - 27.0, float(heart_x) + 1.0
                target_y = clamp(float(heart_y) - 5.0, min_y, max_y)
            target_x = right_x if self.facing > 0 else left_x
            if extended_board:
                min_x, max_x = -math.inf, math.inf
                min_y, max_y = -math.inf, math.inf
                target_y = float(heart_y) - (0.0 if compact else 5.0)
            alternate_x = left_x if self.facing > 0 else right_x
            if not min_x <= target_x <= max_x and min_x <= alternate_x <= max_x:
                self.facing *= -1
                target_x = alternate_x
            target_x = clamp(target_x, min_x, max_x)
        elif state != "sipping":
            returning = True
            available_perches = max(0, len(leaves) - 1)
            if self.ident - 1 <= available_perches and leaves:
                leaf = leaves[(primary_leaf + self.ident - 1) % len(leaves)]
                target_x, target_y = float(leaf[0]), float(leaf[1])
            else:
                slot = self.ident - 1
                target_x = (slot + 0.5) * width / max(1, count) - (1.0 if compact else 16.0)
                target_y = play_top + (slot % 3) * (1.0 if compact else 2.0)
                target_x += view_origin[0]
                target_y += view_origin[1]

        if state != "sipping":
            dx, dy = target_x - self.x, target_y - self.y
            distance = visual_distance(dx, dy)
            max_speed = 13.0 if calm else (17.0 if returning else 22.0)
            desired_speed = max_speed * min(1.0, distance / (6.0 if compact else 13.0))
            norm = max(0.001, math.hypot(dx, dy))
            desired_vx = dx / norm * desired_speed
            desired_vy = dy / norm * desired_speed

            nearby: list[tuple[float, float, float, float]] = []
            separation_x = separation_y = 0.0
            recovering = now < self.recovery_until
            for other_id, other_x, other_y, other_vx, other_vy in neighbors:
                if int(other_id) == self.ident:
                    continue
                away_x, away_y = self.x - float(other_x), self.y - float(other_y)
                neighbor_distance = visual_distance(away_x, away_y)
                radius = 6.0 if compact else 16.0
                if neighbor_distance < radius:
                    nearby.append((float(other_x), float(other_y), float(other_vx), float(other_vy)))
                    strength = (1.0 - neighbor_distance / radius) ** 2
                    magnitude = math.hypot(away_x, away_y)
                    if magnitude < 0.2:
                        away_x = 1.0 if self.ident < int(other_id) else -1.0
                        away_y, magnitude = 0.0, 1.0
                    separation_x += away_x / magnitude * strength
                    separation_y += away_y / magnitude * strength
            if nearby and not recovering:
                average_x = sum(item[0] for item in nearby) / len(nearby)
                average_y = sum(item[1] for item in nearby) / len(nearby)
                average_vx = sum(item[2] for item in nearby) / len(nearby)
                average_vy = sum(item[3] for item in nearby) / len(nearby)
                desired_vx += separation_x * 7.0
                desired_vy += separation_y * 4.5
                desired_vx += (average_vx - self.velocity_x) * 0.11
                desired_vy += (average_vy - self.velocity_y) * 0.09
                desired_vx += (average_x - self.x) * 0.025
                desired_vy += (average_y - self.y) * 0.018
            wave = math.sin(now * (3.3 + self.ident * 0.11) + self.ident) * min(0.8, distance * 0.035)
            desired_vx += (-dy / norm) * wave
            desired_vy += (dx / norm) * wave * 0.35
            response = 1.0 - math.exp(-(4.2 if calm else 5.6) * dt)
            self.velocity_x += (desired_vx - self.velocity_x) * response
            self.velocity_y += (desired_vy - self.velocity_y) * response
            self.x += self.velocity_x * dt
            self.y += self.velocity_y * dt

            if extended_board:
                pass  # World positions remain independent of viewport edges.
            elif compact:
                self.x = clamp(self.x, 0.0, max(0.0, width - 2.0))
                self.y = clamp(self.y, float(play_top), float(play_bottom))
            else:
                self.x = clamp(self.x, -5.0, max(-5.0, width - 27.0))
                self.y = clamp(self.y, float(play_top - 2), max(float(play_top - 2), play_bottom - 9.0))

            approach_distance = distance
            arrival_distance = 2.4 if compact else 3.4
            if target_heart is not None:
                if compact:
                    mouth_x = self.x + (2.0 if self.facing > 0 else 0.0)
                    mouth_y = self.y
                    nectar_distance = visual_distance(
                        float(target_heart[1]) + 0.5 - mouth_x,
                        float(target_heart[2]) - mouth_y,
                    )
                else:
                    mouth_x = self.x + (26.0 if self.facing > 0 else 5.0)
                    mouth_y = self.y + 5.5
                    nectar_distance = visual_distance(
                        float(target_heart[1]) + 2.5 - mouth_x,
                        float(target_heart[2]) + 0.5 - mouth_y,
                    )
                approach_distance = min(distance, nectar_distance)
                if self.watchdog.observe(
                    int(target_heart[0]), self.x, self.y, approach_distance,
                    now, arrival_distance,
                ):
                    kick_norm = max(0.001, math.hypot(dx, dy))
                    kick = 8.0 if compact else 13.0
                    side = 1.4 if self.ident % 2 else -1.4
                    self.velocity_x = dx / kick_norm * kick + (-dy / kick_norm) * side
                    self.velocity_y = dy / kick_norm * kick + (dx / kick_norm) * side * 0.45
                    self.recovery_until = now + 0.50
            else:
                self.watchdog.reset()
            speed = math.hypot(self.velocity_x, self.velocity_y)
            self.wing_position = (
                self.wing_position + (110.0 if speed > 7 else 76.0) * dt
            ) % self.frame_count

            if target_heart is not None and approach_distance <= arrival_distance and speed < 6.5:
                self.sip_target = int(target_heart[0])
                base_capture_time = self.rng.uniform(0.32, 0.62)
                self.sip_until = now + base_capture_time * nectar_capture_time_scale(
                    len(hearts), count,
                )
                self.velocity_x = self.velocity_y = 0.0
                state = "sipping"
            elif returning and distance < 0.7 and speed < 3.0:
                self.x, self.y = target_x, target_y
                self.velocity_x = self.velocity_y = 0.0
                self.wing_position = float(self.bottom_frame)
                state = "perched"

        if extended_board:
            pass
        elif compact:
            self.x = clamp(self.x, 0.0, max(0.0, width - 2.0))
            self.y = clamp(self.y, float(play_top), float(play_bottom))
        else:
            self.x = clamp(self.x, -5.0, max(-5.0, width - 27.0))
            self.y = clamp(self.y, float(play_top - 2), max(float(play_top - 2), play_bottom - 9.0))

        return AutonomousResult(
            self.x, self.y, self.velocity_x, self.velocity_y, self.facing,
            self.wing_position, state, collected_id, now < self.recovery_until,
        )
