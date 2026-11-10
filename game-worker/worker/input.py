"""Per-session input injection through the XTEST extension of the session's own X display.

Why XTEST and not uinput?
  * /dev/uinput needs a kernel module + device access, which in Docker means
    --device /dev/uinput and usually extra capabilities. Events written to uinput
    are also *global*: every RetroArch instance on the host would see every pad
    unless udev rules separate them. That is exactly the cross-session leak we
    must avoid.
  * Each session already owns a private Xvfb display. Keys sent with XTEST to
    display :N can only reach the RetroArch process on :N. Isolation comes for free,
    no privileged container is needed.
  * Trade-off: XTEST gives digital buttons only (fine for NES/SNES/GB/MD/PS1 digital
    pad). Analog sticks need uinput or a libretro input hook later (see docs/feasibility.md).

The browser never sends key codes. It sends logical button names from a fixed
whitelist, so a client cannot press RetroArch hotkeys (menu, quit, save-state...).
"""
from __future__ import annotations

import threading

from Xlib import X, XK, display as xdisplay
from Xlib.ext import xtest

# logical button -> X keysym. Must match the bindings written in session.py (retroarch.cfg).
BUTTON_KEYSYMS: dict[str, str] = {
    "up": "Up",
    "down": "Down",
    "left": "Left",
    "right": "Right",
    "a": "x",
    "b": "z",
    "x": "s",
    "y": "a",
    "l": "q",
    "r": "w",
    "l2": "e",
    "r2": "r",
    "start": "Return",
    "select": "Shift_R",
}
# Bit order used by the web player for the compact "pad" message.
BUTTON_ORDER: list[str] = list(BUTTON_KEYSYMS)


class XInputInjector:
    def __init__(self, display_name: str) -> None:
        self._d = xdisplay.Display(display_name)
        self._lock = threading.Lock()
        self._pressed: set[str] = set()
        self._codes = {
            b: self._d.keysym_to_keycode(XK.string_to_keysym(ks)) for b, ks in BUTTON_KEYSYMS.items()
        }
        missing = [b for b, c in self._codes.items() if not c]
        if missing:
            raise RuntimeError(f"no keycode for {missing} on {display_name}")
        self.events = 0

    def focus_first_window(self) -> bool:
        """RetroArch's X input driver only reads the keyboard while its window has focus."""
        root = self._d.screen().root
        children = root.query_tree().children
        for w in children:
            try:
                if w.get_attributes().map_state == X.IsViewable:
                    self._d.set_input_focus(w, X.RevertToParent, X.CurrentTime)
                    self._d.sync()
                    return True
            except Exception:  # window vanished between query and use
                continue
        return False

    def set_button(self, button: str, down: bool) -> None:
        code = self._codes.get(button)
        if code is None:
            return  # silently drop anything not on the whitelist
        with self._lock:
            if down == (button in self._pressed):
                return
            xtest.fake_input(self._d, X.KeyPress if down else X.KeyRelease, code)
            self._d.sync()
            (self._pressed.add if down else self._pressed.discard)(button)
            self.events += 1

    def set_mask(self, mask: int) -> None:
        for i, b in enumerate(BUTTON_ORDER):
            self.set_button(b, bool(mask & (1 << i)))

    def release_all(self) -> None:
        for b in list(self._pressed):
            self.set_button(b, False)

    def close(self) -> None:
        try:
            self.release_all()
            self._d.close()
        except Exception:
            pass
