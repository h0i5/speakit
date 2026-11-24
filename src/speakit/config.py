"""Central config + paths for speakit.

Settings resolve as: SPEAKIT_<NAME> env var > ~/.config/speakit/config.toml >
default. The daemon reads `cfg.NAME` at use time, so `reload()` (called when
the settings UI saves, or the file changes) applies most settings live; the
ones marked restart=True only take effect when the daemon restarts.
"""
from __future__ import annotations

import json
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path


def _runtime_dir() -> Path:
    # Prefer XDG runtime (tmpfs, per-user, 0700). Fall back to /tmp.
    base = os.environ.get("XDG_RUNTIME_DIR") or f"/tmp/speakit-{os.getuid()}"
    p = Path(base)
    p.mkdir(parents=True, exist_ok=True)
    return p


RUNTIME_DIR = _runtime_dir()
CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "speakit"
CONFIG_PATH = CONFIG_DIR / "config.toml"

# Unix socket the daemon listens on; the toggle client connects here.
SOCKET_PATH = RUNTIME_DIR / "speakit.sock"
# State file read by the waybar module ("recording", "idle", ...).
STATE_PATH = RUNTIME_DIR / "speakit.state"
# Temp WAV the recorder writes and the transcriber reads.
WAV_PATH = RUNTIME_DIR / "speakit.wav"
# Bearer token for the settings UI's API (random per daemon start, 0600).
UI_TOKEN_PATH = RUNTIME_DIR / "speakit-ui.token"
# Built settings UI (ui/ -> pnpm build).
UI_DIST = Path(__file__).resolve().parents[2] / "ui" / "dist"

SAMPLE_RATE = 16000  # model native
CHANNELS = 1


@dataclass(frozen=True)
class Setting:
    name: str          # module attribute, env var SPEAKIT_<name>, toml key <section>.<name.lower()>
    section: str
    default: object
    label: str
    help: str = ""
    restart: bool = False
    choices: tuple = ()
    min: float | None = None
    max: float | None = None


SETTINGS = [
    # --- recording
    Setting("HOLD_SECONDS", "recording", 0.4, "Tap vs hold threshold",
            "A press shorter than this is a tap (toggle); longer is push-to-talk.", min=0.1, max=2),
    Setting("MAX_RECORD_SECONDS", "recording", 120.0, "Auto-stop after (seconds)",
            "A recording left running this long is stopped and typed.", min=10, max=600),
    Setting("PAUSE_MEDIA", "recording", True, "Pause music while recording",
            "Pauses Spotify, browser video etc. and resumes them after."),
    Setting("SOUNDS", "recording", True, "Start/stop sounds", "Soft thocks when the mic opens and closes."),
    Setting("MIC_TARGET", "recording", "", "Microphone",
            "PipeWire source name; empty = system default. See pactl list short sources."),
    # --- typing
    Setting("PASTE_MIN_CHARS", "typing", 150, "Paste instead of type from (chars)",
            "Longer text is pasted via the clipboard (restored after). Non-ASCII is always pasted.",
            min=0, max=5000),
    Setting("KEY_DELAY", "typing", 0, "Key delay (ms)", "Delay between typed keys.", min=0, max=50),
    Setting("KEY_HOLD", "typing", 1, "Key hold (ms)", "Raise to 2-4 if an app drops characters.", min=0, max=50),
    # --- cleanup (LLM)
    Setting("LLM_URL", "cleanup", "http://127.0.0.1:8765/v1/chat/completions", "Cleanup server",
            "OpenAI-compatible chat completions endpoint used by cleanup and command mode."),
    Setting("LLM_TIMEOUT", "cleanup", 8.0, "Timeout (seconds)",
            "After this, cleanup falls back to the raw transcript.", min=1, max=60),
    # --- feedback
    Setting("NOTIFY", "feedback", False, "Desktop notifications", "The waybar indicator usually covers it."),
    Setting("DONE_TICK_SECONDS", "feedback", 2.0, "Done tick duration (seconds)", min=0.5, max=10),
    Setting("WAYBAR_SIGNAL", "feedback", 8, "Waybar signal", "Must match \"signal\" in the waybar module.",
            min=1, max=30),
    # --- speech model
    Setting("MODEL", "model", "nemo-parakeet-tdt-0.6b-v2", "Speech model",
            "Any onnx-asr model. v3 adds 25 European languages; v2 is best for English.", restart=True,
            choices=("nemo-parakeet-tdt-0.6b-v2", "nemo-parakeet-tdt-0.6b-v3")),
    Setting("DEVICE", "model", "cuda", "Device", "cpu frees the GPU (slower).", restart=True,
            choices=("cuda", "cpu")),
    Setting("QUANTIZATION", "model", "", "Quantization", "int8 is smaller, mainly for CPU.", restart=True,
            choices=("", "int8")),
    Setting("UI_PORT", "model", 8766, "Settings UI port", restart=True, min=1024, max=65535),
]
BY_NAME = {s.name: s for s in SETTINGS}


