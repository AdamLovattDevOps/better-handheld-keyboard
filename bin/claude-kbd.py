#!/usr/bin/env python3
"""Claude OSK — a dark on-screen keyboard that injects REAL keys via /dev/uinput.

Layout and appearance are configurable via JSON:
  ~/.config/claude-osk/config.json          (opacity, geometry, theme, layout, locale)
  ~/.config/claude-osk/layouts/<name>.json  (the button list)
  ~/.config/claude-osk/locales/<code>.json  (per-XKB-layout label overrides, e.g. us/gb)

Locale: the keyboard injects real keycodes, so what a key TYPES is decided by the
OS XKB layout. The 🌐 key switches the OS layout via KDE's KeyboardLayouts DBus and
re-skins the on-key labels to match, keeping label and output in sync.
If any JSON is missing/invalid, built-in defaults are used so it always comes up.
"""
import gi, sys, time, os, signal, json, subprocess
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk, GLib
from evdev import UInput, ecodes as e
GLib.set_prgname("claude-osk")   # app_id so the KWin window-rule can match us

CFG_DIR = os.path.expanduser("~/.config/claude-osk")

# Game Mode (gamescope): render as a transparent, input-capable external overlay
# instead of a KWin window. Enabled by the daemon when it detects gamescope.
GAMEMODE = os.environ.get("CLAUDE_KBD_GAMEMODE") == "1"
GS_DISPLAY = os.environ.get("CLAUDE_KBD_GS_DISPLAY", os.environ.get("DISPLAY", ":0"))

DEFAULT_CONFIG = {
    "layout": "full", "locale": "auto", "opacity": 0.72,
    "geometry": {"x": 0, "y": 378, "w": 1280, "h": 422},
    "key_size": [74, 64], "wide_size": [110, 64], "space_width": 360,
    "key_settle_ms": 20,
    # OPTIONAL extra toggle. The primary trigger is your device's keyboard button
    # (handled by the mirror daemon — no setup). This hotkey is for an attached
    # keyboard, or a controller chord mapped to this combo in Steam Input. [] = off.
    # Needs read access to /dev/input (installer's udev rule + 'input' group).
    "hotkey": [],
    "theme": {
        "window_bg": "#161616", "key_bg": "#333333", "key_fg": "#f5f5f5",
        "key_border": "#0d0d0d", "key_active": "#3daee9",
        "mod_on_bg": "#ff8c00", "mod_on_fg": "#000000", "mod_on_border": "#ffe000",
        "special_bg": "#2a2a2a", "special_fg": "#bbccdd", "shifted_fg": "#7fb0ff",
    },
}
DEFAULT_LAYOUT = {
    "name": "Built-in",
    "rows": [
        [{"label": "Esc", "key": "KEY_ESC"}, {"label": "Tab", "key": "KEY_TAB", "kind": "wide"},
         {"label": "⌫", "key": "KEY_BACKSPACE", "kind": "wide"}, {"label": "⏎", "key": "KEY_ENTER", "kind": "wide"}],
        [{"label": "Ctrl", "key": "KEY_LEFTCTRL", "kind": "mod"},
         {"label": "Alt", "key": "KEY_LEFTALT", "kind": "mod"},
         {"label": "Shift", "key": "KEY_LEFTSHIFT", "kind": "mod"},
         {"label": "Space", "key": "KEY_SPACE", "kind": "space"}],
    ],
}


def _deep_merge(base, over):
    out = dict(base)
    for k, v in (over or {}).items():
        out[k] = _deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def load_config():
    try:
        with open(os.path.join(CFG_DIR, "config.json")) as f:
            return _deep_merge(DEFAULT_CONFIG, json.load(f))
    except Exception as ex:
        print(f"claude-osk: using default config ({ex})", file=sys.stderr)
        return dict(DEFAULT_CONFIG)


def load_layout(name):
    try:
        with open(os.path.join(CFG_DIR, "layouts", f"{name}.json")) as f:
            lay = json.load(f)
        if not lay.get("rows"):
            raise ValueError("no rows")
        return lay
    except Exception as ex:
        print(f"claude-osk: using default layout ({ex})", file=sys.stderr)
        return dict(DEFAULT_LAYOUT)


def load_locale_map(code):
    try:
        with open(os.path.join(CFG_DIR, "locales", f"{code}.json")) as f:
            return json.load(f)
    except Exception:
        return {}


