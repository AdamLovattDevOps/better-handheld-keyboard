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
install -m755 "$HERE/bin/handheld-kbd-build-dict" "$BIN/"
install -m755 "$HERE/bin/handheld-kbd-focus-probe" "$BIN/"
install -m755 "$HERE/bin/handheld-kbd-resume.sh"  "$BIN/"
install -m755 "$HERE/bin/handheld-kbd-resume-watch.sh" "$BIN/"
install -m755 "$HERE/bin/handheld-kbd-resume-watch.py" "$BIN/"
# imported by handheld-kbd.py (prediction + swipe engines), not run directly
install -m644 "$HERE/bin/handheld_kbd_predict.py" "$BIN/"
install -m644 "$HERE/bin/handheld_kbd_swipe.py"   "$BIN/"

# --- config (never clobber the user's edits) ---
FRESH=0
if [ ! -f "$CFG/config.json" ]; then install -m644 "$HERE/config/config.json" "$CFG/config.json"; FRESH=1; fi
for f in "$HERE"/config/layouts/*.json; do
  d="$CFG/layouts/$(basename "$f")"; [ -f "$d" ] || install -m644 "$f" "$d"
done

# --- upgrade an existing install: add new keys, drop retired settings ---
# Layouts and config are never clobbered, so an upgrade used to ship the CODE for a new
# key while the user's layout kept no button for it — the feature simply never appeared.
# Merge in any action key this release has that their layout lacks, and drop settings that
# no longer do anything. Both are best-effort: a failure here must not fail the install.
python3 - "$HERE/config" "$CFG" <<'PY' || warn "Layout/config upgrade skipped (see above)."
import json, os, shutil, sys

SRC, DST = sys.argv[1], sys.argv[2]
ACTION_KINDS = {"locale", "hide", "size", "opacity", "move"}
RETIRED = ("dock", "dock_edges")          # v1.0.3's docking slots, replaced by unlock/drag

def load(p):
    with open(p) as f:
        return json.load(f)

def save(p, data):
    tmp = p + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, p)

for name in sorted(os.listdir(os.path.join(SRC, "layouts"))):
    if not name.endswith(".json"):
        continue
    sp, dp = os.path.join(SRC, "layouts", name), os.path.join(DST, "layouts", name)
    if not os.path.exists(dp):
        continue
    try:
        shipped, mine = load(sp), load(dp)
    except Exception as ex:
        print(f"handheld-kbd: skipping {name} ({ex})", file=sys.stderr)
        continue
    have = {k.get("kind") for row in mine.get("rows", []) for k in row}
    added = []
    for ri, row in enumerate(shipped.get("rows", [])):
        for ki, key in enumerate(row):
            kind = key.get("kind")
            if kind not in ACTION_KINDS or kind in have:
                continue
            # same row if the layout still has one, else the first row; same offset if it fits
            target = mine["rows"][ri] if ri < len(mine.get("rows", [])) else mine["rows"][0]
            target.insert(min(ki, len(target)), dict(key))
            have.add(kind)
            added.append(key.get("label") or kind)
    if added:
        shutil.copy(dp, dp + ".bak")
        save(dp, mine)
        print(f"handheld-kbd: added {' '.join(added)} to {name}")

cfg = os.path.join(DST, "config.json")
try:
    mine = load(cfg)
    gone = [k for k in RETIRED if k in mine]
    if gone:
        for k in gone:
            mine.pop(k, None)
        save(cfg, mine)
        print(f"handheld-kbd: removed retired setting(s): {', '.join(gone)}")
except Exception as ex:
    print(f"handheld-kbd: config tidy skipped ({ex})", file=sys.stderr)
PY
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

# --- size the keyboard for THIS panel (fresh installs only) ---
# The shipped geometry suits a 1280x800 Steam Deck. On any other panel it would be the
# wrong width and, on a shorter screen, hang off the bottom. Derive it from the internal
# display instead: full width, 55% height (capped), docked to the bottom edge. The
# keyboard clamps at runtime too, so this only makes the first launch look right.
PANEL_W=""; PANEL_H=""
if [ "$FRESH" = 1 ] && command -v kscreen-doctor >/dev/null 2>&1; then
  eval "$(python3 - <<'PY' 2>/dev/null
import json, subprocess
try:
    data = json.loads(subprocess.check_output(["kscreen-doctor", "-j"], text=True, timeout=5))
except Exception:
    raise SystemExit(0)
outs = [o for o in data.get("outputs", []) if o.get("enabled")]
if not outs:
    raise SystemExit(0)
def size(o):
    mode = next((m for m in (o.get("modes") or []) if m.get("id") == o.get("currentModeId")), {})
    s = mode.get("size") or o.get("size") or {}
    return s.get("width"), s.get("height")
internal = next((o for o in outs if (o.get("name") or "").lower().startswith("edp")), outs[0])
w, h = size(internal)
if w and h:
    print(f'PANEL_W={int(w)}; PANEL_H={int(h)}')
PY
)"
fi
if [ -n "$PANEL_W" ] && [ -n "$PANEL_H" ]; then
  say "Sizing for this panel: ${PANEL_W}x${PANEL_H}"
  python3 - "$CFG/config.json" "$PANEL_W" "$PANEL_H" <<'PY'
import json, sys
p, W, H = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
d = json.load(open(p))
h = min(int(H * 0.55), max(240, int(H * 0.55)))          # 55% of the panel
big = min(int(H * 0.64), H)
d["geometry"] = {"x": 0, "y": H - h, "w": W, "h": h}
d["big_geometry"] = {"x": 0, "y": H - big, "w": W, "h": big}
json.dump(d, open(p, "w"), indent=2)
PY
fi

# --- KWin translucency script ---
# Generated, never copied: a static copy used to be installed here and it diverged from
# what the daemon writes and what the opacity key patches (it hardcoded 0.72 and had no
# `var OP` line, so cycling opacity silently did nothing after a re-install).
install -m644 "$HERE/kwin/handheld-kbd-opacity/metadata.json" "$KWIN/metadata.json"
install -m755 "$HERE/bin/handheld-kbd-kwin-script" "$BIN/"
"$BIN/handheld-kbd-kwin-script" --out "$KWIN/contents/code/main.js" || \
  warn "Could not write the KWin opacity script."

# --- autostart (templates carry __BIN__; substitute this user's real path) ---
sed "s#__BIN__#$BIN#g" "$HERE/autostart/handheld-kbd.desktop"      > "$AUTO/handheld-kbd.desktop"
sed "s#__BIN__#$BIN#g" "$HERE/autostart/handheld-kbd-swap.desktop" > "$AUTO/handheld-kbd-swap.desktop"
sed "s#__BIN__#$BIN#g" "$HERE/autostart/handheld-kbd-resume.desktop"   > "$AUTO/handheld-kbd-resume.desktop"
chmod 644 "$AUTO/handheld-kbd.desktop" "$AUTO/handheld-kbd-swap.desktop" "$AUTO/handheld-kbd-resume.desktop"

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
  # The forced position/size must match the geometry above, or the rule fights the window
  # on first show. The keyboard rewrites both live (move key, big mode), so this is just
  # the starting point — but on a panel that isn't 1280x800 the old hardcoded values put
  # the window partly off-screen until something moved it.
  RULE_GEOM="$(python3 -c '
import json, sys
try:
    g = json.load(open(sys.argv[1]))["geometry"]
    print("%d,%d %d,%d" % (g["x"], g["y"], g["w"], g["h"]))
except Exception:
    print("0,378 1280,422")
' "$CFG/config.json" 2>/dev/null || echo "0,378 1280,422")"
  RULE_POS="${RULE_GEOM%% *}"; RULE_SIZE="${RULE_GEOM##* }"
  "${K[@]}" position "$RULE_POS";  "${K[@]}" positionrule 2
  "${K[@]}" size "$RULE_SIZE";     "${K[@]}" sizerule 2
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
echo
say "Predictive text works from what you type straight away. For corpus-backed"
say "suggestions from the first keypress, build the dictionary once:"
echo "     handheld-kbd-build-dict"
[ "${PRIV_OK:-0}" = 1 ] || warn "Permission step didn't complete — typing won't work until it does."