def _coerce(s: Setting, v: object) -> object:
    """Value converted to the setting's type; ValueError if it doesn't fit."""
    d = s.default
    if isinstance(d, bool):
        if isinstance(v, str):
            v = v.strip().lower() not in ("0", "false", "no", "off", "")
        v = bool(v)
    elif isinstance(d, int):
        v = int(v)
    elif isinstance(d, float):
        v = float(v)
    else:
        v = str(v)
    if s.choices and v not in s.choices:
        raise ValueError(f"{s.name}: {v!r} not in {s.choices}")
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        if (s.min is not None and v < s.min) or (s.max is not None and v > s.max):
            raise ValueError(f"{s.name}: {v} outside {s.min}..{s.max}")
    return v


def read_file() -> dict[str, object]:
    """Settings present in config.toml, by name (unknown/invalid keys skipped)."""
    try:
        data = tomllib.loads(CONFIG_PATH.read_text())
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    out = {}
    for s in SETTINGS:
        if s.name.lower() in data.get(s.section, {}):
            try:
                out[s.name] = _coerce(s, data[s.section][s.name.lower()])
            except (TypeError, ValueError):
                pass
    return out


def env_overrides() -> set[str]:
    return {s.name for s in SETTINGS if f"SPEAKIT_{s.name}" in os.environ}


def reload() -> None:
    """Recompute every setting into module globals (env > file > default)."""
    from_file = read_file()
    g = globals()
    for s in SETTINGS:
        v = os.environ.get(f"SPEAKIT_{s.name}")
        try:
            g[s.name] = _coerce(s, v) if v is not None else from_file.get(s.name, s.default)
        except (TypeError, ValueError):
            g[s.name] = from_file.get(s.name, s.default)


def save(changes: dict[str, object]) -> None:
    """Validate and merge changes into config.toml, then reload. Raises
    ValueError/KeyError on a bad name or value (nothing written then)."""
    current = read_file()
    for name, v in changes.items():
        current[name] = _coerce(BY_NAME[name], v)
    lines = ["# speakit settings (written by the settings UI; hand edits are fine)."]
    for section in dict.fromkeys(s.section for s in SETTINGS):
        rows = [s for s in SETTINGS if s.section == section and s.name in current]
        if rows:
            lines.append(f"\n[{section}]")
            # json.dumps output is valid TOML for str/int/float; bools need lowercase.
            lines += [f"{s.name.lower()} = {json.dumps(current[s.name])}" for s in rows]
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_PATH.with_suffix(".tmp")
    tmp.write_text("\n".join(lines) + "\n")
    tmp.replace(CONFIG_PATH)
    reload()


reload()

# Paths that derive from settings (restart-only, so computed once).
# Model files live here as plain files: onnxruntime >=1.32 rejects the HF hub
# cache (its symlinks point outside the model dir). Downloaded on first run.
# ponytail: an interrupted first download leaves a partial dir; delete it to retry.
MODEL_DIR = Path(
    os.environ.get("SPEAKIT_MODEL_DIR")
    or Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "speakit" / MODEL  # noqa: F821
)
# `wrong => right` per line, applied to every transcript (re-read each dictation).
REPLACEMENTS_PATH = Path(os.environ.get("SPEAKIT_REPLACEMENTS") or CONFIG_DIR / "replacements.txt")
SOUND_START = os.environ.get("SPEAKIT_SOUND_START", "")
SOUND_STOP = os.environ.get("SPEAKIT_SOUND_STOP", "")


if __name__ == "__main__":
    import tempfile
    CONFIG_DIR = Path(tempfile.mkdtemp())
    CONFIG_PATH = CONFIG_DIR / "config.toml"
    save({"PAUSE_MEDIA": False, "HOLD_SECONDS": "0.6", "MODEL": "nemo-parakeet-tdt-0.6b-v3"})
    assert PAUSE_MEDIA is False and HOLD_SECONDS == 0.6, (PAUSE_MEDIA, HOLD_SECONDS)  # noqa: F821
    assert tomllib.loads(CONFIG_PATH.read_text())["recording"]["pause_media"] is False
    for bad in ({"DEVICE": "tpu"}, {"HOLD_SECONDS": 99}, {"NOPE": 1}):
        try:
            save(bad)
            raise AssertionError(bad)
        except (ValueError, KeyError):
            pass
    assert read_file()["MODEL"] == "nemo-parakeet-tdt-0.6b-v3"
    print("ok")
