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
from collections import deque
from pathlib import Path

from . import config as cfg
from . import desktop as dk
from . import history as hist
from . import native as nv
from .polish import app_style, command, polish
from .text import ascii_fold, clean, file_paths, load_replacements, replace

# Logic states.
IDLE = "idle"
RECORDING = "recording"
# Display-only: recording with the LLM cleanup pass armed (clean key).
RECORDING_POLISH = "recording-polish"
# Display-only: recording a spoken instruction for command mode (command key).
RECORDING_COMMAND = "recording-command"
# Display-only: between stop and typing (transcribe + optional cleanup).
PROCESSING = "processing"
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


CLIENT = Path.home() / ".local" / "bin" / "speakit-toggle"


def bind_escape(action: str | None) -> None:
    """Escape runs `speakit-toggle <action>` (cancel while recording, raw right
    after a cleanup); None gives Escape back to apps. Bound only for those
    moments, so Escape works normally the rest of the time.
    ponytail: unbind drops every bare-Escape bind, fine while hyprland.conf has none."""
    try:
        nv.hypr("/keyword unbind , Escape")
        if action:
            nv.hypr(f"/keyword bind , Escape, exec, {CLIENT} {action}")
    except (OSError, StopIteration) as e:
        log(f"escape bind failed: {e}")


def set_state(state: str) -> None:
    """Persist state for waybar + poke waybar to refresh immediately."""
    try:
        cfg.STATE_PATH.write_text(state)
    except OSError as e:
        log(f"state write failed: {e}")
    # waybar custom modules refresh on SIGRTMIN+N.
    nv.signal_waybar(cfg.WAYBAR_SIGNAL)


