#!/usr/bin/env bash
# Remove Claude OSK. Leaves your ~/.config/claude-osk/ config in place
# (delete it yourself if you want it gone).
set -uo pipefail
RULE_UUID="a8a95de3-82aa-4998-87c0-125fb8525143"
say() { printf '\033[1;36m::\033[0m %s\n' "$*"; }

say "Stopping running keyboard…"
pkill -f 'python3 .*claude-kbd\.py' 2>/dev/null
pkill -f 'claude-kbd-swap\.sh' 2>/dev/null

say "Removing program + autostart + KWin script…"
rm -f "$HOME/.local/bin/claude-kbd.py" \
      "$HOME/.local/bin/claude-kbd-swap.sh" \
      "$HOME/.local/bin/claude-osk-relogin" \
      "$HOME/.local/bin/claude-osk-ip-remap" \
      "$HOME/.config/autostart/claude-kbd.desktop" \
      "$HOME/.config/autostart/claude-kbd-swap.desktop"
rm -rf "$HOME/.local/share/kwin/scripts/claude-osk-opacity"

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
  pkexec sh -c 'rm -f /etc/udev/rules.d/60-claude-osk.rules; udevadm control --reload' || true
fi

echo
say "Uninstalled. (Your config in ~/.config/claude-osk/ was left untouched.)"
echo "   You were added to the 'input' group at install — remove with: sudo gpasswd -d $USER input"
