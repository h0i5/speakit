#!/usr/bin/env bash
# Waybar custom module for speakit. Uses Nerd Font glyphs (not emoji) so it
# aligns with the rest of the bar. Glyphs are emitted as explicit UTF-8 byte
# escapes so they survive editing tools that strip private-use chars.
#   recording -> mic + REC   (red via .recording)
#   done      -> check       (green via .done) ~2s then auto-hides
#   idle      -> ""          (empty text => waybar hides the module)
# Refreshed instantly when the daemon sends SIGRTMIN+8 (match "signal": 8).

state_file="${XDG_RUNTIME_DIR:-/tmp/speakit-$(id -u)}/speakit.state"
state="$(cat "$state_file" 2>/dev/null || echo idle)"

mic=$(printf '\xef\x84\xb0')    # nf-fa-microphone  U+F130
check=$(printf '\xef\x80\x8c')  # nf-fa-check       U+F00C

case "$state" in
    recording)
        printf '{"text":"%s REC","class":"recording","tooltip":"speakit recording — press again to stop"}\n' "$mic"
        ;;
    done)
        printf '{"text":"%s","class":"done","tooltip":"speakit: transcription done"}\n' "$check"
        ;;
    *)
        printf '{"text":"","class":"idle"}\n'
        ;;
esac
