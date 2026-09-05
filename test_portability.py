import os
import tempfile
import time
import unittest

from hummingbird_terminal import encode_key
from hummingbird_tui import split_enhanced_key_events


class InputTests(unittest.TestCase):
    def test_independent_holds_and_releases(self):
        payload = b"".join(encode_key(vk, char, down) for vk, char, down in
                           [(87, "w", True), (68, "d", True), (68, "d", False)])
        text, events, pending = split_enhanced_key_events(payload.decode())
        self.assertEqual(events, [("w", 1), ("d", 1), ("d", 3)])
        self.assertEqual((text, pending), ("", ""))

    def test_arrows_and_shifted_controls(self):
        for vk, key in ((38, "up"), (40, "down"), (37, "left"), (39, "right")):
            self.assertEqual(split_enhanced_key_events(encode_key(vk, "", True).decode())[1], [(key, 1)])
        self.assertEqual(split_enhanced_key_events(encode_key(78, "N", True).decode())[1], [("N", 1)])
        self.assertEqual(encode_key(87, "W", False), b"\x1b[119;1:3u")

    def test_studio_plain_input(self):
        self.assertEqual(encode_key(38, "", True, enhanced=False), b"\x1b[A")
        self.assertEqual(encode_key(78, "N", False, enhanced=False), b"")
        self.assertEqual(encode_key(187, "+", True, enhanced=False), b"+")

    @unittest.skipUnless(os.name == "nt", "Windows console API")
    def test_native_console_events_and_restore(self):
        import ctypes as C
        from ctypes import wintypes as W
        import hummingbird_terminal as terminal
        # CI may have redirected stdio. Give the test its own console, never a hook.
        kernel = terminal.kernel
        allocated = bool(kernel.AllocConsole())
        # Hosted runners retain redirected std handles even after AllocConsole.
        # Open the new console explicitly, then restore those redirected handles.
        kernel.CreateFileW.argtypes = [W.LPCWSTR, W.DWORD, W.DWORD, W.LPVOID, W.DWORD, W.DWORD, W.HANDLE]
        kernel.CreateFileW.restype = W.HANDLE
        kernel.SetStdHandle.argtypes = [W.DWORD, W.HANDLE]
        kernel.CloseHandle.argtypes = [W.HANDLE]
        saved_input, saved_output = kernel.GetStdHandle(-10), kernel.GetStdHandle(-11)
        input_handle = kernel.CreateFileW("CONIN$", 0xC0000000, 3, None, 3, 0, None)
        output_handle = kernel.CreateFileW("CONOUT$", 0xC0000000, 3, None, 3, 0, None)
        self.assertNotEqual(input_handle, W.HANDLE(-1).value)
        self.assertNotEqual(output_handle, W.HANDLE(-1).value)
        kernel.SetStdHandle(-10, input_handle)
        kernel.SetStdHandle(-11, output_handle)
        mode = W.DWORD()
        if not kernel.GetConsoleMode(input_handle, C.byref(mode)):
            self.fail("A Windows console could not be allocated for the integration test")
        reader = terminal.TerminalInput(0)
        kernel.WriteConsoleInputW.argtypes = [W.HANDLE, C.POINTER(terminal.InputRecord), W.DWORD, C.POINTER(W.DWORD)]
        try:
            reader.start()
            records = (terminal.InputRecord * 3)()
            for record, vk, down in zip(records, (87, 68, 68), (True, True, False)):
                record.kind = 1
                record.event.key.down = down
                record.event.key.repeat = 1
                record.event.key.vk = vk
                record.event.key.char.UnicodeChar = chr(vk + 32)
            written = W.DWORD()
            self.assertTrue(kernel.WriteConsoleInputW(input_handle, records, 3, C.byref(written)))
            payload = b""
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline and payload.count(b"u") < 3:
                payload += reader.read(128, 0.02, True)
            self.assertEqual(split_enhanced_key_events(payload.decode())[1], [("w", 1), ("d", 1), ("d", 3)])
        finally:
            reader.close()
            after = W.DWORD()
            kernel.GetConsoleMode(input_handle, C.byref(after))
            self.assertEqual(after.value, mode.value)
            kernel.SetStdHandle(-10, saved_input)
            kernel.SetStdHandle(-11, saved_output)
            kernel.CloseHandle(input_handle)
            kernel.CloseHandle(output_handle)
            if allocated:
                kernel.FreeConsole()


if __name__ == "__main__":
    unittest.main()
