"""speakit daemon.

Resident process: keeps the ASR model loaded in VRAM and runs a tiny
unix-socket server. The toggle client sends "toggle"; first toggle starts
recording, second stops -> transcribe -> type into the focused window.

Model load (a few seconds) happens once at startup so each dictation only pays
transcription time.
"""
from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import threading
import time

from . import config as cfg
from .polish import polish
from .text import clean, load_replacements, replace

# Logic states.
IDLE = "idle"
RECORDING = "recording"
# Display-only: recording with the LLM cleanup pass armed (clean key held).
RECORDING_POLISH = "recording-polish"
# Transient display-only state shown after a successful type (the ✓ tick).
DONE = "done"


def log(msg: str) -> None:
    print(f"[speakitd] {msg}", flush=True)


def notify(summary: str, body: str = "", *, urgency: str = "low") -> None:
    if not cfg.NOTIFY:
        return
    try:
        subprocess.run(
            ["notify-send", "-a", "speakit", "-u", urgency, "-t", "1500", summary, body],
            check=False,
        )
    except FileNotFoundError:
        pass


def set_state(state: str) -> None:
    """Persist state for waybar + poke waybar to refresh immediately."""
    try:
        cfg.STATE_PATH.write_text(state)
    except OSError as e:
        log(f"state write failed: {e}")
    # waybar custom modules refresh on SIGRTMIN+N.
    subprocess.run(["pkill", f"-RTMIN+{cfg.WAYBAR_SIGNAL}", "waybar"], check=False)


