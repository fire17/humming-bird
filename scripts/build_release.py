"""Build a self-contained terminal app. Run on the target OS, not cross-compiled."""
import hashlib
import os
from pathlib import Path
import platform
import plistlib
import shutil
import subprocess
import sys
import tarfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"


def build():
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
                    "--name", "humming-bird", "--onedir", "--collect-data", "humming_bird_assets",
                    "--collect-data", "pyte", "hummingbird_cli.py"], cwd=ROOT, check=True)
    folder = DIST / "humming-bird"
    shutil.copy2(ROOT / "LICENSE", folder / "LICENSE")
    subprocess.run([str(folder / ("humming-bird.exe" if os.name == "nt" else "humming-bird")), "--check"], check=True)
    system = {"Darwin": "macos", "Windows": "windows", "Linux": "linux"}[platform.system()]
    arch = "arm64" if platform.machine().lower() in ("arm64", "aarch64") else "x86_64"
    name = f"humming-bird-{system}-{arch}"
    if system == "macos":
        app = DIST / "Humming Bird.app"
        # RGB art must run in a capable terminal, with an isolated app profile.
        subprocess.run(["osacompile", "-o", str(app),
                        str(ROOT / "packaging/macos-launcher.applescript")], check=True)
        for resource in ("launch-wezterm.sh", "humming-bird-wezterm.lua"):
            shutil.copy2(ROOT / "packaging" / resource, app / "Contents/Resources" / resource)
        shutil.copytree(folder, app / "Contents/Resources/humming-bird", dirs_exist_ok=True)
        iconset = DIST / "HummingBird.iconset"
        iconset.mkdir(exist_ok=True)
        for size in (16, 32, 128, 256, 512):
            for density in (1, 2):
                suffix = "@2x" if density == 2 else ""
                icon = iconset / f"icon_{size}x{size}{suffix}.png"
                subprocess.run(["sips", "-s", "format", "png", "-z", str(size * density),
                                str(size * density), str(ROOT / "assets/favicon.svg"),
                                "--out", str(icon)], check=True, stdout=subprocess.DEVNULL)
        subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o",
                        str(app / "Contents/Resources/HummingBird.icns")], check=True)
        info_path = app / "Contents/Info.plist"
        with info_path.open("rb") as stream:
            info = plistlib.load(stream)
        info.update(CFBundleIdentifier="io.github.fire17.humming-bird",
                    CFBundleName="Humming Bird", CFBundleShortVersionString="1.1.0",
                    CFBundleIconFile="HummingBird",
                    NSHighResolutionCapable=True)
        with info_path.open("wb") as stream:
            plistlib.dump(info, stream)
        subprocess.run(["codesign", "--force", "--deep", "--sign", "-", str(app)], check=True)
        target = DIST / (name + ".zip")
        subprocess.run(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(app), str(target)], check=True)
    elif system == "windows":
        target = DIST / (name + ".zip")
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
            for file in sorted(folder.rglob("*")):
                if file.is_file():
                    archive.write(file, file.relative_to(DIST))
    else:
        target = DIST / (name + ".tar.gz")
        with tarfile.open(target, "w:gz") as archive:
            archive.add(folder, arcname="humming-bird")
    checksum = hashlib.sha256(target.read_bytes()).hexdigest()
    (DIST / (target.name + ".sha256")).write_text(f"{checksum}  {target.name}\n")
    print(target)


if __name__ == "__main__":
    build()
