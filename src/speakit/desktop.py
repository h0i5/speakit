"""Desktop glue: media pause, cue sounds, focused window, clipboard paste/copy."""
from __future__ import annotations

import json
import subprocess
import time
import wave
from pathlib import Path

TERMINALS = {"kitty", "foot", "alacritty", "wezterm", "org.wezfurlong.wezterm",
             "ghostty", "com.mitchellh.ghostty", "konsole", "xterm"}

# Linux input keycodes for ydotool.
CTRL, SHIFT, C, V = 29, 42, 46, 47


def _run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=False, capture_output=True, timeout=3, **kw)


def _copy(data: bytes, mime: str = "text/plain;charset=utf-8") -> None:
    # wl-copy forks a child that serves the clipboard; with captured pipes
    # run() would wait for that child forever, so discard its output.
    subprocess.run(["wl-copy", "--type", mime], input=data, check=False, timeout=3,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# --- focused window ------------------------------------------------------------
def active_window() -> tuple[str, str]:
    """(class, title) of the focused window, lowercased; empty if unknown."""
    try:
        w = json.loads(_run(["hyprctl", "activewindow", "-j"]).stdout or b"{}")
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return "", ""
    return str(w.get("class", "")).lower(), str(w.get("title", "")).lower()


def is_terminal(cls: str) -> bool:
    return cls in TERMINALS


# --- media ----------------------------------------------------------------------
def pause_media() -> list[str]:
    """Pause every MPRIS player that is playing; return their names to resume."""
    try:
        out = _run(["playerctl", "-a", "metadata", "--format", "{{playerInstance}} {{status}}"]).stdout.decode()
    except (OSError, subprocess.TimeoutExpired):
        return []
    playing = [line.split()[0] for line in out.splitlines() if line.endswith(" Playing")]
    for p in playing:
        _run(["playerctl", "-p", p, "pause"])
    return playing


def resume_media(players: list[str]) -> None:
    for p in players:
        _run(["playerctl", "-p", p, "play"])


# --- cue sounds -----------------------------------------------------------------
def make_cues(directory: Path) -> tuple[Path, Path]:
    """Write the start/stop cues: two soft low "thocks" like a heavy keycap,
    rising (230 -> 300 Hz) for start, falling for stop."""
    import numpy as np  # already loaded by the ASR stack

    rate = 44100

    def thock(f: float) -> "np.ndarray":
        t = np.arange(int(rate * 0.12)) / rate
        body = np.sin(2 * np.pi * f * t) * np.exp(-t / 0.025) + 0.4 * np.sin(3 * np.pi * f * t) * np.exp(-t / 0.012)
        click = np.random.default_rng(1).normal(0, 1, t.size) * np.exp(-t / 0.004) * 0.25
        return np.convolve(body + click, np.ones(10) / 10, mode="same")  # muffle: cheap low-pass

    def save(path: Path, freqs: tuple[float, float]) -> None:
        x = np.concatenate([thock(freqs[0]), np.zeros(int(rate * 0.05)), thock(freqs[1])])
        x = x / np.abs(x).max() * 0.35
        with wave.open(str(path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes((x * 32767).astype("<i2").tobytes())

    start, stop = directory / "speakit-start.wav", directory / "speakit-stop.wav"
    save(start, (230, 300))
    save(stop, (300, 230))
    return start, stop


def play(path: Path | str) -> None:
    try:
        subprocess.Popen(["pw-play", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass


# --- clipboard ------------------------------------------------------------------
def clip_save() -> tuple[str, bytes] | None:
    """Current clipboard as (mime, bytes), or None if empty/unavailable."""
    try:
        types = _run(["wl-paste", "--list-types"]).stdout.decode().split()
        if not types:
            return None
        mime = next((t for t in types if t.startswith("text/plain")), types[0])
        r = _run(["wl-paste", "--no-newline", "--type", mime])
        return (mime, r.stdout) if r.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def clip_restore(saved: tuple[str, bytes] | None) -> None:
    if saved is None:
        _run(["wl-copy", "--clear"])
    else:
        _copy(saved[1], saved[0])


def _keys(*combo: int) -> None:
    downs = [f"{k}:1" for k in combo]
    ups = [f"{k}:0" for k in reversed(combo)]
    _run(["ydotool", "key", *downs, *ups])


def copy_selection(terminal: bool) -> str:
    """Text currently selected in the focused window ("" if none).

    Copy shortcut + sentinel: if nothing is selected the copy is a no-op and
    the sentinel survives. Terminals get Ctrl+Shift+C (Ctrl+C would SIGINT).
    The user's clipboard is restored afterwards.
    """
    saved = clip_save()
    sentinel = f"speakit-sentinel-{time.monotonic_ns()}"
    _copy(sentinel.encode())
    _keys(CTRL, SHIFT, C) if terminal else _keys(CTRL, C)
    time.sleep(0.2)
    got = _run(["wl-paste", "--no-newline", "--type", "text/plain"]).stdout.decode("utf-8", "replace")
    clip_restore(saved)
    return "" if got == sentinel else got


def paste(text: str, terminal: bool) -> None:
    """Put text on the clipboard, send the paste shortcut, restore clipboard."""
    saved = clip_save()
    _copy(text.encode())
    _keys(CTRL, SHIFT, V) if terminal else _keys(CTRL, V)
    time.sleep(0.4)  # apps read the clipboard asynchronously; don't restore under them
    clip_restore(saved)
