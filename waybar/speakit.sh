#!/usr/bin/env bash
# Waybar custom module for speakit. Uses Nerd Font glyphs (not emoji) so it
# aligns with the rest of the bar. Glyphs are emitted as explicit UTF-8 byte
# escapes so they survive editing tools that strip private-use chars.
#   recording        -> dot + REC            (.recording)
#   recording-polish -> dot + REC + gold sparkle  (.recording.polish: LLM cleanup armed)
#   recording-command -> dot + REC + gold wand (.recording.command: command mode)
#   processing       -> hourglass            (.processing: transcribing/cleaning up)
#   done             -> check                (.done) ~2s then auto-hides
#   idle             -> ""                   (empty text => waybar hides the module)
# The dot is the only span without a Pango colour, so it follows the CSS
# `color`, which style.css animates: only the dot blinks.
# Refreshed instantly when the daemon sends SIGRTMIN+8 (match "signal": 8).

state_file="${XDG_RUNTIME_DIR:-/tmp/speakit-$(id -u)}/speakit.state"
state="$(cat "$state_file" 2>/dev/null || echo idle)"

dot=$(printf '\xf3\xb0\x91\x8a')    # nf-md-record        U+F044A
spark=$(printf '\xf3\xb0\x99\xb4')  # nf-md-creation      U+F0674
wand=$(printf '\xf3\xb0\x81\xa8')   # nf-md-auto_fix      U+F0068
sand=$(printf '\xf3\xb0\x94\x9f')   # nf-md-timer_sand    U+F051F
check=$(printf '\xf3\xb0\xb8\x9e')  # nf-md-check_bold    U+F0E1E

case "$state" in
    recording)
        printf '{"text":"%s <span foreground=\x27#ff5555\x27>REC</span>","class":"recording","tooltip":"speakit recording, press again to stop"}\n' "$dot"
        ;;
    recording-polish)
        printf '{"text":"%s <span foreground=\x27#ff5555\x27>REC</span> <span foreground=\x27#e5a04b\x27>%s</span>","class":["recording","polish"],"tooltip":"speakit recording + cleanup, press again to stop"}\n' "$dot" "$spark"
        ;;
    recording-command)
        printf '{"text":"%s <span foreground=\x27#ff5555\x27>REC</span> <span foreground=\x27#e5a04b\x27>%s</span>","class":["recording","command"],"tooltip":"speakit command mode: say what to do with the selected text"}\n' "$dot" "$wand"
        ;;
    processing)
        printf '{"text":"%s","class":"processing","tooltip":"speakit: transcribing"}\n' "$sand"
        ;;
    done)
        printf '{"text":"%s","class":"done","tooltip":"speakit: transcription done"}\n' "$check"
        ;;
    *)
        printf '{"text":"","class":"idle"}\n'
        ;;
esac
