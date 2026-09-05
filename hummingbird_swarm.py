#!/usr/bin/env python3
"""Asynchronous per-bird workers for the active terminal garden."""

from __future__ import annotations

from dataclasses import dataclass
import multiprocessing
from multiprocessing.connection import Connection
import random
from typing import Any

from hummingbird_brain import AutonomousBirdBrain, visual_distance
from hummingbird_game import RemoteBird


MAX_FLOCK_SIZE = 24


def bounded_flock_count(count: int) -> int:
    return max(1, min(MAX_FLOCK_SIZE, count))


def append_flock_digit(buffer: str, digit: str) -> str:
    candidate = (buffer + digit).lstrip("0") or "0"
    if buffer and int(candidate) > MAX_FLOCK_SIZE:
        return digit.lstrip("0") or "0"
    return candidate


@dataclass
class WorkerHandle:
    ident: int
    hue_shift: float
    connection: Connection
    process: multiprocessing.Process
    awaiting: bool = False
    latest: RemoteBird | None = None


def _worker_main(connection: Connection, ident: int, seed: int, hue_shift: float) -> None:
    """Own one companion's brain/physics; never touches terminal state."""
    rng = random.Random(seed)
    brain = AutonomousBirdBrain(ident, rng)

    try:
        while True:
            message = connection.recv()
            if message.get("op") == "stop":
                break
            result = brain.step(
                now=float(message["now"]),
                dt=float(message["dt"]),
                width=int(message["width"]),
                compact=bool(message["compact"]),
                play_top=int(message["play_top"]),
                play_bottom=int(message["play_bottom"]),
                count=int(message["count"]),
                primary_leaf=int(message["primary_leaf"]),
                hearts=tuple(message["hearts"]),
                leaves=tuple(message["leaves"]),
                assigned_target=message.get("target_id"),
                neighbors=tuple(message["neighbors"]),
                calm=bool(message.get("calm", False)),
                extended_board=bool(message.get("extended_board", False)),
                view_origin=tuple(message.get("view_origin", (0, 0))),
            )
            connection.send({
                "ident": ident,
                "x": result.x,
                "y": result.y,
                "facing": result.facing,
                "wing_position": result.wing_position,
                "hue_shift": hue_shift,
                "state": result.state,
                "collected_id": result.collected_id,
                "velocity_x": result.velocity_x,
                "velocity_y": result.velocity_y,
            })
    except (EOFError, BrokenPipeError, OSError):
        pass
    finally:
        connection.close()