class Daemon:
    def __init__(self) -> None:
        self.state = IDLE
        self.rec_proc: subprocess.Popen | None = None
        self.rec_started = 0.0
        self.model = None  # lazy import + load in run()
        # Monotonic generation so a stale "done" timer can't clear a newer state.
        self._display_gen = 0
        # Clean key (Insert) held right now / armed for the current recording.
        self.clean_held = False
        self.polish = False
        # Socket handler and the auto-stop timer thread both drive state.
        self.lock = threading.Lock()

    def flash_done(self) -> None:
        """Show the ✓ tick, then auto-hide after cfg.DONE_TICK_SECONDS."""
        set_state(DONE)
        self._display_gen += 1
        gen = self._display_gen

        def clear() -> None:
            # Only clear if nothing newer (a new recording) happened since.
            if gen == self._display_gen and self.state == IDLE:
                set_state(IDLE)

        threading.Timer(cfg.DONE_TICK_SECONDS, clear).start()

    # --- recording ---------------------------------------------------------
    def start_recording(self) -> None:
        cmd = [
            "pw-record",
            "--rate", str(cfg.SAMPLE_RATE),
            "--channels", str(cfg.CHANNELS),
            "--format", "s16",
        ]
        if cfg.MIC_TARGET:
            cmd += ["--target", cfg.MIC_TARGET]
        cmd.append(str(cfg.WAV_PATH))
        try:
            self.rec_proc = subprocess.Popen(cmd)
        except FileNotFoundError:
            notify("speakit error", "pw-record not found", urgency="critical")
            log("pw-record missing")
            return
        self.rec_started = started = time.monotonic()
        self.state = RECORDING
        self.polish = self.clean_held
        self._display_gen += 1  # invalidate any pending done-tick timer
        set_state(RECORDING_POLISH if self.polish else RECORDING)

        def auto_stop() -> None:
            if self.state == RECORDING and self.rec_started == started:
                log(f"hit {cfg.MAX_RECORD_SECONDS:.0f}s limit, stopping")
                self.handle("stop")

        t = threading.Timer(cfg.MAX_RECORD_SECONDS, auto_stop)
        t.daemon = True
        t.start()
        notify("🎙 Recording", "speak now — toggle again to stop")
        log("recording started")

    def stop_recording(self) -> str:
        """Stop recorder cleanly and return the WAV path (empty on failure)."""
        proc, self.rec_proc = self.rec_proc, None
        self.state = IDLE
        # Hyprland drops the clean key's release bind if Home was pressed
        # while it was held, so each recording consumes the armed flag.
        self.clean_held = False
        set_state(IDLE)
        if proc is None:
            return ""
        # SIGINT lets pw-record flush/close the WAV header cleanly.
        proc.send_signal(signal.SIGINT)
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        dur = time.monotonic() - self.rec_started
        log(f"recording stopped ({dur:.1f}s)")
        if not cfg.WAV_PATH.exists() or cfg.WAV_PATH.stat().st_size < 1024:
            return ""
        return str(cfg.WAV_PATH)

    # --- transcribe + inject ----------------------------------------------
    def transcribe(self, wav: str) -> str:
        t0 = time.monotonic()
        text = clean(self.model.recognize(wav))
        if text:
            text = replace(text, load_replacements(cfg.REPLACEMENTS_PATH))
        log(f"transcribed in {time.monotonic() - t0:.2f}s: {text!r}")
        return text

    def inject(self, text: str) -> None:
        # Trailing space so back-to-back dictations don't run together.
        lines = (text + " ").split("\n")
        try:
            for i, line in enumerate(lines):
                if i:
                    # Newline as Shift+Enter (keycodes 42 LEFTSHIFT, 28 ENTER):
                    # a bare Enter would send the message in chat apps/Claude Code.
                    subprocess.run(["ydotool", "key", "42:1", "28:1", "28:0", "42:0"], check=True)
                if line:
                    subprocess.run(
                        ["ydotool", "type",
                         "--key-delay", cfg.KEY_DELAY,
                         "--key-hold", cfg.KEY_HOLD,
                         "--", line],
                        check=True,
                    )
        except FileNotFoundError:
            notify("speakit error", "ydotool not found", urgency="critical")
            log("ydotool missing")
        except subprocess.CalledProcessError as e:
            notify("speakit error", "ydotool failed (is ydotoold running?)", urgency="critical")
            log(f"ydotool failed: {e}")

    # --- command handling --------------------------------------------------
    def toggle(self) -> str:
        if self.state == IDLE:
            if self.model is None:
                notify("speakit", "model still loading — try again in a moment")
                return "loading"
            self.start_recording()
            return "recording"
        # RECORDING -> stop + process
        wav = self.stop_recording()
        if not wav:
            notify("speakit", "no audio captured")
            return "empty"
        try:
            text = self.transcribe(wav)
        except Exception as e:  # never let one bad clip kill the daemon
            notify("speakit error", f"transcribe failed: {e}", urgency="critical")
            log(f"transcribe error: {e}")
            return "error"
        if text and self.polish:
            t0 = time.monotonic()
            text = replace(clean(polish(text)), load_replacements(cfg.REPLACEMENTS_PATH))
            log(f"polished in {time.monotonic() - t0:.2f}s: {text!r}")
        if not text:
            notify("speakit", "no speech detected")
            return "empty"
        self.inject(text)
        notify("✓ Transcription done")
        self.flash_done()
        return "typed"

    def handle(self, cmd: str) -> str:
        with self.lock:
            return self._handle(cmd.strip().lower())

    def _handle(self, cmd: str) -> str:
        if cmd == "toggle":
            return self.toggle()
        if cmd == "status":
            return self.state
        if cmd == "press":
            return self.toggle()
        if cmd == "release":
            # Tap = toggle mode, keep recording. Hold = push-to-talk, stop now.
            # (Release after a stopping tap finds state IDLE and does nothing.)
            if self.state == RECORDING and time.monotonic() - self.rec_started >= cfg.HOLD_SECONDS:
                return self.toggle()
            return self.state
        if cmd == "clean-down":
            # Hold the clean key before or during a recording to arm cleanup.
            self.clean_held = True
            if self.state == RECORDING and not self.polish:
                self.polish = True
                set_state(RECORDING_POLISH)
            return self.state
        if cmd == "clean-up":
            self.clean_held = False
            return self.state
        if cmd == "stop" and self.state == RECORDING:
            return self.toggle()
        if cmd == "start" and self.state == IDLE:
            return self.toggle()
        return f"unknown:{cmd}"

    # --- server ------------------------------------------------------------
    def run(self) -> None:
        import numpy as np
        import onnx_asr
        import onnxruntime as ort

        def load_model() -> None:
            log(f"loading model {cfg.MODEL} on {cfg.DEVICE}...")
            t0 = time.monotonic()
            providers: list = ["CPUExecutionProvider"]
            if cfg.DEVICE != "cpu":
                # CUDA/cuDNN come from the nvidia-* wheels, not the system.
                ort.preload_dlls()
                # HEURISTIC: the default exhaustive cuDNN search re-runs for
                # every new clip length, making each first-seen length slow.
                # kSameAsRequested: grow the VRAM arena exactly, not in doubling
                # chunks (~500 MiB less resident, same speed).
                providers.insert(0, ("CUDAExecutionProvider", {
                    "cudnn_conv_algo_search": "HEURISTIC",
                    "arena_extend_strategy": "kSameAsRequested",
                }))
            # ORT falls back to CPU by itself if the CUDA provider can't start.
            model = onnx_asr.load_model(cfg.MODEL, cfg.MODEL_DIR, quantization=cfg.QUANTIZATION or None, providers=providers)
            model.recognize(np.zeros(cfg.SAMPLE_RATE, dtype=np.float32))  # warm up
            self.model = model
            log(f"model loaded in {time.monotonic() - t0:.1f}s")

        # Open the socket FIRST so the client never sees "daemon not running"
        # while the (possibly large, first-run downloading) model loads. Toggles
        # received before the model is ready get a "loading" reply.
        if cfg.SOCKET_PATH.exists():
            cfg.SOCKET_PATH.unlink()
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(str(cfg.SOCKET_PATH))
        os.chmod(cfg.SOCKET_PATH, 0o600)
        srv.listen(8)
        set_state(IDLE)
        self._install_signal_handlers(srv)
        log(f"listening on {cfg.SOCKET_PATH}")

        threading.Thread(target=load_model, daemon=True).start()

        while True:
            try:
                conn, _ = srv.accept()
            except OSError:
                break
            with conn:
                try:
                    data = conn.recv(4096).decode("utf-8", "replace")
                except OSError:
                    continue
                if not data:
                    continue
                reply = self.handle(data)
                try:
                    conn.sendall(reply.encode())
                except OSError:
                    pass

    def _install_signal_handlers(self, srv: socket.socket) -> None:
        def shutdown(_signum, _frame):
            log("shutting down")
            if self.rec_proc is not None:
                self.rec_proc.send_signal(signal.SIGINT)
            try:
                srv.close()
            finally:
                if cfg.SOCKET_PATH.exists():
                    cfg.SOCKET_PATH.unlink()
                set_state(IDLE)
                sys.exit(0)

        signal.signal(signal.SIGINT, shutdown)
        signal.signal(signal.SIGTERM, shutdown)


def main() -> None:
    Daemon().run()


if __name__ == "__main__":
    main()
