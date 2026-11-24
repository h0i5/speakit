# speakit

System-wide **push-to-toggle voice-to-text** for Arch + Hyprland. Press a key to
start recording, press again to stop — the transcription is typed straight into
whatever window has focus (Claude Code terminal, browser search, any web textbox).

A local, free, private alternative to Claude Code `/voice` that works **everywhere**.

## How it works

```
Hyprland bind ─► speakit-toggle ─unix socket─► speakitd (daemon)
  (Home)          (Rust, ~1 ms)                ├─ Parakeet ASR model resident in VRAM
                                               ├─ pw-record → 16k mono WAV
                                               ├─ transcribe (Parakeet TDT v2, CUDA)
                                               ├─ own uinput keyboard → focused window
                                               └─ waybar indicator
```

The daemon keeps the ASR model loaded in GPU memory, so each dictation only
pays transcription time (tens of ms for short clips), not the model load. First toggle starts recording; second stops, transcribes, and types.

- **Engine**: NVIDIA Parakeet TDT 0.6B v2 via [onnx-asr](https://github.com/istupakov/onnx-asr) on CUDA (English, punctuated).
- **Injection**: the daemon's own virtual keyboard (kernel uinput, no ydotoold) — works in terminals, browsers, Electron, XWayland.
- **Desktop calls**: Hyprland's socket, MPRIS over D-Bus and waybar signals are done in-process (~1 ms each) instead of spawning hyprctl/playerctl/pkill.
- **Audio**: PipeWire `pw-record`.
- **Cleanup** (opt-in per dictation): Qwen3-4B-Instruct Q4 on llama.cpp/Vulkan
  (`speakit-llm.service`, ~2.8 GB VRAM, ~0.2–0.8 s). If it's down, raw text is typed.

## Install

```bash
cd ~/Desktop/web/speakit
./install.sh
```

The installer: installs system packages, sets `/dev/uinput` permissions (udev
`uaccess` rule: an ACL for the logged-in user only, no `input` group), `uv sync`s
the Python env, builds the Rust keybind client into `~/.local/bin/speakit-toggle`,
and installs+enables the `speakit` and `speakit-llm` **user** systemd services.

> Upgrading from an install that used the `input` group? Re-run `./install.sh`:
> it removes the old rule and drops you from `input`; then log out and back in.

Then add the Hyprland keybinds (installer prints the exact lines):

```
bind  = , Home, exec, ~/.local/bin/speakit-toggle press
bindr = , Home, exec, ~/.local/bin/speakit-toggle release
```

## Usage

- **Tap** Home → recording starts; **tap** again → transcribes and types at the cursor.
- **Hold** Home while speaking → stops and types on release (push-to-talk).
  A press shorter than `SPEAKIT_HOLD_SECONDS` (0.4) counts as a tap.
- **Insert** (tap or hold, same as the dictation key; or press it to stop a
  running dictation) → cleanup mode: a local LLM fixes grammar, drops false starts, applies
  self-corrections ("3, no, 4" → "4") and formats lists/paragraphs. Waybar shows
  `REC+`. Line breaks are typed as Shift+Enter so chat apps don't send early.
- **End** (command mode, tap or hold) → select text, then say what to do with it
  ("make this more polite", "turn into bullets", "translate to Hindi"); the result
  replaces the selection. Nothing selected = writes what you ask for ("write a
  short reply saying I'll be 10 minutes late"). Waybar shows a gold wand.
- Cleanup and command mode adapt to the focused app: terminals get backticked
  commands/paths, chat apps a casual tone, email (Gmail, Thunderbird...) polished paragraphs.
- Playing media (Spotify, browser, mpv...) pauses while recording and resumes after.
- Soft start/stop blips (`SPEAKIT_SOUNDS=0` to disable, or point
  `SPEAKIT_SOUND_START`/`_STOP` at your own files).
- Text of 150+ chars or with non-ASCII characters is pasted (clipboard restored)
  instead of typed key by key; terminals get Ctrl+Shift+V.
- Recordings auto-stop after `SPEAKIT_MAX_RECORD_SECONDS` (120).

CLI equivalents (for testing without the keybind):

```bash
uv run speakit-toggle          # toggle start/stop
uv run speakit-toggle press    # / release: what the keybinds send
uv run speakit-toggle status   # idle | recording
```

## Settings app

`speakit-toggle settings` (or "speakit settings" in your app launcher) opens a
settings window: keys, recording, typing, cleanup, word fixes, recent
dictations and the speech model. It's a native Rust app (`app/`, gpui +
gpui-component, installed as `~/.local/bin/speakit`) talking to the daemon's
JSON API on `127.0.0.1:8766`; the API needs a random per-start token that only
your user can read. Changes save to `~/.config/speakit/config.toml` and apply
live, except those marked *restart*.

If the native app isn't installed, the launcher falls back to the React web UI
(`ui/`, served by the daemon) in a Chrome app window.

Rebuild after editing: `cd app && cargo build --release && install -m755 target/release/speakit ~/.local/bin/`
(web UI: `cd ui && pnpm install && pnpm build`).

## Config (env vars)

Env vars override `config.toml`.

Set in `~/.config/systemd/user/speakit.service` (`Environment=...`) or your shell:

| Var | Default | Notes |
|-----|---------|-------|
| `SPEAKIT_MODEL` | `nemo-parakeet-tdt-0.6b-v2` | any onnx-asr model (`nemo-parakeet-tdt-0.6b-v3` for 25 languages, ...) |
| `SPEAKIT_DEVICE` | `cuda` | `cpu` falls back automatically if CUDA fails |
| `SPEAKIT_QUANTIZATION` | (full precision) | `int8` = smaller, mainly for CPU |
| `SPEAKIT_MIC` | (default source) | PipeWire source name/id; `pactl list short sources` |
| `SPEAKIT_WAYBAR_SIGNAL` | `8` | must match `"signal"` in your waybar module |
| `SPEAKIT_NOTIFY` | `0` | `1` enables desktop notifications |
| `SPEAKIT_PAUSE_MEDIA` | `1` | pause MPRIS players while recording |
| `SPEAKIT_SOUNDS` | `1` | start/stop cue sounds |
| `SPEAKIT_PASTE_MIN_CHARS` | `150` | paste instead of type at this length |
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
/* speakit: house tint (text colour + faint background, border neutral).
   The record dot is the only span without a Pango colour, so it follows
   `color`, which the animation flips: only the dot blinks. REC+ (cleanup
   armed) is the same red plus a gold sparkle. Hidden when idle (empty text collapses the module). */
#custom-speakit.recording {
  color: #ff5555;
  background-color: #2a1519;
  animation: speakit-blink-red 1.2s infinite;
}

#custom-speakit.processing {
  color: #e5a04b;
  background-color: #251e14;
}

#custom-speakit.done {
  color: #50fa7b;
  background-color: #16241c;
  padding: 3px 16px 3px 12px; /* optical centring for the tick glyph */
}

@keyframes speakit-blink-red {
  0% { color: #ff5555; }
  50% { color: #ff5555; }
  51% { color: #4a2026; }
  100% { color: #4a2026; }
}
```

The daemon pokes waybar (`SIGRTMIN+8`) on every state change for instant updates.

## Troubleshooting

- **Nothing types** → no uinput access: `getfacl /dev/uinput` should list
  `user:$USER:rw-` (re-run `./install.sh`, then log out/in). The daemon log says
  `no /dev/uinput access` at startup when this is the cause.
- **`daemon not running`** → `systemctl --user status speakit`; logs: `journalctl --user -u speakit -f`.
- **Loaded on CPU (slow)** → check daemon log for the CUDA load error; ensure NVIDIA
  driver present. onnxruntime-gpu pulls its own CUDA 13 libs via pip (driver must support CUDA 13); no system CUDA toolkit needed.
- **Wrong mic** → set `SPEAKIT_MIC` (see `pactl list short sources`).