class Daemon:
    def __init__(self) -> None:
        self.state = IDLE
        self.rec_proc: subprocess.Popen | None = None
        self.rec_started = 0.0
        self.model = None  # lazy import + load in run()
        # Monotonic generation so a stale "done" timer can't clear a newer state.
        self._display_gen = 0
        # What happens to the current recording: "raw" (type as-is), "clean"
        # (LLM cleanup) or "command" (instruction applied to the selection).
        self.mode = "raw"
        self.paused: list[str] = []  # media players we paused, to resume
        self.cues = dk.make_cues(cfg.RUNTIME_DIR)
        try:
            dk.kb()  # create the virtual keyboard now, not on first dictation
        except OSError as e:
            log(f"no /dev/uinput access ({e}); typing will fail. Re-run install.sh.")
        # Recent dictations for the settings UI (also on disk if cfg.SAVE_HISTORY).
        self.history: deque[dict] = deque(hist.load()[-50:] if cfg.SAVE_HISTORY else [], maxlen=50)
        self.rec_secs = 0.0
        # (chars, terminal) of the last cleanup typed, so Escape can swap in the raw text.
        self.typed: tuple[int, bool] | None = None
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
                self.typed = None
                bind_escape(None)  # the revert window is over
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
        if cfg.PAUSE_MEDIA:
            self.paused = dk.pause_media()
        try:
            self.rec_proc = subprocess.Popen(cmd)
        except FileNotFoundError:
            notify("speakit error", "pw-record not found", urgency="critical")
            log("pw-record missing")
            return
        self.rec_started = started = time.monotonic()
        self.state = RECORDING
        self._display_gen += 1  # invalidate any pending done-tick timer
        self.typed = None
        bind_escape("cancel")
        set_state({"clean": RECORDING_POLISH, "command": RECORDING_COMMAND}.get(self.mode, RECORDING))
        if cfg.SOUNDS:
            dk.play(cfg.SOUND_START or self.cues[0])

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
        bind_escape(None)
        if proc is None:
            set_state(IDLE)
            return ""
        set_state(PROCESSING)  # toggle() ends it with flash_done() or IDLE
        # SIGINT lets pw-record flush/close the WAV header cleanly.
        proc.send_signal(signal.SIGINT)
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        if cfg.SOUNDS:
            dk.play(cfg.SOUND_STOP or self.cues[1])
        dk.resume_media(self.paused)
        self.paused = []
        self.rec_secs = dur = time.monotonic() - self.rec_started
        log(f"recording stopped ({dur:.1f}s)")
        if not cfg.WAV_PATH.exists() or cfg.WAV_PATH.stat().st_size < 1024:
            return ""
        return str(cfg.WAV_PATH)

    def cancel(self) -> str:
        """Drop the running recording: nothing is transcribed or typed."""
        proc, self.rec_proc = self.rec_proc, None
        self.state = IDLE
        bind_escape(None)
        if proc is not None:
            proc.kill()
            proc.wait()
        dk.resume_media(self.paused)
        self.paused = []
        set_state(IDLE)
        if cfg.SOUNDS:
            dk.play(cfg.SOUND_STOP or self.cues[1])
        log("recording cancelled")
        return "cancelled"

    def revert(self) -> str:
        """Replace the cleanup just typed with the raw transcript (Escape while
        the done tick shows). Backspaces over it, so the cursor must not have moved."""
        last = self.history[-1] if self.history else {}
        typed, self.typed = self.typed, None
        bind_escape(None)
        if not typed or "raw" not in last:
            return "nothing"
        n, terminal = typed
        try:
            for _ in range(n):
                dk.kb().combo(dk.BACKSPACE)
        except OSError as e:
            log(f"revert failed: {e}")
            return "error"
        self.inject(last["raw"], terminal)
        last["text"], last["mode"] = last.pop("raw"), "raw"
        log("reverted to raw transcript")
        return "reverted"

    # --- transcribe + inject ----------------------------------------------
    def transcribe(self, wav: str, files: list[str]) -> str:
        t0 = time.monotonic()
        text = clean(self.model.recognize(wav))
        if text:
            text = replace(text, load_replacements(cfg.REPLACEMENTS_PATH))
            # Spoken file names -> paths of the terminal's repo.
            text = file_paths(text, files)
        log(f"transcribed in {time.monotonic() - t0:.2f}s: {text!r}")
        return text

    def inject(self, text: str, terminal: bool, trailing: str = " ") -> int:
        """Types or pastes text; returns how many characters landed."""
        # Trailing space so back-to-back dictations don't run together.
        text += trailing
        if len(text) >= cfg.PASTE_MIN_CHARS or not text.isascii():
            # Long text: one paste beats typing key by key (also keeps
            # newlines as newlines; pasting never triggers "send").
            # Non-ASCII (accents, other scripts): ydotool can't type it.
            dk.paste(text, terminal)
            return len(text)
        text = ascii_fold(text)
        lines = text.split("\n")
        try:
            for i, line in enumerate(lines):
                if i:
                    # Newline as Shift+Enter: a bare Enter would send the
                    # message in chat apps/Claude Code.
                    dk.kb().combo(nv.SHIFT, nv.ENTER)
                if line:
                    dk.kb().type(line, cfg.KEY_DELAY, cfg.KEY_HOLD)
        except OSError as e:
            notify("speakit error", "can't type: no /dev/uinput access", urgency="critical")
            log(f"typing failed: {e}")
            return 0
        return len(text)

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
            set_state(IDLE)
            notify("speakit", "no audio captured")
            return "empty"
        cls, title, pid = dk.active_window()
        terminal = dk.is_terminal(cls)
        try:
            text = self.transcribe(wav, dk.repo_files(dk.terminal_cwd(pid)) if terminal else [])
        except Exception as e:  # never let one bad clip kill the daemon
            set_state(IDLE)
            notify("speakit error", f"transcribe failed: {e}", urgency="critical")
            log(f"transcribe error: {e}")
            return "error"
        raw = text
        style = app_style(cls, title, terminal)
        trailing = " "
        if text and self.mode == "clean":
            t0 = time.monotonic()
            text = replace(clean(polish(text, style)), load_replacements(cfg.REPLACEMENTS_PATH))
            log(f"polished in {time.monotonic() - t0:.2f}s [{cls}]: {text!r}")
        elif text and self.mode == "command":
            # Read the selection now, not at key press: synthetic copy keys
            # between press and release would make Hyprland drop the release.
            selection = dk.copy_selection(terminal, dk.is_editor(cls))
            t0 = time.monotonic()
            text = clean(command(text, selection, style))
            log(f"command in {time.monotonic() - t0:.2f}s [{cls}, {len(selection)} chars selected]: {text!r}")
            trailing = "" if selection else " "  # replacing a selection: no extra space
        if not text:
            set_state(IDLE)
            notify("speakit", "no speech detected")
            return "empty"
        typed = self.inject(text, terminal, trailing)
        entry = {"time": time.time(), "mode": self.mode, "app": cls, "text": text, "secs": round(self.rec_secs, 1)}
        if self.mode == "clean" and raw != text:
            entry["raw"] = raw
            self.typed = (typed, terminal)
            bind_escape("raw")  # until the done tick clears
        self.history.append(entry)
        if cfg.SAVE_HISTORY:
            try:
                hist.append(entry)
            except OSError as e:
                log(f"history save failed: {e}")
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
        if cmd == "cancel":
            return self.cancel() if self.state == RECORDING else self.state
        if cmd == "raw":
            return self.revert()
        if cmd == "press":
            if self.state != RECORDING:  # stopping keeps the recording's mode
                self.mode = "raw"
            return self.toggle()
        if cmd in ("press-clean", "press-command"):
            # Clean/command keys: start a recording in that mode, or stop any
            # recording in that mode. Separate keys, not chords with the
            # dictation key: Hyprland drops release binds when two keys are
            # let go together.
            self.mode = "clean" if cmd == "press-clean" else "command"
            return self.toggle()
        if cmd == "release":
            # Tap = toggle mode, keep recording. Hold = push-to-talk, stop now.
            # (Release after a stopping tap finds state IDLE and does nothing.)
            if self.state == RECORDING and time.monotonic() - self.rec_started >= cfg.HOLD_SECONDS:
                return self.toggle()
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
        bind_escape(None)  # a crash may have left it bound
        self._install_signal_handlers(srv)
        log(f"listening on {cfg.SOCKET_PATH}")

        threading.Thread(target=load_model, daemon=True).start()
        try:
            from .server import serve
            serve(self)
            log(f"settings UI on http://127.0.0.1:{cfg.UI_PORT}")
        except OSError as e:  # port taken: dictation still works
            log(f"settings UI disabled: {e}")

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
            bind_escape(None)
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
