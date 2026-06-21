#!/usr/bin/env bash
# Claude OSK installer — copies files into your home, sets up the one bit of
# permission it needs (access to /dev/uinput so it can type), and enables autostart.
# Safe to re-run; it won't overwrite your edited config.
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
BIN="$HOME/.local/bin"
CFG="$HOME/.config/claude-osk"
KWIN="$HOME/.local/share/kwin/scripts/claude-osk-opacity"
AUTO="$HOME/.config/autostart"
RULE_UUID="a8a95de3-82aa-4998-87c0-125fb8525143"

say() { printf '\033[1;36m::\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!!\033[0m %s\n' "$*"; }

say "Installing Claude OSK…"
mkdir -p "$BIN" "$CFG/layouts" "$CFG/locales" "$KWIN/contents/code" "$AUTO"

# --- programs ---
install -m755 "$HERE/bin/claude-kbd.py"        "$BIN/"
install -m755 "$HERE/bin/claude-kbd-swap.sh"   "$BIN/"
install -m755 "$HERE/bin/claude-osk-relogin"   "$BIN/"
install -m755 "$HERE/bin/claude-osk-ip-remap"  "$BIN/"

# --- config (never clobber the user's edits) ---
FRESH=0
if [ ! -f "$CFG/config.json" ]; then install -m644 "$HERE/config/config.json" "$CFG/config.json"; FRESH=1; fi
for f in "$HERE"/config/layouts/*.json; do
  d="$CFG/layouts/$(basename "$f")"; [ -f "$d" ] || install -m644 "$f" "$d"
done
for f in "$HERE"/config/locales/*.json; do
  d="$CFG/locales/$(basename "$f")"; [ -f "$d" ] || install -m644 "$f" "$d"
done

# --- on a fresh install, auto-pick the trigger mode for this device ---
# Seamless: if InputPlumber exposes the hardware keyboard button (Legion Go etc.),
# remap it to summon THIS keyboard directly. Otherwise: mirror Steam's on-screen
# keyboard (works on any KDE handheld; press the device's keyboard button).
if [ "$FRESH" = 1 ]; then
  if grep -q 'button: Keyboard' /usr/share/inputplumber/profiles/default.yaml 2>/dev/null; then
    say "Seamless mode — your keyboard button will summon this keyboard directly."
    python3 - "$CFG/config.json" <<'PY'
import json,sys
p=sys.argv[1]; d=json.load(open(p)); d['mirror']=False; d['dbus_trigger']='ui_select'
json.dump(d,open(p,'w'),indent=2)
PY
  else
    say "Mirror mode — this keyboard replaces the system on-screen keyboard."
  fi
fi

# --- KWin translucency script ---
install -m644 "$HERE/kwin/claude-osk-opacity/metadata.json" "$KWIN/metadata.json"
install -m644 "$HERE/kwin/claude-osk-opacity/contents/code/main.js" "$KWIN/contents/code/main.js"

# --- autostart ---
install -m644 "$HERE/autostart/claude-kbd.desktop"      "$AUTO/claude-kbd.desktop"
install -m644 "$HERE/autostart/claude-kbd-swap.desktop" "$AUTO/claude-kbd-swap.desktop"

# --- KWin window rule (pins the keyboard: on top, no focus-steal, bottom-docked) ---
if command -v kwriteconfig6 >/dev/null 2>&1; then
  K=( kwriteconfig6 --file kwinrulesrc --group "$RULE_UUID" --key )
  "${K[@]}" Description "Claude OSK"
  "${K[@]}" wmclass "claude-osk";  "${K[@]}" wmclassmatch 1; "${K[@]}" wmclasscomplete false
  "${K[@]}" above true;            "${K[@]}" aboverule 2
  "${K[@]}" acceptfocus false;     "${K[@]}" acceptfocusrule 2
  "${K[@]}" noborder true;         "${K[@]}" noborderrule 2
  "${K[@]}" skiptaskbar true;      "${K[@]}" skiptaskbarrule 2
  "${K[@]}" skippager true;        "${K[@]}" skippagerrule 2
  "${K[@]}" position "0,378";      "${K[@]}" positionrule 2
  "${K[@]}" size "1280,422";       "${K[@]}" sizerule 2
  cur="$(kreadconfig6 --file kwinrulesrc --group General --key rules 2>/dev/null)"
  case ",$cur," in *",$RULE_UUID,"*) : ;; *)
    new="${cur:+$cur,}$RULE_UUID"
    kwriteconfig6 --file kwinrulesrc --group General --key rules "$new"
    kwriteconfig6 --file kwinrulesrc --group General --key count \
      "$(printf '%s' "$new" | tr ',' '\n' | grep -c .)" ;;
  esac
  qdbus6 org.kde.KWin /KWin reconfigure >/dev/null 2>&1 || true
fi

# --- the one privileged step: let it reach /dev/uinput (single auth prompt) ---
say "Setting up keyboard-injection permission (you'll be asked for your password once)…"
PRIV='
cat > /etc/udev/rules.d/60-claude-osk.rules <<EOF
KERNEL=="uinput", MODE="0660", GROUP="input", OPTIONS+="static_node=uinput"
EOF
getent group input >/dev/null || groupadd input
usermod -aG input "'"$USER"'"
udevadm control --reload && udevadm trigger /dev/uinput 2>/dev/null
'
if command -v pkexec >/dev/null 2>&1; then
  pkexec sh -c "$PRIV" && PRIV_OK=1 || PRIV_OK=0
else
  warn "pkexec not found — run this once yourself:  sudo sh -c '$PRIV'"; PRIV_OK=0
fi

# --- dependency check ---
MISSING=""
python3 -c "import gi" 2>/dev/null || MISSING="$MISSING python-gobject(gtk3)"
python3 -c "import evdev" 2>/dev/null || MISSING="$MISSING python-evdev"
[ -n "$MISSING" ] && warn "Missing Python deps:$MISSING — install them with your package manager."

echo
say "Done!"
echo "   • Log out and back in once (activates autostart + permissions)."
echo "   • Then press your device's keyboard button — this keyboard comes up instead."
echo "   • Edit ~/.config/claude-osk/config.json for opacity, layout, theme, optional hotkey."
[ "${PRIV_OK:-0}" = 1 ] || warn "Permission step didn't complete — typing won't work until it does."
