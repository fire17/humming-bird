"""Terminal input boundary: POSIX tty or native Windows console events.

Windows key releases become the same events the game's Kitty parser consumes.
No global keyboard hook, shell profile edits, or third-party terminal required.
"""
from __future__ import annotations

import os
import sys


def encode_key(vk: int, char: str, down: bool, repeat: int = 1,
               enhanced: bool = True) -> bytes:
    arrows = {0x26: (57352, "A"), 0x28: (57353, "B"),
              0x27: (57354, "C"), 0x25: (57355, "D")}
    if enhanced:
        # Virtual keys are stable across Shift changes during a held movement.
        code = arrows[vk][0] if vk in arrows else (
            vk + 32 if vk in (65, 68, 83, 87) else ord(char) if char else 0)
        if not code:
            return b""
        event = 1 if down else 3
        modifier = 2 if char and char.isupper() and vk not in (65, 68, 83, 87) else 1
        return f"\x1b[{code};{modifier}:{event}u".encode("utf-8")
    if not down:
        return b""
    text = "\x1b[" + arrows[vk][1] if vk in arrows else char
    return (text * max(1, min(repeat, 32))).encode("utf-8")


if os.name == "nt":
    import ctypes as C
    from ctypes import wintypes as W

    class Coord(C.Structure):
        _fields_ = [("X", W.SHORT), ("Y", W.SHORT)]

    class KeyChar(C.Union):
        _fields_ = [("UnicodeChar", W.WCHAR), ("AsciiChar", C.c_char)]

    class KeyEvent(C.Structure):
        _fields_ = [("down", W.BOOL), ("repeat", W.WORD), ("vk", W.WORD),
                    ("scan", W.WORD), ("char", KeyChar), ("control", W.DWORD)]

    class MouseEvent(C.Structure):
        _fields_ = [("position", Coord), ("buttons", W.DWORD),
                    ("control", W.DWORD), ("flags", W.DWORD)]

    class EventUnion(C.Union):
        _fields_ = [("key", KeyEvent), ("mouse", MouseEvent),
                    ("padding", C.c_byte * 16)]

    class InputRecord(C.Structure):
        _fields_ = [("kind", W.WORD), ("event", EventUnion)]

    kernel = C.WinDLL("kernel32", use_last_error=True)
    kernel.GetStdHandle.argtypes = [W.DWORD]
    kernel.GetStdHandle.restype = W.HANDLE
    kernel.GetConsoleMode.argtypes = [W.HANDLE, C.POINTER(W.DWORD)]
    kernel.SetConsoleMode.argtypes = [W.HANDLE, W.DWORD]
    kernel.WaitForSingleObject.argtypes = [W.HANDLE, W.DWORD]
    kernel.ReadConsoleInputW.argtypes = [W.HANDLE, C.POINTER(InputRecord), W.DWORD, C.POINTER(W.DWORD)]


class TerminalInput:
    def __init__(self, fd: int):
        self.fd = fd
        self.active = False
        self.buttons = 0

    def start(self) -> None:
        if os.name != "nt":
            import termios
            import tty
            self.saved = termios.tcgetattr(self.fd)
            tty.setcbreak(self.fd)
            self.active = True
            return
        self.input = kernel.GetStdHandle(-10)
        self.output = kernel.GetStdHandle(-11)
        self.saved_in, self.saved_out = W.DWORD(), W.DWORD()
        if not kernel.GetConsoleMode(self.input, C.byref(self.saved_in)) or not kernel.GetConsoleMode(self.output, C.byref(self.saved_out)):
            raise OSError("Use Windows Terminal or a native PowerShell console, not an output pane.")
        self.saved_cp = kernel.GetConsoleOutputCP()
        self.active = True
        try:
            # Process Ctrl+C; receive mouse and resize; disable QuickEdit/VT input.
            if not kernel.SetConsoleMode(self.input, 0x0001 | 0x0008 | 0x0010 | 0x0080):
                raise C.WinError(C.get_last_error())
            if not kernel.SetConsoleMode(self.output, self.saved_out.value | 0x0004):
                raise OSError("This console does not support ANSI output. Use Windows Terminal.")
            kernel.SetConsoleOutputCP(65001)
            import msvcrt
            msvcrt.setmode(sys.stdout.fileno(), os.O_BINARY)
        except Exception:
            self.close()
            raise

    def read(self, size: int, timeout: float, enhanced: bool = False) -> bytes:
        if os.name != "nt":
            import select
            ready, _, _ = select.select([self.fd], [], [], timeout)
            return os.read(self.fd, size) if ready else b""
        if kernel.WaitForSingleObject(self.input, max(0, int(timeout * 1000))) != 0:
            return b""
        records = (InputRecord * 32)()
        count = W.DWORD()
        if not kernel.ReadConsoleInputW(self.input, records, 32, C.byref(count)):
            raise C.WinError(C.get_last_error())
        result = bytearray()
        for record in records[:count.value]:
            if record.kind == 1:
                key = record.event.key
                char = key.char.UnicodeChar
                # UTF-16 surrogates cannot be independently UTF-8 encoded.
                if char and (ord(char) == 0 or 0xD800 <= ord(char) <= 0xDFFF):
                    char = ""
                result.extend(encode_key(key.vk, char, bool(key.down), key.repeat, enhanced))
            elif record.kind == 2 and enhanced:
                mouse = record.event.mouse
                left = mouse.buttons & 1
                if left != (self.buttons & 1) or mouse.flags == 2:
                    action = "M" if left else "m"
                    result.extend(f"\x1b[<0;{mouse.position.X + 1};{mouse.position.Y + 1}{action}".encode())
                self.buttons = mouse.buttons
        return bytes(result)

    def close(self) -> None:
        if not self.active:
            return
        self.active = False
        if os.name == "nt":
            kernel.SetConsoleMode(self.input, self.saved_in)
            kernel.SetConsoleMode(self.output, self.saved_out)
            kernel.SetConsoleOutputCP(self.saved_cp)
        else:
            import termios
            termios.tcsetattr(self.fd, termios.TCSADRAIN, self.saved)


_input: TerminalInput | None = None


def read_input(fd: int, size: int, timeout: float, enhanced: bool = False) -> bytes:
    if _input is None:
        raise RuntimeError("Terminal input not started")
    return _input.read(size, timeout, enhanced)


def start_input(fd: int) -> TerminalInput:
    global _input
    _input = TerminalInput(fd)
    _input.start()
    return _input