def active_layout_code():
    """The XKB layout code (e.g. 'us'/'gb') KDE currently has active."""
    try:
        ll = subprocess.check_output(
            ["kreadconfig6", "--file", "kxkbrc", "--group", "Layout", "--key", "LayoutList"],
            text=True, timeout=3).strip()
        codes = [c.strip() for c in ll.split(",") if c.strip()]
        idx = int(subprocess.check_output(
            ["qdbus6", "org.kde.keyboard", "/Layouts", "org.kde.KeyboardLayouts.getLayout"],
            text=True, timeout=3).strip())
        return codes[idx] if 0 <= idx < len(codes) else (codes[0] if codes else "us")
    except Exception:
        return "us"


def resolve_locale(config):
    loc = config.get("locale", "auto")
    if loc != "auto":
        return loc
    if GAMEMODE:
        return "us"          # no KDE in Game Mode — skip the DBus/kreadconfig probe
    return active_layout_code()


def resolve_rows(layout):
    """[(label, keycode_or_None, kind, shifted, name)], plus sorted keycode set."""
    rows, keys = [], set()
    for jrow in layout["rows"]:
        row = []
        for k in jrow:
            kind = k.get("kind", "")
            if kind == "locale":                      # layout-switch key: no keycode
                row.append((k.get("label", "🌐"), None, "locale", "", ""))
                continue
            name = k.get("key", "")
            kc = getattr(e, name, None)
            if not isinstance(kc, int):
                print(f"claude-osk: skipping unknown key '{name}'", file=sys.stderr)
                continue
            row.append((k.get("label", name), kc, kind, k.get("shifted", ""), name))
            keys.add(kc)
        if row:
            rows.append(row)
    return rows, sorted(keys)


def build_css(t):
    return f"""
window {{ background-color: {t['window_bg']}; }}
button {{ background: {t['key_bg']}; color: {t['key_fg']}; border: 1px solid {t['key_border']};
         border-radius: 5px; font-size: 18px; margin: 2px; padding: 6px; }}
button:active {{ background: {t['key_active']}; }}
button.mod-on {{ background: {t['mod_on_bg']}; color: {t['mod_on_fg']}; font-weight: bold;
                border: 3px solid {t['mod_on_border']}; }}
button.special {{ background: {t['special_bg']}; color: {t['special_fg']}; }}
window.gm {{ background-color: rgba(0,0,0,0); }}
.gm-keys {{ background-color: rgba(12,12,12,0.82); }}
""".encode()


