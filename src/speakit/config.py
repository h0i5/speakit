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

# --- ASR model -------------------------------------------------------------
# Any onnx-asr model name. Parakeet TDT v2: English-only, punctuated output,
# far more accurate and faster than whisper-large-v3-turbo.
MODEL = os.environ.get("SPEAKIT_MODEL", "nemo-parakeet-tdt-0.6b-v2")
DEVICE = os.environ.get("SPEAKIT_DEVICE", "cuda")  # "cpu" to skip the GPU
# "" = full precision (best on GPU); "int8" = smaller, mainly for CPU.
QUANTIZATION = os.environ.get("SPEAKIT_QUANTIZATION", "")
# Model files live here as plain files: onnxruntime >=1.32 rejects the HF hub
# cache (its symlinks point outside the model dir). Downloaded on first run.
# ponytail: an interrupted first download leaves a partial dir; delete it to retry.
MODEL_DIR = Path(
    os.environ.get("SPEAKIT_MODEL_DIR")
    or Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "speakit" / MODEL
)

# --- Audio -----------------------------------------------------------------
SAMPLE_RATE = 16000  # model native
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

# --- Text ------------------------------------------------------------------
# `wrong => right` per line, applied to every transcript (whole word, case-
# insensitive). Re-read each dictation, so edits apply without a restart.
REPLACEMENTS_PATH = Path(
    os.environ.get("SPEAKIT_REPLACEMENTS")
    or Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "speakit" / "replacements.txt"
)

# --- Feedback --------------------------------------------------------------
# Real-time signal number waybar listens on (waybar uses SIGRTMIN+N).
WAYBAR_SIGNAL = int(os.environ.get("SPEAKIT_WAYBAR_SIGNAL", "8"))
# Desktop notifications OFF by default — the waybar indicator is enough.
# Re-enable any time without code changes: set SPEAKIT_NOTIFY=1 (env / systemd
# unit) and restart the daemon.
NOTIFY = os.environ.get("SPEAKIT_NOTIFY", "0") != "0"
# How long the ✓ tick stays in waybar after a successful type, then hides.
DONE_TICK_SECONDS = float(os.environ.get("SPEAKIT_DONE_TICK_SECONDS", "2"))
