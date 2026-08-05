#!/usr/bin/env bash
# Re-initialise the Better Handheld Keyboard after resume-from-sleep. A fresh restart
# re-establishes the uinput device AND the InputPlumber (org.shadowblip) dbus signal
# subscription, both of which go stale across suspend. Idempotent, no root.
export DISPLAY="${DISPLAY:-:0}"
# force a clean restart of the OSK process (not just "start if dead" — it IS alive but stale)
pkill -f 'python3 .*handheld-kbd\.py' 2>/dev/null
sleep 1
setsid sh -c 'python3 "$HOME/.local/bin/handheld-kbd.py" >/tmp/handheld-kbd-out.log 2>&1' >/dev/null 2>&1 &
# reassert the KWin opacity/focus script + swap daemon
[ -x "$HOME/.local/share/system-fixes/restore-osk.sh" ] && "$HOME/.local/share/system-fixes/restore-osk.sh" >/dev/null 2>&1 || true
exit 0
