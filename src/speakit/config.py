"""Central config + paths for speakit. Override most via env vars."""
from __future__ import annotations

import os
from pathlib import Path


def _runtime_dir() -> Path:
    # Prefer XDG runtime (tmpfs, per-user, 0700). Fall back to /tmp.
    base = os.environ.get("XDG_RUNTIME_DIR") or f"/tmp/speakit-{os.getuid()}"
    p = Path(base)
    p.mkdir(parents=True, exist_ok=True)
    return p


RUNTIME_DIR = _runtime_dir()

# Unix socket the daemon listens on; the toggle client connects here.
SOCKET_PATH = RUNTIME_DIR / "speakit.sock"

# State file read by the waybar module ("recording" or "idle").
STATE_PATH = RUNTIME_DIR / "speakit.state"

# Temp WAV the recorder writes and the transcriber reads.
WAV_PATH = RUNTIME_DIR / "speakit.wav"

# --- Whisper model ---------------------------------------------------------
MODEL = os.environ.get("SPEAKIT_MODEL", "large-v3-turbo")
DEVICE = os.environ.get("SPEAKIT_DEVICE", "cuda")
COMPUTE_TYPE = os.environ.get("SPEAKIT_COMPUTE_TYPE", "float16")
LANGUAGE = os.environ.get("SPEAKIT_LANGUAGE", "en")
BEAM_SIZE = int(os.environ.get("SPEAKIT_BEAM_SIZE", "5"))

# initial_prompt biases Whisper's vocabulary + style. A romanized Hinglish
# sample keeps Hindi words in Latin script and primes English<->Hindi
# code-switching (instead of mangling Hindi or switching to Devanagari).
# Add your own frequent names/terms here for better proper-noun accuracy.
# Set SPEAKIT_PROMPT to override; set it empty ("") to disable.
INITIAL_PROMPT = os.environ.get(
    "SPEAKIT_PROMPT",
    "Haan bhai, main thoda busy hoon abhi. Let's catch up kal. "
    "Yeh wala code push kar do aur PR merge kar dena. "
    "Mujhe lagta hai ki ye feature theek kaam kar raha hai.",
)

# --- Audio -----------------------------------------------------------------
SAMPLE_RATE = 16000  # whisper native
CHANNELS = 1
# PipeWire source target. Empty = default source. Set SPEAKIT_MIC to override.
MIC_TARGET = os.environ.get("SPEAKIT_MIC", "")

# --- Injection -------------------------------------------------------------
# ydotool defaults to 20ms key-delay + 20ms key-hold => ~40ms/char (slow,
# visible letter-by-letter). 0/1 makes typing effectively instant while staying
# universal (works in terminals, browsers, web inputs). Bump KEY_HOLD to 2-4 if
# a specific app drops characters.
KEY_DELAY = os.environ.get("SPEAKIT_KEY_DELAY", "0")
KEY_HOLD = os.environ.get("SPEAKIT_KEY_HOLD", "1")

# --- Feedback --------------------------------------------------------------
# Real-time signal number waybar listens on (waybar uses SIGRTMIN+N).
WAYBAR_SIGNAL = int(os.environ.get("SPEAKIT_WAYBAR_SIGNAL", "8"))
# Desktop notifications OFF by default — the waybar indicator is enough.
# Re-enable any time without code changes: set SPEAKIT_NOTIFY=1 (env / systemd
# unit) and restart the daemon.
NOTIFY = os.environ.get("SPEAKIT_NOTIFY", "0") != "0"
# How long the ✓ tick stays in waybar after a successful type, then hides.
DONE_TICK_SECONDS = float(os.environ.get("SPEAKIT_DONE_TICK_SECONDS", "2"))

# Drop trailing newline whisper sometimes adds; trim transcript before typing.
TRIM_OUTPUT = True
