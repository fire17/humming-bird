"""Create the release's vector masthead from the actual approved ANSI cells."""
from html import escape
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hummingbird_tui import ansi_grid, GAME_BIRD_CACHE, colored

out = Path(__file__).resolve().parents[1] / "assets"
out.mkdir(exist_ok=True)
grid = ansi_grid((GAME_BIRD_CACHE / "bird-00.ansi").read_text())
parts = ['<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="360" viewBox="0 0 1200 360">',
         '<rect width="1200" height="360" rx="24" fill="#080b16"/>',
         '<path d="M40 320H1160" stroke="#29324a"/>',
         '<g transform="translate(28 25)" font-family="Menlo,DejaVu Sans Mono,monospace" font-size="25">']
for y, row in enumerate(grid):
    for x, cell in enumerate(row):
        if not colored(cell):
            continue
        fg = '#' + cell.fg if len(cell.fg) == 6 else '#000000'
        bg = '#' + cell.bg if len(cell.bg) == 6 else '#000000'
        parts.append(f'<rect x="{x*10}" y="{y*24}" width="10" height="24" fill="{bg}"/>')
        parts.append(f'<text x="{x*10}" y="{y*24+21}" fill="{fg}">{escape(cell.data)}</text>')
parts.extend(['</g>', '<text x="450" y="128" fill="#f6f4ff" font-family="sans-serif" font-size="66" font-weight="700">Humming Bird</text>',
              '<text x="454" y="184" fill="#9aaac9" font-family="sans-serif" font-size="26">A little neon wilderness. Inside your terminal.</text>',
              '<text x="454" y="250" fill="#22d3ee" font-family="monospace" font-size="19">PLANT · PILOT · FLOCK · DRIFT</text>', '</svg>'])
(out / "banner.svg").write_text('\n'.join(parts))
(out / "favicon.svg").write_text('''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><path d="M8 4L33 29 45 23 63 26 46 29 29 47 8 62 22 37Z" fill="#b56add"/><path d="M22 37L29 47 8 62Z" fill="#00b9c9"/></svg>''')
