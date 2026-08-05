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

write_opscript() {          # $1 = 1 to also force Steam's OSK transparent
    if [ "$1" = 1 ]; then
        STEAM_RULE="else if (cap.indexOf(\"$NAME\") !== -1) w.opacity = 0.0;"
    else
        STEAM_RULE="// Steam's OSK left alone: this keyboard has not proven it can appear yet."
    fi
    mkdir -p "$(dirname "$OPSCRIPT")"
    cat > "$OPSCRIPT" <<EOF2
// Better Handheld Keyboard KWin helper: (1) set our OSK's opacity + hide Steam's OSK,
// (2) keep the OSK visible above fullscreen windows (e.g. Chrome video fullscreen),
// (3) keep keyboard focus on the window the user was on when the OSK is summoned.
var OP = $OP;
var demoted = {};   // internalId -> true : fullscreen windows WE dropped to keepBelow
var lastReal = null;   // most recent focusable window the user was on (for focus restore)

function isKbd(w){ return ("" + w.resourceClass).indexOf("handheld-kbd") !== -1; }

function focusable(w){
    // windows that can hold the user's typing focus: exclude our OSK and
    // non-activating surfaces (panels/docks, desktop, OSD, notifications).
    if (!w) return false;
    if (isKbd(w)) return false;
    if (w.dock || w.desktopWindow || w.onScreenDisplay || w.notification) return false;
    return true;
}

function setOp(w){
    try {
        var c = "" + w.resourceClass;
        var cap = "" + w.caption;
        if (c.indexOf("handheld-kbd") !== -1) w.opacity = OP;
        $STEAM_RULE
    } catch(e){}
}

// GTK hide() destroys the OSK's Wayland surface, so a present, non-minimized
// handheld-kbd window means the keyboard is currently shown.
function kbdShown(){
    var list = workspace.windowList();
    for (var i = 0; i < list.length; i++)
        if (isKbd(list[i]) && !list[i].minimized) return true;
    return false;
}

// A fullscreen window sits in KWin's ActiveLayer, above the OSK's keep-above
// AboveLayer, so it covers the keyboard. keepBelow is evaluated before
// activeFullScreen, so dropping the fullscreen window to keepBelow (BelowLayer)
// lets the OSK float on top. Restore it when the OSK hides / leaves fullscreen.
function applyStack(){
    try {
        var shown = kbdShown();
        var list = workspace.windowList();
        for (var i = 0; i < list.length; i++){
            var w = list[i];
            if (isKbd(w)) continue;
            var id = "" + w.internalId;
            if (shown && w.fullScreen){
                if (!w.keepBelow){ w.keepBelow = true; demoted[id] = true; }
            } else if (demoted[id]){
                w.keepBelow = false;
                delete demoted[id];
            }
        }
    } catch(e){}
}

function watch(w){
    try { w.fullScreenChanged.connect(applyStack); w.minimizedChanged.connect(applyStack); } catch(e){}
}
function onAdded(w){
    setOp(w); watch(w); applyStack();
    // When our OSK maps, the summon (touch gesture / map) may have shifted focus.
    // Re-assert the window the user was on so typed keys land there. keepBelow keeps
    // a demoted fullscreen window below the OSK even once it is active again.
    if (isKbd(w) && lastReal) {
        // only re-activate if focus actually moved, so we don't needlessly re-raise the
        // window and disturb the text caret when the summon didn't defocus it.
        try { if (workspace.activeWindow !== lastReal) workspace.activeWindow = lastReal; } catch(e){}
    }
}

workspace.windowActivated.connect(function(w){ if (focusable(w)) lastReal = w; });
workspace.windowList().forEach(function(w){ setOp(w); watch(w); });
workspace.windowAdded.connect(onAdded);
workspace.windowRemoved.connect(applyStack);
applyStack();
EOF2
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