class SwarmManager:
    """Non-blocking parent-side bridge to one spawned process per companion."""

    def __init__(self, rng: random.Random):
        self.rng = rng
        self.context = multiprocessing.get_context("spawn")
        self.workers: dict[int, WorkerHandle] = {}
        self.reservations: dict[int, int] = {}

    @property
    def count(self) -> int:
        return 1 + len(self.workers)

    def set_count(self, count: int) -> None:
        count = bounded_flock_count(count)
        desired = set(range(2, count + 1))
        for ident in sorted(set(self.workers) - desired, reverse=True):
            self._stop_worker(ident)
        used_hues = [0.0, *(worker.hue_shift for worker in self.workers.values())]
        for ident in sorted(desired - set(self.workers)):
            candidates = [self.rng.random() for _ in range(24)]
            hue = max(
                candidates,
                key=lambda candidate: min(
                    min(abs(candidate - old), 1.0 - abs(candidate - old))
                    for old in used_hues
                ),
            )
            used_hues.append(hue)
            parent, child = self.context.Pipe(duplex=True)
            process = self.context.Process(
                target=_worker_main,
                args=(child, ident, self.rng.randrange(1 << 30), hue),
                name=f"hummingbird-{ident}",
                daemon=True,
            )
            process.start()
            child.close()
            self.workers[ident] = WorkerHandle(ident, hue, parent, process)

    def _stop_worker(self, ident: int) -> None:
        worker = self.workers.pop(ident)
        self.reservations.pop(ident, None)
        try:
            if worker.process.is_alive():
                worker.connection.send({"op": "stop"})
        except (BrokenPipeError, EOFError, OSError):
            pass
        worker.process.join(timeout=0.35)
        if worker.process.is_alive():
            worker.process.terminate()
            worker.process.join(timeout=0.35)
        worker.connection.close()

    def prepare(self, world: Any) -> None:
        """Reserve each nectar for the closest eligible bird, then stay sticky."""
        live_hearts = {heart.ident: heart for heart in world.hearts}
        eligible = set(self.workers)
        if not world.player_mode:
            eligible.add(1)
        self.reservations = {
            bird_id: heart_id
            for bird_id, heart_id in self.reservations.items()
            if bird_id in eligible and heart_id in live_hearts
        }
        reserved_hearts = set(self.reservations.values())
        free_birds = eligible - set(self.reservations)
        free_hearts = set(live_hearts) - reserved_hearts

        positions: dict[int, tuple[float, float]] = {}
        if 1 in free_birds:
            positions[1] = world._bird_center()
        for ident in free_birds:
            worker = self.workers.get(ident)
            if worker is not None and worker.latest is not None:
                positions[ident] = (
                    worker.latest.x + (1.0 if world.compact else 15.5),
                    worker.latest.y + (0.0 if world.compact else 5.5),
                )

        candidates: list[tuple[float, int, int]] = []
        for bird_id, (bird_x, bird_y) in positions.items():
            for heart_id in free_hearts:
                heart = live_hearts[heart_id]
                heart_x = heart.x + (0.5 if world.compact else 2.5)
                heart_y = heart.y + (0.0 if world.compact else 0.5)
                candidates.append((visual_distance(heart_x - bird_x, heart_y - bird_y), bird_id, heart_id))
        for _, bird_id, heart_id in sorted(candidates):
            if bird_id in self.reservations or heart_id in reserved_hearts:
                continue
            self.reservations[bird_id] = heart_id
            reserved_hearts.add(heart_id)

        world.assigned_target_id = self.reservations.get(1) if not world.player_mode else None

    def update(self, world: Any, now: float, dt: float) -> None:
        for worker in tuple(self.workers.values()):
            if worker.awaiting and worker.connection.poll():
                try:
                    result = worker.connection.recv()
                except (EOFError, OSError):
                    self._stop_worker(worker.ident)
                    continue
                worker.awaiting = False
                worker.latest = RemoteBird(
                    ident=int(result["ident"]),
                    x=float(result["x"]),
                    y=float(result["y"]),
                    facing=int(result["facing"]),
                    wing_position=float(result["wing_position"]),
                    hue_shift=float(result["hue_shift"]),
                    state=str(result["state"]),
                    velocity_x=float(result["velocity_x"]),
                    velocity_y=float(result["velocity_y"]),
                )
                if result["collected_id"] is not None:
                    world.collect_companion(int(result["collected_id"]), worker.ident, now)

            if not worker.awaiting and worker.process.is_alive():
                neighbors = [
                    (1, world.bird_x, world.bird_y, world.velocity_x, world.velocity_y)
                ]
                neighbors.extend(
                    (
                        item.ident, item.x, item.y,
                        item.velocity_x, item.velocity_y,
                    )
                    for item in (
                        handle.latest for handle in self.workers.values()
                    )
                    if item is not None
                )
                payload = {
                    "op": "tick",
                    "now": now,
                    "dt": dt,
                    "width": world.width,
                    "compact": world.compact,
                    "play_top": world.play_top,
                    "play_bottom": world.play_bottom,
                    "count": self.count,
                    "primary_leaf": world.target_leaf,
                    "hearts": tuple((heart.ident, heart.x, heart.y) for heart in world.hearts),
                    "leaves": tuple((leaf.x, leaf.y) for leaf in world.leaves),
                    "target_id": self.reservations.get(worker.ident),
                    "neighbors": tuple(neighbors),
                    "calm": world.calm,
                    "extended_board": world.extended_board,
                    "view_origin": world.camera_cell,
                }
                try:
                    worker.connection.send(payload)
                    worker.awaiting = True
                except (BrokenPipeError, EOFError, OSError):
                    self._stop_worker(worker.ident)

        world.companions = [
            worker.latest
            for worker in sorted(self.workers.values(), key=lambda item: item.ident)
            if worker.latest is not None
        ]

    def close(self) -> None:
        for ident in sorted(tuple(self.workers), reverse=True):
            self._stop_worker(ident)
