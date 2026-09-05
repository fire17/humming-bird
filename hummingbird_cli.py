"""Installed entry point; frozen multiprocessing dispatch precedes app imports."""
import multiprocessing
import sys


def main():
    multiprocessing.freeze_support()
    if "--version" in sys.argv:
        print("Humming Bird 1.1.0")
        return 0
    if "--studio" in sys.argv:
        sys.argv.remove("--studio")
    elif not any(arg in sys.argv for arg in ("--check", "--help", "-h")):
        sys.argv.append("--game")
    from hummingbird_tui import main as play
    return play()


if __name__ == "__main__":
    raise SystemExit(main())
