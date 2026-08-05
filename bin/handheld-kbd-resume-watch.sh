#!/usr/bin/env bash
# Watches logind for resume-from-sleep and re-inits the OSK. User-level (no root).
export DISPLAY="${DISPLAY:-:0}"
exec 9>/tmp/handheld-kbd-resume-watch.lock; flock -n 9 || exit 0
dbus-monitor --system "type='signal',interface='org.freedesktop.login1.Manager',member='PrepareForSleep'" 2>/dev/null |
while read -r line; do
  # PrepareForSleep(true)=going to sleep, (false)=resuming
  case "$line" in
    *"boolean false"*)
      sleep 3            # let InputPlumber/devices settle after wake
      "$HOME/.local/bin/handheld-kbd-resume.sh"
      ;;
  esac
done
