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
    "$HOME/.local/bin/handheld-kbd-kwin-script" --opacity "$OP" --hide-steam "$1" \
        --mirror "$MIRROR" --out "$OPSCRIPT"
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
# The fallback is recorded in a file, not just a variable: the keyboard regenerates the
# KWin script too (opacity key, placement changes) and would otherwise write MIRROR=0 back,
# silently undoing the fallback while the trigger is still dead.
FALLBACK=/tmp/handheld-kbd.mirror-fallback
rm -f "$FALLBACK"
SEAMLESS_WANTED=0
[ "$MIRROR" = 0 ] && SEAMLESS_WANTED=1

apply_remap() {          # 0 = the hardware button now drives us
    [ -x "$HOME/.local/bin/handheld-kbd-ip-remap" ] || return 1
    "$HOME/.local/bin/handheld-kbd-ip-remap" >>/tmp/swap-startup.log 2>&1
}

REMAPPED=0
if [ "$SEAMLESS_WANTED" = 1 ]; then
    if apply_remap; then
        REMAPPED=1
    else
        echo "REMAP FAILED $(date) — mirroring Steam's OSK until it can be applied" >>/tmp/swap-startup.log
        : > "$FALLBACK"
        MIRROR=1
        HIDE_STEAM=$(hide_steam_wanted)
        write_opscript "$HIDE_STEAM"
        load_opscript
    fi
fi

# Supervisor loop. This used to run at 10Hz and walk the whole X window tree on every
# tick (xwininfo + grep + an xprop write per match) to notice Steam's on-screen keyboard
# appearing. That is now the KWin script's job — it calls the keyboard over DBus the
# instant that window maps — so this loop only has to keep things alive, and can be slow
# and cheap. On a Steam Deck the old poll was a constant drip of processes competing with
# Steam Input, which drives the trackpads.
while true; do
    # Self-heal: the KWin script's boot-time load can lose the race with KWin startup.
    if [ "$(qdbus6 org.kde.KWin /Scripting org.kde.kwin.Scripting.isScriptLoaded handheld-kbd-opacity 2>/dev/null)" != "true" ]; then
        write_opscript "$(hide_steam_wanted)"
        load_opscript
    else
        # Seamless mode: once the keyboard has proven it can appear we may start hiding
        # Steam's OSK. Rewrite + reload only when that flips.
        want=$(hide_steam_wanted)
        if [ "$want" != "$HIDE_STEAM" ]; then
            HIDE_STEAM=$want
            write_opscript "$HIDE_STEAM"
            load_opscript
        fi
    fi

    # InputPlumber drops its composite device whenever the controller re-enumerates — on a
    # Legion Go that happens when the pads are detached, or the service restarts. The remap
    # goes with it and the hardware button quietly stops working. Keep trying until it
    # sticks, then drop the mirror fallback.
    if [ "$SEAMLESS_WANTED" = 1 ] && [ "$REMAPPED" = 0 ]; then
        retry=$((${retry:-0} + 1))
        if [ "$retry" -ge 5 ]; then          # every ~10s
            retry=0
            if apply_remap; then
                REMAPPED=1
                rm -f "$FALLBACK"
                MIRROR=0
                echo "REMAP RECOVERED $(date) — hardware button live again" >>/tmp/swap-startup.log
                HIDE_STEAM=$(hide_steam_wanted)
                write_opscript "$HIDE_STEAM"
                load_opscript
            fi
        fi
    elif [ "$SEAMLESS_WANTED" = 1 ] && [ "$REMAPPED" = 1 ]; then
        # ...and notice if it goes away again.
        check=$((${check:-0} + 1))
        if [ "$check" -ge 15 ]; then         # every ~30s
            check=0
            if ! busctl --system tree org.shadowblip.InputPlumber 2>/dev/null | grep -q CompositeDevice; then
                REMAPPED=0
                echo "REMAP LOST $(date) — InputPlumber has no composite device" >>/tmp/swap-startup.log
            fi
        fi
    fi

    # The tray icon is the way back when the keyboard misbehaves, so it is the last
    # thing that should be missing. Plasma restarts take it with them.
    if [ -x "$HOME/.local/bin/handheld-kbd-tray" ] \
       && ! pgrep -f 'python3 .*handheld-kbd-tray' >/dev/null; then
        setsid python3 "$HOME/.local/bin/handheld-kbd-tray" </dev/null >>/tmp/handheld-kbd-tray.log 2>&1 &
    fi

    # Watchdog: the keyboard's Wayland connection drops when Steam restarts or the
    # compositor churns. Respawn it hidden so the next summon is instant.
    if ! pgrep -f 'python3 .*handheld-kbd\.py' >/dev/null; then
        # keep the keyboard's own output: it is where startup problems show up
        setsid python3 "$KBD" </dev/null >>/tmp/handheld-kbd-out.log 2>&1 &
        sleep 2
    fi

    sleep 2
done
