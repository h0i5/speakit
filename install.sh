#!/usr/bin/env bash
# speakit installer: deps, ydotool uinput perms, systemd user units.
# Idempotent — safe to re-run.
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
USER_SYSTEMD="$HOME/.config/systemd/user"
UDEV_RULE="/etc/udev/rules.d/70-speakit-uinput.rules"
OLD_UDEV_RULE="/etc/udev/rules.d/80-speakit-uinput.rules"

say() { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[!]\033[0m %s\n' "$*"; }

# 1. System packages -------------------------------------------------------
say "Installing system packages (ydotool, pipewire tools, libnotify)..."
need_pkgs=()
command -v ydotool   >/dev/null || need_pkgs+=(ydotool)
command -v pw-record >/dev/null || need_pkgs+=(pipewire)
command -v notify-send >/dev/null || need_pkgs+=(libnotify)
command -v llama-server >/dev/null || need_pkgs+=(llama-cpp ggml-vulkan)
command -v wl-copy     >/dev/null || need_pkgs+=(wl-clipboard)
command -v playerctl   >/dev/null || need_pkgs+=(playerctl)
if [ ${#need_pkgs[@]} -gt 0 ]; then
    sudo pacman -S --needed "${need_pkgs[@]}"
else
    say "All system packages already present."
fi

# 2. uinput permissions ----------------------------------------------------
# ydotoold needs write access to /dev/uinput. uaccess makes logind grant an
# ACL on it to the user at the active seat only. (Not the 'input' group: that
# also lets every process you run read raw keystrokes from /dev/input/event*.)
# Must sort before 73-seat-late.rules, hence the 70- prefix.
say "Configuring /dev/uinput permissions..."
if [ ! -f "$UDEV_RULE" ]; then
    echo 'KERNEL=="uinput", SUBSYSTEM=="misc", TAG+="uaccess", OPTIONS+="static_node=uinput"' \
        | sudo tee "$UDEV_RULE" >/dev/null
    sudo udevadm control --reload-rules
    sudo udevadm trigger --name-match=uinput || true
    say "udev rule installed."
else
    say "udev rule already present."
fi

# Migrate from older speakit installs, which used the 'input' group.
if [ -f "$OLD_UDEV_RULE" ]; then
    sudo rm "$OLD_UDEV_RULE"
    sudo udevadm control --reload-rules
    if id -nG "$USER" | tr ' ' '\n' | grep -qx input; then
        sudo gpasswd -d "$USER" input
        warn "Removed $USER from 'input' group. LOG OUT and back in for it to take effect."
    fi
fi

# 3. Python env ------------------------------------------------------------
say "Syncing Python env with uv (downloads onnx-asr + CUDA wheels)..."
( cd "$PROJECT_DIR" && uv sync )

say "Fetching cleanup LLM (Qwen3-4B-Instruct Q4, ~2.4 GB, skipped if present)..."
"$PROJECT_DIR/.venv/bin/hf" download unsloth/Qwen3-4B-Instruct-2507-GGUF \
    Qwen3-4B-Instruct-2507-Q4_K_M.gguf --local-dir "$HOME/.cache/speakit/llm" >/dev/null

# 4. systemd user units ----------------------------------------------------
say "Installing systemd user units..."
mkdir -p "$USER_SYSTEMD"
cp "$PROJECT_DIR/systemd/ydotoold.service" "$USER_SYSTEMD/"
cp "$PROJECT_DIR/systemd/speakit.service"  "$USER_SYSTEMD/"
cp "$PROJECT_DIR/systemd/speakit-llm.service" "$USER_SYSTEMD/"
systemctl --user daemon-reload
systemctl --user enable --now ydotoold.service || warn "ydotoold start failed (relog if perms just changed)"
systemctl --user enable --now speakit.service  || warn "speakit start failed (check: journalctl --user -u speakit)"
systemctl --user enable --now speakit-llm.service || warn "speakit-llm start failed (check: journalctl --user -u speakit-llm)"

chmod +x "$PROJECT_DIR/waybar/speakit.sh"

# 5. Snippets --------------------------------------------------------------
cat <<EOF

\033[1;32mDone.\033[0m  Two manual config steps:

1) Hyprland — add to ~/.config/hypr/hyprland.conf:

   bind  = SUPER, D, exec, $PROJECT_DIR/.venv/bin/speakit-toggle press
   bindr = SUPER, D, exec, $PROJECT_DIR/.venv/bin/speakit-toggle release

   bind  = , Insert, exec, $PROJECT_DIR/.venv/bin/speakit-toggle press-clean
   bindr = , Insert, exec, $PROJECT_DIR/.venv/bin/speakit-toggle release

   Tap = toggle (tap again to stop). Hold = push-to-talk (release to stop).
   Insert works the same, plus LLM cleanup + formatting.

   bind  = , End, exec, $PROJECT_DIR/.venv/bin/speakit-toggle press-command
   bindr = , End, exec, $PROJECT_DIR/.venv/bin/speakit-toggle release

   End = command mode: select text, say what to do with it.

   (services autostart via systemd; no exec-once needed)

2) Waybar (optional indicator) — add module to ~/.config/waybar/config:

   "custom/speakit": {
     "exec": "$PROJECT_DIR/waybar/speakit.sh",
     "return-type": "json",
     "signal": 8,
     "interval": "once"
   }

   ...and put "custom/speakit" in your modules list. Style in style.css:
     #custom-speakit.recording { color: #ff5555; }

If you were just removed from the 'input' group, LOG OUT/IN.

Test:  press SUPER+D, speak, press again — text types into the focused window.
EOF
