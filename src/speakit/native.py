"""In-process replacements for helper programs (hyprctl, playerctl, ydotool,
pkill). Each of those costs ~40-55 ms per spawn; these cost ~1 ms."""
from __future__ import annotations

import fcntl
import json
import os
import signal
import socket
import struct
import time
from pathlib import Path

# --- Hyprland IPC -----------------------------------------------------------------
def hypr(request: str) -> bytes:
    """One request on Hyprland's command socket (what hyprctl sends)."""
    base = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")) / "hypr"
    sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE") or next(base.iterdir()).name
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        s.connect(str(base / sig / ".socket.sock"))
        s.sendall(request.encode())
        out = b""
        while chunk := s.recv(65536):
            out += chunk
    return out


def active_window() -> dict:
    try:
        return json.loads(hypr("j/activewindow") or b"{}")
    except (OSError, ValueError, StopIteration):
        return {}


# --- MPRIS over D-Bus -------------------------------------------------------------
_bus = None


def _dbus():
    global _bus
    if _bus is None:
        from jeepney.io.blocking import open_dbus_connection
        _bus = open_dbus_connection(bus="SESSION")
    return _bus


def _call(msg):
    from jeepney import DBusErrorResponse
    try:
        return _dbus().send_and_get_reply(msg, timeout=1).body
    except (DBusErrorResponse, OSError, TimeoutError):
        return None


FADE_STEPS = 12


def _fade(players: list, start: float, end: float, seconds: float) -> None:
    """Ramp each player's MPRIS Volume from start to end (fractions of its own level).
    Players that don't take Volume writes (Firefox, some browsers) just stay put."""
    from jeepney import Properties
    for i in range(1, FADE_STEPS + 1):
        for addr, vol in players:
            if vol:
                _call(Properties(addr).set("Volume", "d", vol * (start + (end - start) * i / FADE_STEPS)))
        time.sleep(seconds / FADE_STEPS)


def mpris(action: str, players: list | None = None, fade: float = 0.3) -> list:
    """action "pause": fade out and pause every Playing player; return
    [(address, volume)] for "play", which fades them back in.
    Blocking for `fade` seconds: call it off the main thread."""
    from jeepney import DBusAddress, Properties, new_method_call
    from jeepney.bus_messages import message_bus
    if action == "play":
        players = [p for p in players or [] if _call(new_method_call(p[0], "Play")) is not None]
        _fade(players, 0.0, 1.0, fade)
        return players
    listed = _call(message_bus.ListNames()) or ([],)
    players = []
    for n in listed[0]:
        if not n.startswith("org.mpris.MediaPlayer2."):
            continue
        addr = DBusAddress("/org/mpris/MediaPlayer2", bus_name=n, interface="org.mpris.MediaPlayer2.Player")
        st = _call(Properties(addr).get("PlaybackStatus"))
        if st and st[0][1] == "Playing":
            vol = _call(Properties(addr).get("Volume"))
            players.append((addr, vol[0][1] if vol else None))
    _fade(players, 1.0, 0.0, fade)
    # Volume stays at 0 while paused: players pause asynchronously, so restoring it
    # here plays a blip of buffered audio at full level. The resume fade restores it.
    # ponytail: a crash mid-recording leaves the player at 0; restore on startup if that bites.
    return [p for p in players if _call(new_method_call(p[0], "Pause")) is not None]


# --- waybar signal ----------------------------------------------------------------
def signal_waybar(n: int) -> None:
    """pkill -RTMIN+n waybar, without spawning pkill."""
    for p in Path("/proc").iterdir():
        if p.name.isdigit():
            try:
                if (p / "comm").read_text().strip() == "waybar":
                    os.kill(int(p.name), signal.SIGRTMIN + n)
            except (OSError, ValueError):
                pass


# --- virtual keyboard (uinput) ----------------------------------------------------
EV_SYN, EV_KEY = 0, 1
SHIFT, ENTER, CTRL = 42, 28, 29
_US = {**{c: k for c, k in zip("1234567890-=", range(2, 14))},
       **{c: k for c, k in zip("qwertyuiop[]", range(16, 28))},
       **{c: k for c, k in zip("asdfghjkl;'`", range(30, 42))},
       **{c: k for c, k in zip("zxcvbnm,./", range(44, 54))},
       "\\": 43, " ": 57, "\t": 15, "\n": ENTER}
_SHIFTED = dict(zip('!@#$%^&*()_+{}:"~<>?|', "1234567890-=[];'`,./\\"))


def keycode(ch: str) -> tuple[int, bool] | None:
    """(code, needs_shift) on a US layout; None if the key doesn't exist."""
    if ch in _US:
        return _US[ch], False
    if ch.isascii() and ch.isupper():
        return _US[ch.lower()], True
    if ch in _SHIFTED:
        return _US[_SHIFTED[ch]], True
    return None


class Keyboard:
    """A uinput keyboard (what ydotoold provides, minus the daemon). Needs
    write access to /dev/uinput (udev uaccess rule from install.sh)."""

    def __init__(self) -> None:
        self.fd = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)
        fcntl.ioctl(self.fd, 0x40045564, EV_KEY)          # UI_SET_EVBIT
        for code in range(1, 120):
            fcntl.ioctl(self.fd, 0x40045565, code)        # UI_SET_KEYBIT
        setup = struct.pack("<4H80sI", 0x06, 0x5350, 0x4B54, 1, b"speakit virtual keyboard", 0)
        fcntl.ioctl(self.fd, 0x405C5503, setup)           # UI_DEV_SETUP
        fcntl.ioctl(self.fd, 0x5501)                      # UI_DEV_CREATE

    def _emit(self, code: int, value: int) -> None:
        os.write(self.fd, struct.pack("<qqHHi", 0, 0, EV_KEY, code, value) + struct.pack("<qqHHi", 0, 0, EV_SYN, 0, 0))

    def combo(self, *codes: int, hold: float = 0.001) -> None:
        for c in codes:
            self._emit(c, 1)
        time.sleep(hold)
        for c in reversed(codes):
            self._emit(c, 0)

    def type(self, text: str, delay_ms: float = 0, hold_ms: float = 1) -> None:
        """Type ASCII text (others skipped; non-ASCII goes via paste)."""
        for ch in text:
            k = keycode(ch)
            if k is None:
                continue
            self.combo(*((SHIFT, k[0]) if k[1] else (k[0],)), hold=hold_ms / 1000)
            if delay_ms:
                time.sleep(delay_ms / 1000)


if __name__ == "__main__":
    assert keycode("a") == (30, False) and keycode("A") == (30, True)
    assert keycode("?") == (53, True) and keycode("`") == (41, False) and keycode("~") == (41, True)
    assert keycode("\\") == (43, False) and keycode("|") == (43, True) and keycode("é") is None
    assert all(keycode(c) for c in "The quick brown fox: 1+1=2, [ok] {x} <y> \"q\" 50% #tag @me ~/a_b|c;")
    print("ok")
