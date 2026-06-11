"""speakit toggle client.

Tiny: connect to the daemon socket, send a command (default "toggle"), print
the reply. Bound to a Hyprland key.
"""
from __future__ import annotations

import socket
import subprocess
import sys

from . import config as cfg


def _notify_dead() -> None:
    if not cfg.NOTIFY:
        return
    subprocess.run(
        ["notify-send", "-a", "speakit", "-u", "critical",
         "speakit", "daemon not running (systemctl --user start speakit)"],
        check=False,
    )


def send(cmd: str) -> str:
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(60)  # transcription happens server-side before reply
    try:
        s.connect(str(cfg.SOCKET_PATH))
    except (FileNotFoundError, ConnectionRefusedError, OSError):
        _notify_dead()
        return "no-daemon"
    with s:
        s.sendall(cmd.encode())
        try:
            return s.recv(4096).decode("utf-8", "replace")
        except OSError:
            return ""


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "toggle"
    reply = send(cmd)
    print(reply)
    if reply == "no-daemon":
        sys.exit(1)


if __name__ == "__main__":
    main()