def _esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class OSK(Gtk.Window):
    def __init__(self, config, rows, allkeys, locale):
        super().__init__()
        self.cfg = config
        self.locale = locale
        self.sfg = config["theme"]["shifted_fg"]
        self.settle = config.get("key_settle_ms", 20) / 1000.0
        self.ui = UInput({e.EV_KEY: allkeys}, name="claude-osk")
        self.mods = {}
        self.modbtns = []
        self.keybtns = []        # (button, key_name, base_label, base_shifted) for relabeling
        self.locale_btn = None
        prov = Gtk.CssProvider(); prov.load_from_data(build_css(config["theme"]))
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), prov,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        ksz, wsz, sw = config["key_size"], config["wide_size"], config["space_width"]
        grid = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        grid.set_margin_top(4); grid.set_margin_bottom(4)
        for row in rows:
            hb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
            hb.set_halign(Gtk.Align.CENTER)
            for (label, kc, kind, shifted, name) in row:
                b = Gtk.Button(label=label)
                b.set_can_focus(False)
                exp = kind in ('wide', 'space')
                b.set_hexpand(exp)
                if kind == 'space': b.set_size_request(sw, -1)
                elif kind == 'wide': b.set_size_request(wsz[0], wsz[1])
                else: b.set_size_request(ksz[0], ksz[1])
                if kind == 'locale':
                    b.get_style_context().add_class('special')
                    b.connect("clicked", self.on_locale)
                    self.locale_btn = b
                elif kind == 'hide':
                    b.get_style_context().add_class('special')
                    b.connect("clicked", lambda *_: self.hide())
                elif kind == 'mod':
                    b.get_style_context().add_class('special')
                    b.connect("clicked", self.on_mod, kc)
                    self.modbtns.append((b, kc))
                else:
                    b.connect("clicked", self.on_key, kc)
                    self.keybtns.append((b, name, label, shifted))
                hb.pack_start(b, exp, exp, 0)
            grid.pack_start(hb, False, False, 0)
        self.orig_touch_mode = None
        if GAMEMODE:
            # Transparent fullscreen overlay: gamescope fullscreens us, the game shows
            # through the transparent top, keys docked at the bottom on a dark strip.
            vis = self.get_screen().get_rgba_visual()
            if vis is not None:
                self.set_visual(vis)
            self.set_app_paintable(True)
            self.get_style_context().add_class("gm")
            grid.get_style_context().add_class("gm-keys")
            outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
            spacer = Gtk.Box(); spacer.set_vexpand(True)   # transparent filler
            outer.pack_start(spacer, True, True, 0)
            outer.pack_end(grid, False, False, 0)
            self.add(outer)
        else:
            self.add(grid)
        self.set_wmclass("claude-osk", "claude-osk")
        self.set_title("claude-osk")
        self.set_decorated(False)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_keep_above(True)
        g = config["geometry"]
        self.set_default_size(g["w"], g["h"])
        self.set_gravity(Gdk.Gravity.SOUTH)
        self.apply_locale(locale)

    def _set_label(self, button, label, shifted):
        ch = button.get_child()
        if isinstance(ch, Gtk.Label):
            if shifted:
                ch.set_markup(_esc(label) + f" <span size='xx-small' foreground='{self.sfg}'>"
                              + _esc(shifted) + "</span>")
            else:
                ch.set_text(label)

    def apply_locale(self, code):
        """Re-skin key labels to match the active XKB layout."""
        self.locale = code
        lmap = load_locale_map(code)
        for (b, name, base_label, base_shifted) in self.keybtns:
            ov = lmap.get(name, {})
            self._set_label(b, ov.get("label", base_label), ov.get("shifted", base_shifted))
        if self.locale_btn:
            self._set_label(self.locale_btn, "🌐" + code.upper(), "")

    def on_locale(self, btn):
        before = active_layout_code()
        try:
            subprocess.run(["qdbus6", "org.kde.keyboard", "/Layouts",
                            "org.kde.KeyboardLayouts.switchToNextLayout"], timeout=3)
        except Exception as ex:
            print(f"claude-osk: layout switch failed ({ex})", file=sys.stderr)
        after = active_layout_code()
        if after == before:
            # switch had no effect — extra layouts are configured but not registered
            # yet (KWin reads kxkbrc only at login). Tell the user to log out.
            try: subprocess.Popen(["claude-osk-relogin"])
            except Exception: pass
        self.apply_locale(after)

    def _refresh_mods(self):
        for b, k in self.modbtns:
            ctx = b.get_style_context()
            (ctx.add_class if k in self.mods else ctx.remove_class)('mod-on')

    def on_mod(self, btn, kc):
        if kc in self.mods: del self.mods[kc]
        else: self.mods[kc] = True
        self._refresh_mods()

    def on_key(self, btn, kc):
        s = self.settle
        mods = list(self.mods)
        for m in mods: self.ui.write(e.EV_KEY, m, 1)
        if mods: self.ui.syn(); time.sleep(s)
        self.ui.write(e.EV_KEY, kc, 1); self.ui.syn(); time.sleep(s)
        self.ui.write(e.EV_KEY, kc, 0); self.ui.syn(); time.sleep(s)
        for m in reversed(mods): self.ui.write(e.EV_KEY, m, 0)
        if mods: self.ui.syn()
        self.mods.clear(); self._refresh_mods()

    # ---- Game Mode (gamescope overlay) ----
    def _xprop(self, target, atom, val):
        subprocess.run(["xprop", "-display", GS_DISPLAY, "-id", target,
                        "-f", atom, "32c", "-set", atom, str(val)], check=False)

    def _root_touch_mode(self, val):
        subprocess.run(["xprop", "-display", GS_DISPLAY, "-root", "-f",
                        "STEAM_TOUCH_CLICK_MODE", "32c",
                        "-set", "STEAM_TOUCH_CLICK_MODE", str(val)], check=False)

    def _read_touch_mode(self):
        try:
            out = subprocess.check_output(
                ["xprop", "-display", GS_DISPLAY, "-root", "STEAM_TOUCH_CLICK_MODE"],
                text=True, timeout=3)
            return int(out.strip().split("=")[-1])
        except Exception:
            return 4   # SteamOS default (Passthrough)

    def gm_show(self):
        """Become the input-capable gamescope overlay: STEAM_OVERLAY + STEAM_INPUT_FOCUS=2
        (touch->us so keys are tappable; keyboard stays with the game so our injected
        keystrokes land there), and switch touch mode to 1 (Left) so taps become clicks."""
        gw = self.get_window()
        if gw is None:
            return False
        try:
            xid = hex(gw.get_xid())
        except Exception:
            return False
        if self.orig_touch_mode is None:
            self.orig_touch_mode = self._read_touch_mode()
        self._xprop(xid, "STEAM_OVERLAY", 1)
        self._xprop(xid, "STEAM_INPUT_FOCUS", 2)
        self._root_touch_mode(1)
        return False   # one-shot for GLib.timeout_add

    def gm_hide(self):
        """Hand input back to the game and restore the original touch mode."""
        gw = self.get_window()
        if gw is not None:
            try: self._xprop(hex(gw.get_xid()), "STEAM_INPUT_FOCUS", 0)
            except Exception: pass
        self._root_touch_mode(self.orig_touch_mode if self.orig_touch_mode is not None else 4)


