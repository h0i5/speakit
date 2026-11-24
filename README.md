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
- **Cleanup** (opt-in per dictation): Qwen3-4B-Instruct Q4 on llama.cpp/Vulkan
  (`speakit-llm.service`, ~2.8 GB VRAM, ~0.2–0.8 s). If it's down, raw text is typed.

## Install

```bash
cd ~/Desktop/web/speakit
./install.sh
```

The installer: installs `ydotool`/`pipewire`/`libnotify`, sets `/dev/uinput`
permissions (udev `uaccess` rule: an ACL for the logged-in user only, no `input`
group), `uv sync`s the Python env, and installs+enables the `ydotoold` and
`speakit` **user** systemd services.

> Upgrading from an install that used the `input` group? Re-run `./install.sh`:
> it removes the old rule and drops you from `input`; then log out and back in.

Then add the Hyprland keybinds (installer prints the exact lines):

```
bind  = SUPER, D, exec, ~/Desktop/web/speakit/.venv/bin/speakit-toggle press
bindr = SUPER, D, exec, ~/Desktop/web/speakit/.venv/bin/speakit-toggle release
```

## Usage

- **Tap** SUPER+D → recording starts; **tap** again → transcribes and types at the cursor.
- **Hold** SUPER+D while speaking → stops and types on release (push-to-talk).
  A press shorter than `SPEAKIT_HOLD_SECONDS` (0.4) counts as a tap.
- **Insert + SUPER+D** (hold Insert when starting, or tap it mid-recording) →
  cleanup mode: a local LLM fixes grammar, drops false starts, applies
  self-corrections ("3, no, 4" → "4") and formats lists/paragraphs. Waybar shows
  `REC+`. Line breaks are typed as Shift+Enter so chat apps don't send early.
- Recordings auto-stop after `SPEAKIT_MAX_RECORD_SECONDS` (120).

CLI equivalents (for testing without the keybind):

```bash
uv run speakit-toggle          # toggle start/stop
uv run speakit-toggle press    # / release: what the keybinds send
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
| `SPEAKIT_LLM_URL` | `http://127.0.0.1:8765/v1/chat/completions` | any OpenAI-compatible endpoint |
| `SPEAKIT_LLM_TIMEOUT` | `8` | seconds before falling back to raw text |
| `SPEAKIT_MAX_RECORD_SECONDS` | `120` | auto-stop |
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
  `systemctl --user status ydotoold`; `getfacl /dev/uinput` should list `user:$USER:rw-`.
- **`daemon not running`** → `systemctl --user status speakit`; logs: `journalctl --user -u speakit -f`.
- **Loaded on CPU (slow)** → check daemon log for the CUDA load error; ensure NVIDIA
  driver present. onnxruntime-gpu pulls its own CUDA 13 libs via pip (driver must support CUDA 13); no system CUDA toolkit needed.
- **Wrong mic** → set `SPEAKIT_MIC` (see `pactl list short sources`).
