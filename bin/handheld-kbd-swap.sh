#!/bin/bash
# Better Handheld Keyboard swap daemon (MIRROR, self-correcting). Ours mirrors Steam's OSK
# visibility via /tmp/handheld-kbd.vis. Also loads the opacity KWin script at start.
export DISPLAY=:0
NAME="Steam Input On-screen Keyboard"
VIS=/tmp/handheld-kbd.vis
KBD="$HOME/.local/bin/handheld-kbd.py"

# Mirror Steam's OSK by default (hardware keyboard-button trigger). Set "mirror": false
# in config.json to instead drive the keyboard with a controller chord / hotkey — then
# the daemon won't hide what the hotkey just showed.
MIRROR=$(python3 -c 'import json,os
try: print(0 if json.load(open(os.path.expanduser("~/.config/handheld-kbd/config.json"))).get("mirror", True) is False else 1)
except Exception: print(1)' 2>/dev/null)
[ "$MIRROR" = 0 ] || MIRROR=1

exec 9>/tmp/handheld-kbd-swap.lock
flock -n 9 || exit 0

OPSCRIPT="$HOME/.local/share/kwin/scripts/handheld-kbd-opacity/contents/code/main.js"
PROVEN="$HOME/.local/share/handheld-kbd/trigger-proven"

# Regenerate the KWin opacity script from config.json so `opacity` is configurable.
OP=$(python3 -c 'import json,os
try: print(float(json.load(open(os.path.expanduser("~/.config/handheld-kbd/config.json")))["opacity"]))
except Exception: print(0.72)' 2>/dev/null)
case "$OP" in ''|*[!0-9.]*) OP=0.72 ;; esac

# Hiding Steam's OSK is only safe once we know ours can actually come up. In mirror mode
# it can by definition — Steam's OSK is what drives ours. In seamless mode the keyboard
# touches PROVEN the first time it is shown for real, so until that exists we leave
# Steam's keyboard alone: a trigger that never fires must degrade to "the stock keyboard",
# never to "no keyboard at all". (That was the Legion Go 1 case — InputPlumber's default
# profile carries a 'Keyboard' button mapping on every device, but no Go 1 button emits it.)
hide_steam_wanted() { { [ "$MIRROR" = 1 ] || [ -f "$PROVEN" ]; } && echo 1 || echo 0; }

# One writer for the KWin script (shared with the installer and the keyboard's opacity
# key) so the file can never diverge from what those two expect to find in it.
write_opscript() {          # $1 = 1 to also force Steam's OSK transparent
    "$HOME/.local/bin/handheld-kbd-kwin-script" --opacity "$OP" --hide-steam "$1" --out "$OPSCRIPT"
}

load_opscript() {
    qdbus6 org.kde.KWin /Scripting org.kde.kwin.Scripting.unloadScript "handheld-kbd-opacity" >/dev/null 2>&1
    qdbus6 org.kde.KWin /Scripting org.kde.kwin.Scripting.loadScript "$OPSCRIPT" "handheld-kbd-opacity" >/dev/null 2>&1
    qdbus6 org.kde.KWin /Scripting org.kde.kwin.Scripting.start >/dev/null 2>&1
}

HIDE_STEAM=$(hide_steam_wanted)
write_opscript "$HIDE_STEAM"

{
  echo "STARTUP $(date) OPSCRIPT=$OPSCRIPT exists=$([ -f "$OPSCRIPT" ] && echo Y || echo N) opacity=$OP mirror=$MIRROR hide_steam=$HIDE_STEAM"
  load_opscript
} >>/tmp/swap-startup.log 2>&1

# Seamless mode: remap the hardware keyboard button (via InputPlumber) so it fires our
# DBus event instead of triggering Steam's OSK. If that remap can't be applied, fall back
# to mirror mode for this session — better a keyboard on Steam's trigger than no keyboard.
if [ "$MIRROR" = 0 ] && [ -x "$HOME/.local/bin/handheld-kbd-ip-remap" ]; then
    if ! "$HOME/.local/bin/handheld-kbd-ip-remap" >>/tmp/swap-startup.log 2>&1; then
        echo "REMAP FAILED $(date) — falling back to mirror mode" >>/tmp/swap-startup.log
        MIRROR=1
        HIDE_STEAM=$(hide_steam_wanted)
        write_opscript "$HIDE_STEAM"
        load_opscript
    fi
fi

opcheck=99   # force an immediate opacity-script check on first loop
while true; do
    # self-heal: ensure the opacity KWin script stays loaded (its boot-time load
    # can lose the race with KWin startup, which lets Steam's OSK reappear).
    opcheck=$((opcheck+1))
    if [ "$opcheck" -ge 30 ]; then
        opcheck=0
        # Seamless mode: the first time the keyboard actually appears, PROVEN shows up and
        # we may start hiding Steam's OSK. Rewrite + reload the script when that flips.
        want=$(hide_steam_wanted)
        if [ "$want" != "$HIDE_STEAM" ]; then
            HIDE_STEAM=$want
            write_opscript "$HIDE_STEAM"
            load_opscript
        elif [ "$(qdbus6 org.kde.KWin /Scripting org.kde.kwin.Scripting.isScriptLoaded handheld-kbd-opacity 2>/dev/null)" != "true" ]; then
            qdbus6 org.kde.KWin /Scripting org.kde.kwin.Scripting.loadScript "$OPSCRIPT" "handheld-kbd-opacity" >/dev/null 2>&1
            qdbus6 org.kde.KWin /Scripting org.kde.kwin.Scripting.start >/dev/null 2>&1
        fi
    fi
    pid=$(pgrep -f 'python3 .*handheld-kbd\.py' | head -1)
    if [ -z "$pid" ]; then
        # Watchdog: the keyboard process can die when Steam restarts / the compositor
        # churns and its Wayland connection drops. Respawn it (hidden), throttled to
        # once / 3s, so it recovers WITHOUT needing a reboot.
        now=$(date +%s)
        if [ $((now - ${lastspawn:-0})) -ge 3 ]; then
            lastspawn=$now
            setsid python3 "$KBD" </dev/null >/dev/null 2>&1 &
        fi
    elif [ "$MIRROR" = 1 ]; then
        # Mirror Steam's OSK → ours (hardware keyboard-button path). Skipped when
        # mirror=false (chord/hotkey drives it) so we don't hide what the hotkey showed.
        # Dismiss latch (hide button) → UNMAP Steam's OSK so its invisible window can't
        # keep capturing taps; clears once it's gone.
        supp=0; [ -f /tmp/handheld-kbd.suppress ] && supp=1
        steam=0
        for w in $(xwininfo -root -tree 2>/dev/null | grep -i "$NAME" | grep -oE '0x[0-9a-f]+'); do
            if [ "$supp" = 1 ]; then
                xdotool windowunmap "$w" 2>/dev/null
            else
                xprop -id "$w" -f _NET_WM_WINDOW_OPACITY 32c -set _NET_WM_WINDOW_OPACITY 0 2>/dev/null
            fi
            xwininfo -id "$w" 2>/dev/null | grep -q IsViewable && steam=1
        done
        ours=$(cat "$VIS" 2>/dev/null); ours=${ours:-0}
        [ "$steam" = 0 ] && rm -f /tmp/handheld-kbd.suppress
        if [ "$steam" = 1 ] && [ "$ours" = 0 ] && [ "$supp" = 0 ]; then kill -USR1 "$pid" 2>/dev/null
        elif [ "$steam" = 0 ] && [ "$ours" = 1 ]; then kill -USR2 "$pid" 2>/dev/null
        fi
    fi
    sleep 0.1
done
