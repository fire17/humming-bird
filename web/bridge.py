"""Thin browser host for the exact native GameWorld and AutonomousBirdBrain.

No duplicate physics/AI. One browser worker owns all birds; the main thread paints.
"""
import json
import math
import random
from dataclasses import asdict

from hummingbird_brain import AutonomousBirdBrain
from hummingbird_flock import assign_targets, step_brain
from hummingbird_game import GameWorld, GameRenderer, RemoteBird


class BrowserGame:
    def __init__(self, width=120, height=40, settings=None, seed=None):
        self.rng = random.Random(seed)
        self.now = 0.0
        self.world = GameWorld(width, height, self.now, self.rng)
        self.brains = {}
        self.peers = {}
        self.hues = {}
        self.reservations = {}
        self.paused = False
        self.set_count(3)
        self.world.toggle_auto(0)
        for _ in range(7):
            self.world.plant_random(0)
        self.apply_settings(settings or {})

    def set_count(self, count):
        count = max(1, min(24, int(count)))
        for ident in list(self.brains):
            if ident > count:
                del self.brains[ident]
                self.peers.pop(ident, None)
                self.hues.pop(ident, None)
        for ident in range(2, count + 1):
            if ident not in self.brains:
                self.brains[ident] = AutonomousBirdBrain(ident, random.Random(self.rng.randrange(1 << 30)))
                used = [0.0, *self.hues.values()]
                self.hues[ident] = max((self.rng.random() for _ in range(24)),
                    key=lambda c: min(min(abs(c-old), 1-abs(c-old)) for old in used))
                self.peers[ident] = None
        self.world.companions = [p for p in self.peers.values() if p is not None]

    def settings(self):
        w = self.world
        return dict(flock_count=len(self.brains)+1, nectar_limit=w.nectar_limit_setting,
                    player_mode=w.player_mode, auto_spawn=w.auto_spawn,
                    nectar_refill=w.nectar_refill, gravity_assist=w.gravity_assist,
                    calm=w.calm, extended_board=w.extended_board, paused=self.paused)

    def apply_settings(self, values):
        if not isinstance(values, dict):
            return
        toggles = dict(player_mode="toggle_player", auto_spawn="toggle_auto",
                       nectar_refill="toggle_nectar_refill", gravity_assist="toggle_gravity_assist",
                       calm="toggle_calm", extended_board="toggle_extended_board")
        if isinstance(values.get("flock_count"), (int, float)) and math.isfinite(values["flock_count"]):
            self.set_count(values["flock_count"])
        if isinstance(values.get("nectar_limit"), (int, float)) and math.isfinite(values["nectar_limit"]):
            self.world.nectar_limit_setting = max(1, min(60, int(values["nectar_limit"])))
        for key, method in toggles.items():
            if isinstance(values.get(key), bool) and values[key] != getattr(self.world, key):
                getattr(self.world, method)(self.now)
        if isinstance(values.get("paused"), bool):
            self.paused = values["paused"]
        if self.world.nectar_refill:
            self.world._maintain_nectar(self.now)

    def command(self, message):
        op = message.get("op")
        w = self.world
        if op == "input":
            w.set_player_input(int(message.get("x", 0)), int(message.get("y", 0)))
        elif op == "resize":
            w.resize(int(message["width"]), int(message["height"]), self.now)
        elif op == "plant":
            w.plant(int(message["x"]), int(message["y"]), self.now)
        elif op == "scatter":
            w.plant_random(self.now)
        elif op == "clear":
            w.clear_hearts(self.now)
        elif op == "settings":
            self.apply_settings(message.get("values", {}))

    def tick(self, dt=1/30):
        w = self.world
        dt = min(0.1, max(0, dt))
        if not self.paused:
            self.now += dt
            self.reservations = assign_targets(w, self.peers, self.reservations)
            w.update(self.now, dt)
            neighbors = [(1, w.bird_x, w.bird_y, w.velocity_x, w.velocity_y)]
            neighbors.extend((p.ident, p.x, p.y, p.velocity_x, p.velocity_y)
                             for p in self.peers.values() if p is not None)
            for ident, brain in self.brains.items():
                result = step_brain(brain, dict(
                    now=self.now, dt=dt, width=w.width, compact=w.compact,
                    play_top=w.play_top, play_bottom=w.play_bottom, count=len(self.brains)+1,
                    primary_leaf=w.target_leaf, hearts=tuple((h.ident,h.x,h.y) for h in w.hearts),
                    leaves=tuple((leaf.x,leaf.y) for leaf in w.leaves),
                    target_id=self.reservations.get(ident), neighbors=tuple(neighbors),
                    calm=w.calm, extended_board=w.extended_board, view_origin=w.camera_cell))
                self.peers[ident] = RemoteBird(ident, result.x, result.y, result.facing,
                    result.wing_position, self.hues[ident], result.state,
                    result.velocity_x, result.velocity_y)
                if result.collected_id is not None:
                    w.collect_companion(result.collected_id, ident, self.now)
            w.companions = list(self.peers.values())
        return self.snapshot()

    def snapshot(self):
        w = self.world
        back, front = GameRenderer.effect_layers(w, self.now)
        effects = {name: [[column, row, cell.data + ':' + cell.fg]
                         for (row, column), cell in layer.items()]
                   for name, layer in (('back', back), ('front', front))}
        birds = [asdict(p) for p in self.peers.values() if p is not None]
        birds.append(dict(ident=1, x=w.bird_x, y=w.bird_y, facing=w.facing,
            wing_position=w.wing_position, hue_shift=0, state=w.state,
            velocity_x=w.velocity_x, velocity_y=w.velocity_y))
        return dict(time=self.now, width=w.width, height=w.height, camera=w.camera_cell,
                    birds=birds, hearts=[asdict(h) for h in w.hearts],
                    leaves=[asdict(leaf) for leaf in w.leaves], target_leaf=w.target_leaf,
                    trail=[asdict(spark) for spark in w.trail], effects=effects, score=w.score,
                    combo=w.combo, collected=w.collected, heart_limit=w.heart_limit,
                    compact=w.compact, message=w.status(self.now)[1],
                    event_message=w.message if self.now < w.message_until else '', settings=self.settings())


game = None

def start(payload):
    global game
    game = BrowserGame(**json.loads(payload))
    return json.dumps(game.snapshot())

def command(payload):
    game.command(json.loads(payload))
    return json.dumps(game.snapshot())

def tick(dt):
    return json.dumps(game.tick(dt))