def setup_hotkey(config, toggle):
    """Watch input devices for the configured hotkey combo and call toggle().
    evdev-level, so it works regardless of which window has focus. Needs read
    access to /dev/input/event* (installer's udev rule + 'input' group)."""
    names = config.get("hotkey") or []
    codes = {getattr(e, n) for n in names if isinstance(getattr(e, n, None), int)}
    if not codes:
        return
    try:
        from evdev import InputDevice, list_devices
    except Exception:
        return
    pressed = set()

    def on_input(fd, cond, dev):
        try:
            for ev in dev.read():
                if ev.type != e.EV_KEY:
                    continue
                if ev.value == 1:
                    pressed.add(ev.code)
                elif ev.value == 0:
                    pressed.discard(ev.code)
                if codes <= pressed:           # all hotkey keys held together
                    pressed.clear()
                    toggle()
        except OSError:
            return False                       # device unplugged → drop the watch
        return True

    opened = 0
    for path in list_devices():
        try:
            dev = InputDevice(path)
            if dev.name == "claude-osk":        # skip our own injected-key device
                continue
            if codes <= set(dev.capabilities().get(e.EV_KEY, [])):
                GLib.io_add_watch(dev.fd, GLib.IO_IN, on_input, dev)
                opened += 1
        except Exception:
            pass
    if opened == 0:
        print("claude-osk: hotkey set but no readable input device "
              "(need 'input' group / udev rule)", file=sys.stderr)


def main():
    config = load_config()
    layout = load_layout(config.get("layout", "full"))
    rows, allkeys = resolve_rows(layout)
    if not allkeys:
        rows, allkeys = resolve_rows(DEFAULT_LAYOUT)
    locale = resolve_locale(config)

    w = OSK(config, rows, allkeys, locale)
    w.connect("destroy", Gtk.main_quit)
    open("/tmp/claude-kbd.pid", "w").write(str(os.getpid()))
    VIS = "/tmp/claude-kbd.vis"

    def _setvis(v):
        try: open(VIS, "w").write(v)
        except Exception: pass

    def _show(*_):
        w.show_all()
        if GAMEMODE:                      # set overlay atoms once gamescope has mapped us
            GLib.timeout_add(250, w.gm_show)
        _setvis("1"); return True

    def _hide(*_):
        if GAMEMODE: w.gm_hide()
        w.hide(); _setvis("0"); return True
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGUSR1, _show, None)
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGUSR2, _hide, None)

    def _toggle():
        cur = "0"
        try: cur = open(VIS).read().strip()
        except Exception: pass
        (_hide if cur == "1" else _show)()

    setup_hotkey(config, _toggle)

    _setvis("1" if os.environ.get("CLAUDE_KBD_SHOW") == "1" else "0")
    if os.environ.get("CLAUDE_KBD_SHOW") == "1":
        _show()
    Gtk.main()


if __name__ == "__main__":
    import faulthandler, traceback
    try:
        faulthandler.enable(open("/tmp/claude-kbd-fault.log", "w"))
    except Exception:
        pass
    try:
        main()
    except BaseException:
        try:
            with open("/tmp/claude-kbd-crash.log", "w") as _f:
                traceback.print_exc(file=_f)
        except Exception:
            pass
        raise
