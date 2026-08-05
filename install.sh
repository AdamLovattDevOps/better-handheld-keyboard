#!/usr/bin/env bash
# Better Handheld Keyboard installer — copies files into your home, sets up the one bit of
# permission it needs (access to /dev/uinput so it can type), and enables autostart.
# Safe to re-run; it won't overwrite your edited config.
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
BIN="$HOME/.local/bin"
CFG="$HOME/.config/handheld-kbd"
KWIN="$HOME/.local/share/kwin/scripts/handheld-kbd-opacity"
AUTO="$HOME/.config/autostart"
RULE_UUID="a8a95de3-82aa-4998-87c0-125fb8525143"

say() { printf '\033[1;36m::\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!!\033[0m %s\n' "$*"; }

say "Installing Better Handheld Keyboard…"

# --- migrate from a previous 'claude-osk' install, if present ---
if [ -e "$HOME/.local/bin/claude-kbd.py" ] || [ -d "$HOME/.config/claude-osk" ]; then
  say "Migrating from a previous install…"
  pkill -f 'python3 .*claude-kbd\.py' 2>/dev/null || true
  pkill -f 'claude-kbd-swap\.sh' 2>/dev/null || true
  rm -f "$HOME/.local/bin/claude-kbd.py" "$HOME/.local/bin/claude-kbd-swap.sh" \
        "$HOME/.local/bin/claude-osk-relogin" "$HOME/.local/bin/claude-osk-ip-remap" \
        "$HOME/.config/autostart/claude-kbd.desktop" "$HOME/.config/autostart/claude-kbd-swap.desktop"
  rm -rf "$HOME/.local/share/kwin/scripts/claude-osk-opacity"
  # carry over the old config if the new one doesn't exist yet
  if [ -d "$HOME/.config/claude-osk" ] && [ ! -d "$CFG" ]; then
    mv "$HOME/.config/claude-osk" "$CFG"
  fi
fi

mkdir -p "$BIN" "$CFG/layouts" "$CFG/locales" "$KWIN/contents/code" "$AUTO"

# --- programs ---
install -m755 "$HERE/bin/handheld-kbd.py"        "$BIN/"
install -m755 "$HERE/bin/handheld-kbd-swap.sh"   "$BIN/"
install -m755 "$HERE/bin/handheld-kbd-relogin"   "$BIN/"
install -m755 "$HERE/bin/handheld-kbd-ip-remap"  "$BIN/"
install -m755 "$HERE/bin/handheld-kbd-recover"   "$BIN/"

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
# Mirror mode is the default because it works on any KDE handheld: press whatever
# summons the system on-screen keyboard and ours comes up in its place.
#
# Seamless mode remaps the hardware keyboard button via InputPlumber so it drives this
# keyboard directly. It is only offered on devices that actually HAVE such a button.
# Do NOT infer that from /usr/share/inputplumber/profiles/default.yaml — that profile
# ships the same 'button: Keyboard' mapping on every device, so grepping it selected
# seamless mode on hardware where no button can ever emit the event (Legion Go 1, and a
# Steam Deck or ROG Ally under Bazzite/ChimeraOS: none of those InputPlumber drivers
# emit GamepadButton::Keyboard). The result was a dead trigger. Match the device instead.
SEAMLESS_DMI='83N0 83N1'        # Lenovo Legion Go 2 — has a real keyboard button

seamless_supported() {
  [ -f /usr/share/inputplumber/profiles/default.yaml ] || return 1
  command -v busctl >/dev/null 2>&1 || return 1
  local product
  product="$(cat /sys/class/dmi/id/product_name 2>/dev/null)" || return 1
  for m in $SEAMLESS_DMI; do [ "$product" = "$m" ] && return 0; done
  return 1
}

if [ "$FRESH" = 1 ]; then
  if seamless_supported; then
    say "Seamless mode — your keyboard button will summon this keyboard directly."
    python3 - "$CFG/config.json" <<'PY'
import json,sys
p=sys.argv[1]; d=json.load(open(p)); d['mirror']=False; d['dbus_trigger']='ui_select'
json.dump(d,open(p,'w'),indent=2)
PY
  else
    say "Mirror mode — this keyboard replaces the system on-screen keyboard."
  fi
elif ! seamless_supported && python3 -c 'import json,os,sys
p=os.path.expanduser("~/.config/handheld-kbd/config.json")
try: sys.exit(0 if json.load(open(p)).get("mirror", True) is False else 1)
except Exception: sys.exit(1)' 2>/dev/null; then
  # Repair an existing install that an earlier version put into seamless mode on hardware
  # that can't drive it. Left alone, the keyboard button does nothing at all.
  warn "This device is in seamless mode but has no keyboard button that can trigger it."
  python3 - "$CFG/config.json" <<'PY'
import json,sys
p=sys.argv[1]; d=json.load(open(p)); d['mirror']=True
json.dump(d,open(p,'w'),indent=2)
PY
  say "Switched to mirror mode — press whatever opens the Steam keyboard."
  pkill -f 'handheld-kbd-swap\.sh' 2>/dev/null || true
  if [ -f /usr/share/inputplumber/profiles/default.yaml ] && command -v busctl >/dev/null 2>&1; then
    for dev in $(busctl --system tree org.shadowblip.InputPlumber 2>/dev/null \
                 | grep -oE '/org/shadowblip/InputPlumber/CompositeDevice[0-9]+'); do
      busctl --system call org.shadowblip.InputPlumber "$dev" \
        org.shadowblip.Input.CompositeDevice LoadProfilePath s \
        /usr/share/inputplumber/profiles/default.yaml >/dev/null 2>&1
    done
    say "Restored InputPlumber's stock button mapping."
  fi
fi

# --- KWin translucency script ---
install -m644 "$HERE/kwin/handheld-kbd-opacity/metadata.json" "$KWIN/metadata.json"
install -m644 "$HERE/kwin/handheld-kbd-opacity/contents/code/main.js" "$KWIN/contents/code/main.js"

# --- autostart (templates carry __BIN__; substitute this user's real path) ---
sed "s#__BIN__#$BIN#g" "$HERE/autostart/handheld-kbd.desktop"      > "$AUTO/handheld-kbd.desktop"
sed "s#__BIN__#$BIN#g" "$HERE/autostart/handheld-kbd-swap.desktop" > "$AUTO/handheld-kbd-swap.desktop"
chmod 644 "$AUTO/handheld-kbd.desktop" "$AUTO/handheld-kbd-swap.desktop"

# --- KWin window rule (pins the keyboard: on top, no focus-steal, bottom-docked) ---
if command -v kwriteconfig6 >/dev/null 2>&1; then
  K=( kwriteconfig6 --file kwinrulesrc --group "$RULE_UUID" --key )
  "${K[@]}" Description "Better Handheld Keyboard"
  "${K[@]}" wmclass "handheld-kbd";  "${K[@]}" wmclassmatch 1; "${K[@]}" wmclasscomplete false
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
cat > /etc/udev/rules.d/60-handheld-kbd.rules <<EOF
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
echo "   • Edit ~/.config/handheld-kbd/config.json for opacity, layout, theme, optional hotkey."
echo "   • No keyboard at all afterwards? Run:  handheld-kbd-recover"
[ "${PRIV_OK:-0}" = 1 ] || warn "Permission step didn't complete — typing won't work until it does."
