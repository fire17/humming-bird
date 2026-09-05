"""Build browser assets directly from the approved native art and engine."""
import hashlib
import importlib
import importlib.metadata
import json
from pathlib import Path
import struct
import sys
import zipfile
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from hummingbird_tui import load_frames, load_game_assets, load_leaf_overlays
from hummingbird_game import _glyph_foreground_mask, FRAME_COUNT, SPEED_STEPS


def main():
    out = ROOT / "web-dist"
    out.mkdir(exist_ok=True)
    frames, _ = load_frames()
    birds, hearts, leaf = load_game_assets(frames, load_leaf_overlays(frames))
    sprites = [{(x, y): cell for y, row in enumerate(frame) for x, cell in enumerate(row)}
               for frame in birds] + list(hearts) + [leaf]
    width, height = 2560, ((len(sprites) + 9) // 10) * 96
    pixels = bytearray(width * height * 4)
    for index, sprite in enumerate(sprites):
        ox, oy = index % 10 * 256, index // 10 * 96
        for (x, y), cell in sprite.items():
            mask = _glyph_foreground_mask(cell.data)
            for bit, foreground in enumerate(mask):
                color = cell.fg if foreground else cell.bg
                if len(color) != 6 or color == "000000":
                    continue
                rgba = bytes.fromhex(color) + b"\xff"
                offset = ((oy + y*8 + bit//8)*width + ox + x*8 + bit%8)*4
                pixels[offset:offset+4] = rgba
    def chunk(kind, data):
        return struct.pack("!I", len(data)) + kind + data + struct.pack("!I", zlib.crc32(kind+data))
    rows = b"".join(b"\0" + pixels[y*width*4:(y+1)*width*4] for y in range(height))
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack("!2I5B", width, height, 8, 6, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(rows, 9)) + chunk(b"IEND", b"")
    (out / "atlas.png").write_bytes(png)
    hashes = {}
    with zipfile.ZipFile(out / "engine.zip", "w", zipfile.ZIP_DEFLATED) as bundle:
        for name in ("hummingbird_game.py", "hummingbird_brain.py", "hummingbird_flock.py", "web/bridge.py"):
            data = (ROOT/name).read_bytes()
            bundle.writestr(Path(name).name, data)
            hashes[name] = hashlib.sha256(data).hexdigest()
        for package in ("pyte", "wcwidth"):
            base = Path(importlib.import_module(package).__file__).parent
            for path in sorted(base.rglob("*.py")):
                bundle.write(path, f"{package}/{path.relative_to(base)}")
            distribution = importlib.metadata.distribution(package)
            for entry in distribution.files or []:
                if "LICENSE" in str(entry).upper() or "COPYING" in str(entry).upper():
                    bundle.write(distribution.locate_file(entry), f"licenses/{package}/{Path(entry).name}")
    hashes["atlas.png"] = hashlib.sha256(png).hexdigest()
    build = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()[:12]
    (out / "assets.json").write_text(json.dumps(dict(
        build=build, hashes=hashes, frames=FRAME_COUNT, hearts=len(hearts), leaf=len(sprites)-1,
        atlasWidth=width, atlasHeight=height, tileWidth=256, tileHeight=96, speedSteps=SPEED_STEPS)))
    print(f"Exported {len(sprites)} exact native sprites; engine {build}")


if __name__ == "__main__":
    main()
