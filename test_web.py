import hashlib
import json
import math
from pathlib import Path
import unittest
import zipfile

from web.bridge import BrowserGame
from hummingbird_brain import AutonomousBirdBrain
from hummingbird_game import GameWorld, GameRenderer, TrailSpark, trail_cell, perch_cell
from pyte.screens import Char


class WebEngineTests(unittest.TestCase):
    def test_movement_and_capture_effects_use_native_cells(self):
        game = BrowserGame(seed=17, settings=dict(auto_spawn=False, player_mode=True))
        game.command(dict(op='input', x=1, y=-1))
        for _ in range(12): game.tick()
        self.assertGreater(len(game.world.trail), 0)
        heart = game.world.hearts[0]
        game.world._collect(heart, game.now)
        self.assertEqual(sum(s.lifetime == .85 for s in game.world.trail), 5)
        state = game.snapshot()
        for layer, cells in zip(('back', 'front'), GameRenderer.effect_layers(game.world, game.now)):
            self.assertEqual(state['effects'][layer],
                             [[x,y,cell.data+':'+cell.fg] for (y,x),cell in cells.items()])
        self.assertIn('+', state['event_message'])

    def test_effect_fade_and_camera_clipping(self):
        spark = TrailSpark(30,20,0,.6)
        self.assertEqual([trail_cell(spark,t).fg for t in (0,.2,.4)],
                         ['00b9d7','086e91','173e69'])
        game = BrowserGame(seed=17)
        world = game.world
        world.camera_x, world.camera_y = 10,10
        world.trail = [spark, TrailSpark(-10,0,0), TrailSpark(30,10,0)]
        world.set_reticle(12,5,0)
        back,front = GameRenderer.effect_layers(world,.1)
        self.assertEqual(set(back),{(10,20)})
        self.assertEqual(set(front),{(5,12)})  # reticle is already screen-relative
        self.assertEqual(GameRenderer.effect_layers(world,.5)[1],{})
        self.assertEqual(perch_cell(Char(data='▀',fg='80c040',bg='00ff00'),False).fg,'409020')
        self.assertEqual(perch_cell(Char(data='▀',fg='80c040',bg='00ff00'),False).bg,'00ff00')

    def test_uses_native_engine_for_every_bird(self):
        game = BrowserGame(seed=17)
        self.assertIs(type(game.world), GameWorld)
        self.assertIs(type(game.world.autonomous_brain), AutonomousBirdBrain)
        self.assertTrue(all(type(brain) is AutonomousBirdBrain for brain in game.brains.values()))

    def test_busy_flock_collects_and_stays_finite(self):
        game = BrowserGame(160, 48, dict(flock_count=24, nectar_limit=60, nectar_refill=True), seed=17)
        for _ in range(600):
            state = game.tick()
            self.assertEqual(len(state['birds']), 24)
            for bird in state['birds']:
                self.assertTrue(all(math.isfinite(bird[key]) for key in ('x','y','wing_position')))
            self.assertEqual(len(set(game.reservations.values())), len(game.reservations))
        self.assertGreater(state['collected'], 10)

    def test_pause_resume_and_resize(self):
        game = BrowserGame(seed=42)
        game.tick()
        game.apply_settings(dict(paused=True))
        before = game.snapshot()
        for _ in range(10):
            self.assertEqual(game.tick(), before)
        game.command(dict(op='resize', width=80,height=60))
        self.assertEqual(game.world.width,80)
        game.apply_settings(dict(paused=False))
        self.assertGreater(game.tick()['time'],before['time'])

    def test_pilot_multikey_and_release(self):
        game = BrowserGame(settings=dict(player_mode=True),seed=42)
        game.command(dict(op='input',x=1,y=-1))
        for _ in range(10): game.tick()
        self.assertGreater(game.world.velocity_x,0)
        self.assertLess(game.world.velocity_y,0)
        game.command(dict(op='input',x=-1,y=0))
        game.tick()
        self.assertEqual(game.world.facing,-1)
        game.command(dict(op='input',x=0,y=0))

    def test_settings_are_bounded_and_malformed_storage_is_ignored(self):
        game=BrowserGame(settings=['bad'])
        game.apply_settings(dict(flock_count=1000,nectar_limit=1000))
        self.assertEqual(game.settings()['flock_count'],24)
        self.assertEqual(game.settings()['nectar_limit'],60)
        game.apply_settings(dict(flock_count=float('nan')))
        game.set_count(1)
        self.assertEqual(len(game.tick()['birds']),1)

    def test_exported_engine_is_byte_identical(self):
        root=Path(__file__).parent
        if not (root/'web-dist/engine.zip').exists():
            self.skipTest('Run bun run build for export integration coverage')
        metadata=json.loads((root/'web-dist/assets.json').read_text())
        with zipfile.ZipFile(root/'web-dist/engine.zip') as archive:
            for name,digest in metadata['hashes'].items():
                if name.endswith('.py'):
                    data=(root/name).read_bytes()
                    self.assertEqual(archive.read(Path(name).name),data)
                    self.assertEqual(hashlib.sha256(data).hexdigest(),digest)


if __name__=='__main__': unittest.main()
