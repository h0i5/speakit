# speakit

System-wide **push-to-toggle voice-to-text** for Arch + Hyprland. Press a key to
start recording, press again to stop — the transcription is typed straight into
whatever window has focus (Claude Code terminal, browser search, any web textbox).

A local, free, private alternative to Claude Code `/voice` that works **everywhere**.

## How it works

```
Hyprland bind ─► speakit-toggle ─unix socket─► speakitd (daemon)
  (SUPER+D)       (thin client)                ├─ Parakeet ASR model resident in VRAM  
                                               ├─ pw-record → 16k mono WAV
                                               ├─ transcribe (Parakeet TDT v2, CUDA)   
                                               ├─ ydotool type → focused window
                                               └─ notify-send + waybar indicator
```

The daemon keeps the ASR model loaded in GPU memory, so each dictation only
pays transcription time (tens of ms for short clips), not the model load. First toggle starts recording; second stops, transcribes, and types.

- **Engine**: NVIDIA Parakeet TDT 0.6B v2 via [onnx-asr](https://github.com/istupakov/onnx-asr) on CUDA (English, punctuated).
- **Injection**: `ydotool` (kernel uinput) — works in terminals, browsers, Electron, XWayland.
- **Audio**: PipeWire `pw-record`.

## Install

```bash
cd ~/Desktop/web/speakit
./install.sh
```

The installer: installs `ydotool`/`pipewire`/`libnotify`, sets `/dev/uinput`
permissions (udev rule + adds you to the `input` group), `uv sync`s the Python
env, and installs+enables the `ydotoold` and `speakit` **user** systemd services.

> If it added you to the `input` group, **log out and back in**, then
> `systemctl --user restart ydotoold speakit`.

Then add the Hyprland keybind (installer prints the exact line):

```
bind = SUPER, D, exec, ~/Desktop/web/speakit/.venv/bin/speakit-toggle
```

## Usage

- **SUPER+D** → 🎙 notification, speak.
- **SUPER+D** again → transcribes, types text at the cursor, ✓ notification.

CLI equivalents (for testing without the keybind):

```bash
uv run speakit-toggle          # toggle start/stop
uv run speakit-toggle status   # idle | recording
```

## Config (env vars)

Set in `~/.config/systemd/user/speakit.service` (`Environment=...`) or your shell:

| Var | Default | Notes |
|-----|---------|-------|
| `SPEAKIT_MODEL` | `nemo-parakeet-tdt-0.6b-v2` | any onnx-asr model (`nemo-parakeet-tdt-0.6b-v3` for 25 languages, ...) |
| `SPEAKIT_DEVICE` | `cuda` | `cpu` falls back automatically if CUDA fails |
| `SPEAKIT_QUANTIZATION` | (full precision) | `int8` = smaller, mainly for CPU |
| `SPEAKIT_MIC` | (default source) | PipeWire source name/id; `pactl list short sources` |
| `SPEAKIT_WAYBAR_SIGNAL` | `8` | must match `"signal"` in your waybar module |
| `SPEAKIT_NOTIFY` | `0` | `1` enables desktop notifications |
| `SPEAKIT_REPLACEMENTS` | `~/.config/speakit/replacements.txt` | word fixes, see below |

## Transcript cleanup

Filler words (uh, um, hmm) are dropped, and a trailing space is typed so
back-to-back dictations don't run together.

For names/jargon the model mishears, add `wrong => right` lines to
`~/.config/speakit/replacements.txt` (whole word, case-insensitive, `#` comments).
Re-read on every dictation, so no restart needed:

```
Zo => Zoho
S D F S => SDFs
```

## Waybar indicator (optional)

```jsonc
"custom/speakit": {
  "exec": "~/Desktop/web/speakit/waybar/speakit.sh",
  "return-type": "json",
  "signal": 8,
  "interval": "once"
}
```

```css
#custom-speakit.recording { color: #ff5555; }
```

The daemon pokes waybar (`SIGRTMIN+8`) on every state change for instant updates.

## Troubleshooting

- **Nothing types / `ydotool failed`** → ydotoold not running or no uinput perms.
  `systemctl --user status ydotoold`; confirm you're in the `input` group (`id`) and relogged.
- **`daemon not running`** → `systemctl --user status speakit`; logs: `journalctl --user -u speakit -f`.
- **Loaded on CPU (slow)** → check daemon log for the CUDA load error; ensure NVIDIA
  driver present. onnxruntime-gpu pulls its own CUDA 13 libs via pip (driver must support CUDA 13); no system CUDA toolkit needed.
- **Wrong mic** → set `SPEAKIT_MIC` (see `pactl list short sources`).
