#!/bin/bash
# Claude OSK swap daemon (MIRROR, self-correcting). Ours mirrors Steam's OSK
# visibility via /tmp/claude-kbd.vis. Also loads the opacity KWin script at start.
export DISPLAY=:0
NAME="Steam Input On-screen Keyboard"
VIS=/tmp/claude-kbd.vis
KBD="$HOME/.local/bin/claude-kbd.py"

# Mirror Steam's OSK by default (hardware keyboard-button trigger). Set "mirror": false
# in config.json to instead drive the keyboard with a controller chord / hotkey — then
# the daemon won't hide what the hotkey just showed.
MIRROR=$(python3 -c 'import json,os
try: print(0 if json.load(open(os.path.expanduser("~/.config/claude-osk/config.json"))).get("mirror", True) is False else 1)
except Exception: print(1)' 2>/dev/null)
[ "$MIRROR" = 0 ] || MIRROR=1

exec 9>/tmp/claude-kbd-swap.lock
flock -n 9 || exit 0

OPSCRIPT="$HOME/.local/share/kwin/scripts/claude-osk-opacity/contents/code/main.js"

# Regenerate the KWin opacity script from config.json so `opacity` is configurable.
OP=$(python3 -c 'import json,os
try: print(float(json.load(open(os.path.expanduser("~/.config/claude-osk/config.json")))["opacity"]))
except Exception: print(0.72)' 2>/dev/null)
case "$OP" in ''|*[!0-9.]*) OP=0.72 ;; esac
mkdir -p "$(dirname "$OPSCRIPT")"
cat > "$OPSCRIPT" <<EOF2
function setOp(w){
    try {
        var c = "" + w.resourceClass;
        var cap = "" + w.caption;
        if (c.indexOf("claude-osk") !== -1) w.opacity = $OP;
        else if (cap.indexOf("Steam Input On-screen Keyboard") !== -1) w.opacity = 0.0;
    } catch(e){}
}
workspace.windowList().forEach(setOp);
workspace.windowAdded.connect(setOp);
EOF2

{
  echo "STARTUP $(date) OPSCRIPT=$OPSCRIPT exists=$([ -f "$OPSCRIPT" ] && echo Y || echo N) opacity=$OP"
  qdbus6 org.kde.KWin /Scripting org.kde.kwin.Scripting.unloadScript "claude-osk-opacity" 2>&1
  echo "load: $(qdbus6 org.kde.KWin /Scripting org.kde.kwin.Scripting.loadScript "$OPSCRIPT" "claude-osk-opacity" 2>&1)"
  qdbus6 org.kde.KWin /Scripting org.kde.kwin.Scripting.start 2>&1
} >>/tmp/swap-startup.log 2>&1

# When not mirroring Steam's OSK, remap the hardware keyboard button → F13 (via
# InputPlumber) so it toggles Claude OSK directly instead of triggering Steam's OSK.
if [ "$MIRROR" = 0 ] && [ -x "$HOME/.local/bin/claude-osk-ip-remap" ]; then
    "$HOME/.local/bin/claude-osk-ip-remap" >/dev/null 2>&1
fi

opcheck=99   # force an immediate opacity-script check on first loop
while true; do
    # self-heal: ensure the opacity KWin script stays loaded (its boot-time load
    # can lose the race with KWin startup, which lets Steam's OSK reappear).
    opcheck=$((opcheck+1))
    if [ "$opcheck" -ge 30 ]; then
        opcheck=0
        if [ "$(qdbus6 org.kde.KWin /Scripting org.kde.kwin.Scripting.isScriptLoaded claude-osk-opacity 2>/dev/null)" != "true" ]; then
            qdbus6 org.kde.KWin /Scripting org.kde.kwin.Scripting.loadScript "$OPSCRIPT" "claude-osk-opacity" >/dev/null 2>&1
            qdbus6 org.kde.KWin /Scripting org.kde.kwin.Scripting.start >/dev/null 2>&1
        fi
    fi
    pid=$(pgrep -f 'python3 .*claude-kbd\.py' | head -1)
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
        supp=0; [ -f /tmp/claude-kbd.suppress ] && supp=1
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
        [ "$steam" = 0 ] && rm -f /tmp/claude-kbd.suppress
        if [ "$steam" = 1 ] && [ "$ours" = 0 ] && [ "$supp" = 0 ]; then kill -USR1 "$pid" 2>/dev/null
        elif [ "$steam" = 0 ] && [ "$ours" = 1 ]; then kill -USR2 "$pid" 2>/dev/null
        fi
    fi
    sleep 0.1
done
