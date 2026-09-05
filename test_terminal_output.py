import inspect
import random
import unittest
from unittest.mock import patch
from pyte.screens import Char
import hummingbird_tui as tui
from hummingbird_colors import ColorEncoder
from hummingbird_game import GameWorld


class OutputIntegrationTests(unittest.TestCase):
    def test_garden_and_studio_adapt_at_output_only(self):
        frames, _ = tui.load_frames()
        original=frames[0][0]
        for mode in ('truecolor','256','16'):
            with self.subTest(mode=mode), patch.object(tui,'OUTPUT_COLORS',ColorEncoder(mode)), \
                    patch.object(tui.os,'write') as write, patch.object(tui.sys,'stdout'):
                world=GameWorld(80,30,0,random.Random(1))
                tui.draw_game({(3,4):Char(data='▀',fg='fc24b9',bg='000000')}, {},world,0,False,True)
                garden=write.call_args.args[1].decode()
                values={name:False for name in inspect.signature(tui.draw).parameters}
                values.update(frame=original,leaf_overlay='',display_fps=30,motion_fps=150,
                    actual_fps=30,anchor=1,frame_index=0,frame_count=60,phase_name='TOP',
                    heart_rps=1/3,heart_phase=0,sim_speed_level=9,landing_state='flying',
                    perch_mode='continuous',landing_duration=1,flutter_level=None,flutter_step=5)
                tui.draw(**values)
                studio=write.call_args.args[1].decode()
                for payload in (garden,studio):
                    if mode=='truecolor': self.assertIn('38;2;',payload)
                    else:
                        self.assertNotIn('38;2;',payload)
                        self.assertNotIn('48;2;',payload)
                        if mode=='16': self.assertNotIn('38;5;',payload)
                self.assertEqual(frames[0][0],original)
