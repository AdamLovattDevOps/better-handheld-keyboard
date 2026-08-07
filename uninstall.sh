#!/usr/bin/env bash
# Remove Better Handheld Keyboard. Leaves your ~/.config/handheld-kbd/ config in place
# (delete it yourself if you want it gone).
set -uo pipefail
RULE_UUID="a8a95de3-82aa-4998-87c0-125fb8525143"
say() { printf '\033[1;36m::\033[0m %s\n' "$*"; }

say "Stopping running keyboard…"
# Units first. They are what restarts the supervisor, so pkill on its own removes the
# process and gets a fresh one two seconds later.
systemctl --user stop handheld-kbd handheld-kbd-tray 2>/dev/null
systemctl --user reset-failed handheld-kbd handheld-kbd-tray 2>/dev/null
pkill -f 'python3 .*handheld-kbd\.py' 2>/dev/null
pkill -f 'python3 .*handheld-kbd-tray' 2>/dev/null
pkill -f 'handheld-kbd-swap\.sh' 2>/dev/null

say "Removing program + autostart + KWin script…"
# Glob rather than a list of names. The list was written once and never kept up: by
# v1.0.11 it named seven of the eighteen files an install puts in ~/.local/bin, so
# "uninstalled" left most of the program behind. Anything this project installs is
# named handheld-kbd-* or handheld_kbd_*, so match that and nothing else.
rm -f "$HOME"/.local/bin/handheld-kbd-* \
      "$HOME"/.local/bin/handheld-kbd.py \
      "$HOME"/.local/bin/handheld_kbd_*.py
rm -f "$HOME"/.config/autostart/handheld-kbd-*.desktop \
      "$HOME"/.config/autostart/handheld-kbd.desktop \
      "$HOME"/.config/autostart/handheld-kbd*.desktop.disabled
rm -f "$HOME"/.local/share/applications/handheld-kbd-*.desktop
command -v update-desktop-database >/dev/null 2>&1 && \
  update-desktop-database "$HOME/.local/share/applications" 2>/dev/null
rm -rf "$HOME/.local/share/kwin/scripts/handheld-kbd-opacity"
rm -rf "$HOME/.local/lib/handheld-kbd"          # the bundled suggestion filter
# The script keeps running in the session after its files are gone — unload it, or the
# desktop is still being driven by a keyboard that no longer exists.
qdbus6 org.kde.KWin /Scripting org.kde.kwin.Scripting.unloadScript handheld-kbd-opacity >/dev/null 2>&1 || true

# restore the hardware keyboard button (we remapped it via InputPlumber)
say "Restoring InputPlumber default profile…"
for d in $(busctl --system tree org.shadowblip.InputPlumber 2>/dev/null \
           | grep -oE '/org/shadowblip/InputPlumber/CompositeDevice[0-9]+'); do
  busctl --system call org.shadowblip.InputPlumber "$d" \
    org.shadowblip.Input.CompositeDevice LoadProfilePath s \
    /usr/share/inputplumber/profiles/default.yaml 2>/dev/null
done

if command -v kwriteconfig6 >/dev/null 2>&1; then
  say "Removing KWin window rule…"
  cur="$(kreadconfig6 --file kwinrulesrc --group General --key rules 2>/dev/null)"
  new="$(printf '%s' "$cur" | tr ',' '\n' | grep -vx "$RULE_UUID" | paste -sd, -)"
  kwriteconfig6 --file kwinrulesrc --group General --key rules "$new"
  kwriteconfig6 --file kwinrulesrc --group General --key count \
    "$(printf '%s' "$new" | tr ',' '\n' | grep -c .)"
  kwriteconfig6 --file kwinrulesrc --group "$RULE_UUID" --key Description "" 2>/dev/null
  # drop the rule group entirely
  if command -v kwriteconfig6 >/dev/null; then kwriteconfig6 --file kwinrulesrc --group "$RULE_UUID" --delete-group 2>/dev/null || true; fi
  qdbus6 org.kde.KWin /KWin reconfigure >/dev/null 2>&1 || true
fi

say "Removing /dev/uinput udev rule (one password prompt)…"
if command -v pkexec >/dev/null 2>&1; then
  pkexec sh -c 'rm -f /etc/udev/rules.d/60-handheld-kbd.rules; udevadm control --reload' || true
fi

echo
say "Uninstalled. (Your config in ~/.config/handheld-kbd/ was left untouched.)"
echo "   You were added to the 'input' group at install — remove with: sudo gpasswd -d $USER input"
