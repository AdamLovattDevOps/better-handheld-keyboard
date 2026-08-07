#!/usr/bin/env python3
"""Better Handheld Keyboard — a dark on-screen keyboard that injects REAL keys via /dev/uinput.

Layout and appearance are configurable via JSON:
  ~/.config/handheld-kbd/config.json          (opacity, geometry, theme, layout, locale)
  ~/.config/handheld-kbd/layouts/<name>.json  (the button list)
  ~/.config/handheld-kbd/locales/<code>.json  (per-XKB-layout label overrides, e.g. us/gb)

Locale: the keyboard injects real keycodes, so what a key TYPES is decided by the
OS XKB layout. The 🌐 key switches the OS layout via KDE's KeyboardLayouts DBus and
re-skins the on-key labels to match, keeping label and output in sync.
If any JSON is missing/invalid, built-in defaults are used so it always comes up.
"""
import gi, sys, time, os, signal, json, subprocess, math, re
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk, GLib, Pango
from evdev import UInput, ecodes as e
GLib.set_prgname("handheld-kbd")   # app_id so the KWin window-rule can match us

CFG_DIR = os.path.expanduser("~/.config/handheld-kbd")

# Game Mode (gamescope): render as a transparent, input-capable external overlay
# instead of a KWin window. Enabled by the daemon when it detects gamescope.
GAMEMODE = os.environ.get("HANDHELD_KBD_GAMEMODE") == "1"
GS_DISPLAY = os.environ.get("HANDHELD_KBD_GS_DISPLAY", os.environ.get("DISPLAY", ":0"))

DEFAULT_CONFIG = {
    "layout": "full", "locale": "auto", "opacity": 0.72,
    # Transparency cycle: an opacity key (kind "opacity") steps through these values
    # (opaque → most transparent, then wraps). Persisted live, applied via the KWin script.
    "opacity_steps": [1.0, 0.85, 0.7, 0.55, 0.4, 0.25],
    "geometry": {"x": 0, "y": 378, "w": 1280, "h": 422},
    "key_size": [74, 64], "wide_size": [110, 64], "space_width": 360,
    "key_settle_ms": 20,
    # "Big" mode: a size-toggle key (kind "size") flips the keyboard between the
    # normal geometry above and this larger one, stretching every key to fill the
    # window (uses the wasted screen space). Toggles live — no relogin.
    # Sized so keys are ~square (1280/32 units ≈ 80px wide → ~81px rows) and the bottom
    # edge clears a ~56px KDE panel (256+488 = 744, panel occupies 744-800).
    "big_geometry": {"x": 0, "y": 256, "w": 1280, "h": 488},
    "big_key_h": 100,              # key-height floor in big mode (drives the Game Mode strip)
    "start_big": False,            # come up in big mode
    # KWin rule group that pins our window in Desktop Mode. Big mode rewrites this
    # rule's position/size live so the forced geometry follows the toggle. Must match
    # the UUID the installer writes; "" disables the live geometry change (grid still fills).
    "kwin_rule_id": "a8a95de3-82aa-4998-87c0-125fb8525143",
    # Dock on the built-in touchscreen even when an external display shifts the layout.
    # The window position is offset by this output's origin. "" = auto-detect eDP* (the
    # internal panel). Only matters with 2+ displays; single-display is unaffected.
    "internal_output": "",
    # Where the keyboard sits. "bottom" (the default) ignores `geometry` and docks flush
    # with the bottom of the internal panel, full width, at a FRACTION of the panel height
    # — so every device and resolution gets the same keyboard in the same place, like
    # Steam's own OSK. "custom" uses `geometry`, which is what the lock key writes after
    # you drag the keyboard somewhere. The reset key (kind "reset") goes back to "bottom".
    "position_mode": "bottom",
    "dock_height_frac": 0.42,
    "big_height_frac": 0.55,
    # The move key (kind "move") unlocks the keyboard: KWin stops forcing its position and
    # size, a drag bar appears, and you put it where you want. Pressing it again locks it
    # exactly there — it does not move the window — and saves the spot as `geometry`.
    "handle_height": 30,
    # "mirror": true  → the device's keyboard button summons us (via Steam's OSK).
    # "mirror": false → seamless mode: the daemon remaps the hardware keyboard button
    #                   (via InputPlumber) to fire dbus_trigger, which we listen for
    #                   below. No key emitted = nothing leaks to Steam/KDE. Read by daemon.
    "mirror": True,
    # InputPlumber DBus event the keyboard button is remapped to / we listen for.
    # "" = don't use the DBus trigger. (Used when mirror is false.)
    "dbus_trigger": "ui_osk",
    # Hotkey to TOGGLE the keyboard (evdev key names, pressed together). Used when
    # mirror is off (or as an extra). Map a controller chord to this combo in Steam
    # Input. [] = off. Needs /dev/input read access (installer's udev rule + 'input').
    "hotkey": [],
    # Show the keyboard automatically whenever a text field is focused (via AT-SPI
    # accessibility). Show-only: hiding stays manual (hide key / button). Desktop Mode
    # only — Game Mode has no accessibility bridge. Works alongside the button trigger.
    "show_on_focus": False,
    # Summon the keyboard with a swipe up from the bottom edge of the touchscreen.
    # Reads the touch device in parallel with the compositor (no grab); show-only.
    "gesture_summon": False,
    "gesture_device": "",       # touchscreen evdev path; "" = auto-detect
    "gesture_debug": False,     # log every stroke to /tmp/handheld-kbd-gesture.log for tuning
    # Swipe must START in the bottom (1 - gesture_start_frac) of the screen: 0.92 = the
    # bottom 8% edge only. Raise toward 1.0 to shrink the trigger strip further.
    "gesture_start_frac": 0.92,
    "gesture_travel_frac": 0.10,  # and travel up at least this fraction of screen height
    "gesture_fingers": 2,         # fingers required; 2 = two-finger swipe (won't clash with
                                  # normal 1-finger scrolling/swiping). Set 1 for one-finger.
    # Predictive text: a row of tappable suggestions above the keys. Learns what you
    # type (~/.local/share/handheld-kbd/learned.json). Corpus data is built once by
    # `handheld-kbd-build-dict`; without it, prediction still works from learning alone.
    "prediction": True,
    "suggestion_count": 3,
    "suggest_height": 44,         # px; the row is taken out of the key area
    "predict_learn": True,        # remember the words you commit (turn off = corpus only)
    # Swipe (glide) typing: drag across the letters instead of tapping them. Taps
    # are unaffected — a drag only counts once it travels far enough AND crosses
    # enough different letters to be unmistakably not a tap.
    "swipe": True,
    "swipe_min_travel": 1.6,      # multiples of key width the finger must travel
    "swipe_min_keys": 3,          # distinct letters it must cross
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
        print(f"handheld-kbd: using default config ({ex})", file=sys.stderr)
        return dict(DEFAULT_CONFIG)


def load_layout(name):
    try:
        with open(os.path.join(CFG_DIR, "layouts", f"{name}.json")) as f:
            lay = json.load(f)
        if not lay.get("rows"):
            raise ValueError("no rows")
        return lay
    except Exception as ex:
        print(f"handheld-kbd: using default layout ({ex})", file=sys.stderr)
        return dict(DEFAULT_LAYOUT)


_locale_index = None


def locale_badge(code):
    """What the 🌐 key shows for a layout.

    Not the xkb code: "il" is Israel rather than Hebrew, "in" is India rather than Hindi,
    and "us" and "gb" are both English — none of which tells you what you are about to
    type. The index carries a short badge per language, in its own script where that says
    more than two Latin letters would.
    """
    global _locale_index
    if _locale_index is None:
        try:
            with open(os.path.join(CFG_DIR, "locales", "index.json")) as f:
                _locale_index = json.load(f)
        except Exception:
            _locale_index = {}
    entry = _locale_index.get(code)
    if isinstance(entry, dict) and entry.get("badge"):
        return entry["badge"]
    return code.upper()


def load_locale_map(code):
    try:
        with open(os.path.join(CFG_DIR, "locales", f"{code}.json")) as f:
            return json.load(f)
    except Exception:
        return {}


def active_layout_code():
    """The XKB layout code (e.g. 'us'/'gb') KDE currently has active.

    Both the list and the index must come from the LIVE session. This used to read the
    list from kxkbrc and only the index from DBus — but kxkbrc is what the *next* session
    will load, not what this one is running: KWin builds its keymap at login and never
    re-reads the file. Edit the file (handheld-kbd-locales does) and the two go different
    lengths and orders, so list[index] names some other layout entirely — the keyboard
    drew Brazilian labels while the OS typed US.
    """
    try:
        out = subprocess.check_output(
            ["busctl", "--user", "call", "org.kde.keyboard", "/Layouts",
             "org.kde.KeyboardLayouts", "getLayoutsList"], text=True, timeout=3)
        # a(sss): triplets of (code, variant, display name), every string quoted.
        codes = out.split('"')[1::2][0::3]
        idx = int(subprocess.check_output(
            ["qdbus6", "org.kde.keyboard", "/Layouts", "org.kde.KeyboardLayouts.getLayout"],
            text=True, timeout=3).strip())
        if codes:
            return codes[idx] if 0 <= idx < len(codes) else codes[0]
    except Exception:
        pass
    # No live answer (e.g. kded still starting): fall back to the config file.
    try:
        ll = subprocess.check_output(
            ["kreadconfig6", "--file", "kxkbrc", "--group", "Layout", "--key", "LayoutList"],
            text=True, timeout=3).strip()
        codes = [c.strip() for c in ll.split(",") if c.strip()]
        return codes[0] if codes else "us"
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
            if kind in ("locale", "hide", "size", "opacity", "move", "reset"):
                dflt = {"locale": "🌐", "hide": "⌵", "size": "⤢",
                        "opacity": "◐", "move": "✥", "reset": "⤓"}.get(kind, "")
                row.append((k.get("label", dflt), None, kind, "", ""))
                continue
            name = k.get("key", "")
            kc = getattr(e, name, None)
            if not isinstance(kc, int):
                print(f"handheld-kbd: skipping unknown key '{name}'", file=sys.stderr)
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
button.hide {{ background: #5a1f1f; color: #ffd9d9; }}
button.hide:active {{ background: #c0392b; }}
button.suggest {{ background: {t.get('suggest_bg', '#242424')}; color: {t.get('suggest_fg', '#e8e8e8')};
                 font-size: 20px; border: 1px solid {t['key_border']}; }}
button.suggest:active {{ background: {t['key_active']}; }}
button.suggest-empty {{ background: transparent; border-color: transparent; }}
window.gm {{ background-color: rgba(0,0,0,0); }}
.gm-keys {{ background-color: rgba(12,12,12,0.82); }}
/* Free movement is self-evident once the bar is there — a lit-up blue block on top of
   that is noise. Muted bar, muted grips, and the key gets an outline rather than a fill. */
.handle-drag {{ background: {t.get('handle_bg', '#1e2733')}; }}
.handle-drag label {{ color: {t.get('handle_fg', '#9fb4c7')}; font-size: 12px; }}
.handle-grip {{ background: {t.get('handle_bg', '#1e2733')}; padding: 0 16px; }}
.handle-grip label {{ color: {t.get('handle_fg', '#9fb4c7')}; font-size: 15px; }}
button.unlocked {{ background: {t['special_bg']}; color: {t.get('handle_fg', '#9fb4c7')};
                  border: 1px solid {t.get('handle_fg', '#9fb4c7')}; }}
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
        self.ui = UInput({e.EV_KEY: allkeys}, name="handheld-kbd")
        self.mods = {}
        self.modbtns = []
        self.keybtns = []        # (button, key_name, base_label, base_shifted) for relabeling
        self.locale_btn = None
        self.size_btn = None
        self.opacity_btn = None
        self.move_btn = None
        self.reported_rect = None      # where KWin last said our window is (free-move)
        self.hide_cb = None            # set by main(); keeps the hide path single-sourced
        self.big = bool(config.get("start_big", False))
        # Unlocked = KWin's rule is on Remember, so the user can drag/resize by hand.
        # Always starts locked; an unlocked keyboard that got respawned would drift.
        self.unlocked = False
        self.handle = None
        self.norm_kh = config["key_size"][1]
        self.nrows = max(1, len(rows))
        prov = Gtk.CssProvider(); prov.load_from_data(build_css(config["theme"]))
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), prov,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        # Uniform aligned grid: every key snaps to a column grid (column_homogeneous),
        # widths come from per-kind unit spans, rows centred → tidy, even alignment.
        kh = config["key_size"][1]
        SPAN = {'': 2, 'wide': 3, 'mod': 3, 'space': 8, 'locale': 2, 'hide': 2, 'reset': 2, 'size': 2, 'opacity': 2}
        row_units = [sum(SPAN.get(k[2], 2) for k in row) for row in rows]
        maxu = max(row_units) if row_units else 1
        grid = Gtk.Grid()
        self.grid = grid
        grid.set_column_homogeneous(True)
        grid.set_halign(Gtk.Align.CENTER)
        grid.set_margin_top(4); grid.set_margin_bottom(4)
        for ri, row in enumerate(rows):
            col = (maxu - row_units[ri]) // 2          # centre each row on the unit grid
            for (label, kc, kind, shifted, name) in row:
                sp = SPAN.get(kind, 2)
                b = Gtk.Button(label=label)
                # A label must never dictate the window's size. The grid is
                # column-homogeneous, so ONE wide label widens every column — the 🌐 key
                # reading "🌐LATAM" pushed the whole keyboard to 1728px on a 1280px
                # desktop, and since GTK refuses to shrink a window below its natural
                # width, ⤓ could no longer bring it back either. Ellipsizing makes the
                # natural width tiny; the homogeneous grid still gives every key its
                # even share of whatever width the dock grants.
                ch = b.get_child()
                if isinstance(ch, Gtk.Label):
                    ch.set_ellipsize(Pango.EllipsizeMode.END)
                b.set_can_focus(False)
                b.set_hexpand(True); b.set_vexpand(False)
                b.set_size_request(-1, kh)
                if kind == 'locale':
                    b.get_style_context().add_class('special')
                    b.connect("clicked", self.on_locale)
                    self.locale_btn = b
                elif kind == 'size':
                    b.get_style_context().add_class('special')
                    b.connect("clicked", self.on_size)
                    self.size_btn = b
                elif kind == 'opacity':
                    b.get_style_context().add_class('special')
                    b.connect("clicked", self.on_opacity)
                    self.opacity_btn = b
                    b.set_label(f"{int(round(float(config.get('opacity', 0.72)) * 100))}%")
                elif kind == 'move':
                    b.get_style_context().add_class('special')
                    b.connect("clicked", self.on_move)
                    self.move_btn = b
                elif kind == 'reset':
                    b.get_style_context().add_class('special')
                    b.connect("clicked", self.on_reset)
                elif kind == 'hide':
                    b.get_style_context().add_class('hide')
                    b.connect("clicked", lambda *_: self.dismiss())
                elif kind == 'mod':
                    b.get_style_context().add_class('special')
                    b.connect("clicked", self.on_mod, kc)
                    self.modbtns.append((b, kc))
                else:
                    b.connect("clicked", self.on_key, kc)
                    self.keybtns.append((b, name, label, shifted))
                grid.attach(b, col, ri, sp, 1)
                col += sp
        self._init_prediction(rows)
        # Drag/resize bar, hidden until the move key unlocks the keyboard.
        self.handle = self._build_handle()
        self.handle.set_no_show_all(True)
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
            if self.sugbar is not None:
                self.sugbar.get_style_context().add_class("gm-keys")
                outer.pack_start(self.sugbar, False, False, 0)
            outer.pack_end(grid, False, False, 0)
            self.add(outer)
        else:
            # handle bar (hidden while locked) → suggestions → keys
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
            box.pack_start(self.handle, False, False, 0)
            if self.sugbar is not None:
                box.pack_start(self.sugbar, False, False, 0)
            box.pack_start(grid, True, True, 0)
            self.add(box)
        self.set_wmclass("handheld-kbd", "handheld-kbd")
        self.set_title("handheld-kbd")
        self.set_decorated(False)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_keep_above(True)
        g = config["geometry"]
        self.set_default_size(g["w"], g["h"])
        self.set_gravity(Gdk.Gravity.SOUTH)
        self.apply_locale(locale)
        self.apply_size()          # sync grid fill + window/rule geometry to self.big
        self._init_swipe()

    # ------------------------------------------------------------------
    # Predictive text
    # ------------------------------------------------------------------
    def _init_prediction(self, rows):
        """Set up the suggestion row. Everything here is best-effort: if the engine
        or its data is missing the keyboard must still come up as a plain keyboard,
        so any failure just leaves self.pred None and self.sugbar None."""
        self.sugbar = None
        self.pred = None
        self.sugbtns = []
        self.suggestions = []
        self.wordbuf = ""          # the word being typed, as far as we can tell
        self.prev_word = ""        # last committed word, for next-word prediction
        # kc -> the character that key produces unshifted (used to follow the typing)
        self.kc_char = {}
        # character -> (keycode, needs_shift), used to type a whole word back out
        self.charmap = {}
        for row in rows:
            for (label, kc, kind, shifted, name) in row:
                if kc is None or not label:
                    continue
                if len(label) == 1:
                    self.kc_char[kc] = label
                    self.charmap.setdefault(label, (kc, False))
                    if label.isalpha():
                        self.charmap.setdefault(label.upper(), (kc, True))
                if shifted and len(shifted) == 1:
                    self.charmap.setdefault(shifted, (kc, True))
        self.charmap.setdefault(" ", (e.KEY_SPACE, False))
        self.type_settle = self.cfg.get("predict_type_ms", 6) / 1000.0

        if not self.cfg.get("prediction", True):
            return
        try:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            from handheld_kbd_predict import Predictor, neighbours_from_rows
            self.pred = Predictor(neighbours=neighbours_from_rows(rows))
            if not self.pred.ready:
                # Self-heal an install that never built its dictionary (an upgrade, or an
                # installer run before this was automatic). Once, in the background.
                print("handheld-kbd: no prediction data — building it now",
                      file=sys.stderr)
                stamp = os.path.expanduser("~/.local/share/handheld-kbd/.build-started")
                builder = os.path.expanduser("~/.local/bin/handheld-kbd-build-dict")
                if os.access(builder, os.X_OK) and not os.path.exists(stamp):
                    try:
                        os.makedirs(os.path.dirname(stamp), exist_ok=True)
                        open(stamp, "w").close()
                        subprocess.Popen([builder],
                                         stdout=open("/tmp/handheld-kbd-build-dict.log", "w"),
                                         stderr=subprocess.STDOUT, start_new_session=True)
                    except Exception as ex:
                        print(f"handheld-kbd: could not start the builder ({ex})",
                              file=sys.stderr)
        except Exception as ex:
            print(f"handheld-kbd: prediction disabled ({ex})", file=sys.stderr)
            self.pred = None
            return

        n = max(1, int(self.cfg.get("suggestion_count", 3)))
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0, homogeneous=True)
        bar.set_size_request(-1, int(self.cfg.get("suggest_height", 44)))
        for i in range(n):
            b = Gtk.Button(label="")
            # Same rule as the keys: a long suggested word must not widen the window.
            ch = b.get_child()
            if isinstance(ch, Gtk.Label):
                ch.set_ellipsize(Pango.EllipsizeMode.END)
            b.set_can_focus(False)
            b.set_hexpand(True)
            b.get_style_context().add_class("suggest")
            b.get_style_context().add_class("suggest-empty")
            b.connect("clicked", self._on_suggestion, i)
            bar.pack_start(b, True, True, 0)
            self.sugbtns.append(b)
        self.sugbar = bar

    def _emit(self, kc, shift=False, settle=None):
        """Press and release one key, optionally with Shift held."""
        s = self.settle if settle is None else settle
        if shift:
            self.ui.write(e.EV_KEY, e.KEY_LEFTSHIFT, 1); self.ui.syn(); time.sleep(s)
        self.ui.write(e.EV_KEY, kc, 1); self.ui.syn(); time.sleep(s)
        self.ui.write(e.EV_KEY, kc, 0); self.ui.syn(); time.sleep(s)
        if shift:
            self.ui.write(e.EV_KEY, e.KEY_LEFTSHIFT, 0); self.ui.syn(); time.sleep(s)

    def _type_text(self, text):
        """Type a string as real keystrokes. Characters the layout can't produce are
        skipped rather than mangled."""
        for ch in text:
            kc = self.charmap.get(ch)
            if kc is None:
                continue
            self._emit(kc[0], kc[1], self.type_settle)

    def _erase(self, count):
        for _ in range(count):
            self._emit(e.KEY_BACKSPACE, False, self.type_settle)

    def _refresh_suggestions(self):
        if self.pred is None or not self.sugbtns:
            return
        try:
            words = self.pred.suggest(self.wordbuf.lower(), self.prev_word,
                                      n=len(self.sugbtns))
        except Exception as ex:
            print(f"handheld-kbd: suggest failed ({ex})", file=sys.stderr)
            words = []
        # Match the capitalisation of what is being typed, so tapping a suggestion
        # after "Leg" gives "Legion", not "legion".
        if self.wordbuf[:1].isupper():
            words = [w.capitalize() for w in words]
        self._show_suggestions(words)

    def _show_suggestions(self, words):
        """Paint the suggestion row. Used both by prediction (completions of what
        you are typing) and by swipe (the runner-up decodings)."""
        self.suggestions = words
        for i, b in enumerate(self.sugbtns):
            w = words[i] if i < len(words) else ""
            b.set_label(w)
            ctx = b.get_style_context()
            (ctx.add_class if not w else ctx.remove_class)("suggest-empty")
            b.set_sensitive(bool(w))

    def _on_suggestion(self, btn, idx):
        if idx >= len(self.suggestions):
            return
        word = self.suggestions[idx]
        self._erase(len(self.wordbuf))
        self._type_text(word + " ")
        if self.pred is not None and self.cfg.get("predict_learn", True):
            self.pred.learn(word, self.prev_word)
            self.pred.maybe_save()
        self.prev_word = word.lower()
        self.wordbuf = ""
        self._refresh_suggestions()

    def _commit_word(self):
        """The word being typed just ended (space/enter/punctuation)."""
        w = self.wordbuf.strip("'")
        if w and self.pred is not None and self.cfg.get("predict_learn", True):
            self.pred.learn(w, self.prev_word)
            self.pred.maybe_save()
        if w:
            self.prev_word = w.lower()
        self.wordbuf = ""

    # ---- swipe (glide) typing ----
    def _init_swipe(self):
        """Watch raw pointer/touch events so a drag across the keys becomes a word.

        We hook Gdk's event handler rather than connecting to the key buttons: the
        buttons need to keep seeing their own events so ordinary tapping is
        completely unaffected, and this way we observe the stream without consuming
        any of it.
        """
        self.swipe = None
        self._swipe_pts = []
        self._swipe_active = False
        self._swipe_is_gesture = False
        self._swipe_guard = 0.0        # ignore stray clicks just after a swipe
        self._key_boxes = None         # letter -> (centre, rect), in grid coords
        self.need_space = False
        if self.pred is None or not self.cfg.get("swipe", True):
            return
        try:
            from handheld_kbd_swipe import SwipeDecoder
            self.swipe = SwipeDecoder(self.pred)
        except Exception as ex:
            print(f"handheld-kbd: swipe disabled ({ex})", file=sys.stderr)
            return
        self.grid.connect("size-allocate", lambda *_: setattr(self, "_key_boxes", None))
        Gdk.event_handler_set(self._gdk_event, None)

    def _gdk_event(self, ev, *_):
        """Every event passes through here. It MUST always be forwarded, or the
        keyboard stops responding entirely."""
        try:
            self._swipe_feed(ev)
        except Exception:
            pass
        Gtk.main_do_event(ev)

    def _refresh_key_boxes(self):
        """Letter-key centres in grid coordinates. Rebuilt after any relayout
        (big-mode toggle, resize, display change)."""
        boxes, widths = {}, []
        for (b, name, base_label, base_shifted) in self.keybtns:
            label = (base_label or "").lower()
            if len(label) != 1 or not label.isalpha():
                continue
            res = b.translate_coordinates(self.grid, 0, 0)
            if not res:
                continue
            x, y = res[-2], res[-1]
            a = b.get_allocation()
            if a.width <= 1 or a.height <= 1:
                continue
            boxes[label] = (x + a.width / 2.0, y + a.height / 2.0)
            widths.append(a.width)
        self._key_boxes = boxes
        self._key_w = (sorted(widths)[len(widths) // 2] if widths else 1.0)
        if boxes and self.swipe is not None:
            self.swipe.set_keys(boxes, self._key_w)

    def _event_xy(self, ev):
        """Event position in grid coordinates, or None."""
        w = Gtk.get_event_widget(ev)
        if w is None:
            return None
        ok = ev.get_coords()
        if not ok or not ok[0]:
            return None
        res = w.translate_coordinates(self.grid, int(ok[1]), int(ok[2]))
        if not res:
            return None
        return (float(res[-2]), float(res[-1]))

    def _swipe_feed(self, ev):
        if self.swipe is None:
            return
        t = ev.type
        if t in (Gdk.EventType.TOUCH_BEGIN, Gdk.EventType.BUTTON_PRESS):
            if self._key_boxes is None:
                self._refresh_key_boxes()
            pt = self._event_xy(ev)
            self._swipe_pts = [pt] if pt else []
            self._swipe_active = bool(pt)
            self._swipe_is_gesture = False
        elif t in (Gdk.EventType.TOUCH_UPDATE, Gdk.EventType.MOTION_NOTIFY):
            if not self._swipe_active:
                return
            pt = self._event_xy(ev)
            if pt is None:
                return
            self._swipe_pts.append(pt)
            if not self._swipe_is_gesture:
                self._swipe_is_gesture = self._looks_like_gesture()
        elif t in (Gdk.EventType.TOUCH_END, Gdk.EventType.TOUCH_CANCEL,
                   Gdk.EventType.BUTTON_RELEASE):
            if not self._swipe_active:
                return
            pt = self._event_xy(ev)
            if pt:
                self._swipe_pts.append(pt)
            was = self._swipe_is_gesture
            self._swipe_active = False
            self._swipe_is_gesture = False
            if was:
                self._finish_swipe(list(self._swipe_pts))
            self._swipe_pts = []

    def _looks_like_gesture(self):
        """A drag only counts as a swipe once it is clearly not a tap: it has to
        travel a real distance AND pass over several different letters."""
        pts = self._swipe_pts
        if len(pts) < 4 or not self._key_boxes:
            return False
        kw = getattr(self, "_key_w", 1.0) or 1.0
        dist = sum(math.dist(pts[i - 1], pts[i]) for i in range(1, len(pts)))
        if dist < kw * float(self.cfg.get("swipe_min_travel", 1.6)):
            return False
        seen, last = [], None
        for p in pts:
            best, bd = None, kw * 0.75
            for ch, c in self._key_boxes.items():
                d = math.dist(p, c)
                if d < bd:
                    best, bd = ch, d
            if best and best != last:
                seen.append(best)
                last = best
        return len(seen) >= int(self.cfg.get("swipe_min_keys", 3))

    def _finish_swipe(self, pts):
        """Decode the gesture, type the best word, offer the runners-up."""
        # Anything already half-typed is a finished word once a swipe starts, so
        # commit it first — that also gives the decoder the right bigram context.
        if self.wordbuf:
            self._commit_word()
            self.need_space = True
        try:
            words = self.swipe.decode(pts, self.prev_word, n=len(self.sugbtns) or 3)
        except Exception as ex:
            print(f"handheld-kbd: swipe decode failed ({ex})", file=sys.stderr)
            return
        if not words:
            return
        best = words[0]
        if self.need_space:
            self._type_text(" ")
        self._type_text(best)
        self.wordbuf = best            # a suggestion tap now replaces the whole word
        self.need_space = True
        self._swipe_guard = time.time() + 0.3
        self._show_suggestions(words)

    def _track(self, kc, mods):
        """Follow the typing so we know the current word. We can't see the target
        application's text, so this is a model of it: anything that could move the
        caret somewhere we can't predict (arrows, Ctrl-shortcuts, Tab...) resets it
        rather than risking a wrong-word correction."""
        if self.pred is None:
            return
        self.need_space = False         # the user is driving now
        ctrlish = any(m in mods for m in (e.KEY_LEFTCTRL, e.KEY_RIGHTCTRL, e.KEY_LEFTALT,
                                          e.KEY_RIGHTALT, e.KEY_LEFTMETA, e.KEY_RIGHTMETA))
        ch = self.kc_char.get(kc)
        if ctrlish:                                   # a shortcut, not typing
            self.wordbuf = ""; self.prev_word = ""
        elif kc == e.KEY_BACKSPACE:
            self.wordbuf = self.wordbuf[:-1]
        elif kc == e.KEY_SPACE:
            self._commit_word()
        elif kc in (e.KEY_ENTER, e.KEY_KPENTER, e.KEY_TAB):
            self._commit_word(); self.prev_word = ""   # new line/field: no context
        elif ch and (ch.isalpha() or (ch == "'" and self.wordbuf)):
            shift = any(m in mods for m in (e.KEY_LEFTSHIFT, e.KEY_RIGHTSHIFT))
            self.wordbuf += ch.upper() if shift else ch
        elif ch:                                       # punctuation/digit ends a word
            self._commit_word()
        else:                                          # arrows, F-keys, Esc, Del...
            self.wordbuf = ""; self.prev_word = ""
        self._refresh_suggestions()

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
        self.lmap = load_locale_map(code)
        self._relabel()
        if self.locale_btn:
            self._set_label(self.locale_btn, "🌐" + locale_badge(code), "")

    def _relabel(self):
        """Paint the keys for the current layout and modifier state.

        With AltGr held the keys show their third level instead of their first. Printing
        all three at once was the alternative, and on a 7-inch panel three glyphs per key
        is unreadable — and most layouts have an AltGr symbol on nearly every key. Showing
        the level you are actually about to type is both clearer and smaller.
        """
        lmap = getattr(self, "lmap", {}) or {}
        alt_held = e.KEY_RIGHTALT in self.mods
        for (b, name, base_label, base_shifted) in self.keybtns:
            ov = lmap.get(name, {})
            if alt_held and ov.get("alt"):
                self._set_label(b, ov["alt"], "")
            else:
                self._set_label(b, ov.get("label", base_label),
                                ov.get("shifted", base_shifted))

    def on_locale(self, btn):
        if self._stray_tap():
            return
        before = active_layout_code()
        try:
            subprocess.run(["qdbus6", "org.kde.keyboard", "/Layouts",
                            "org.kde.KeyboardLayouts.switchToNextLayout"], timeout=3)
        except Exception as ex:
            print(f"handheld-kbd: layout switch failed ({ex})", file=sys.stderr)
        after = active_layout_code()
        if after == before:
            # switch had no effect — extra layouts are configured but not registered
            # yet (KWin reads kxkbrc only at login). Tell the user to log out.
            try: subprocess.Popen(["handheld-kbd-relogin"])
            except Exception: pass
        self.apply_locale(after)

    # ---- Big mode (larger keys that fill the window) ----
    def on_size(self, btn):
        if self._stray_tap():
            return
        self.big = not self.big
        self._persist_big()                  # written first: the script reads it back
        self.apply_size()

    def _persist_big(self):
        """Write the current mode back to config.json's start_big so it survives both
        the next relogin AND a mid-session respawn by the swap daemon (button-spam churn
        otherwise drops us back to normal)."""
        self._persist("start_big", self.big)

    def _persist(self, key, val):
        """Merge one key into config.json, preserving the rest; atomic write."""
        path = os.path.join(CFG_DIR, "config.json")
        try:
            try:
                with open(path) as f:
                    data = json.load(f)
            except Exception:
                data = {}
            data[key] = val
            os.makedirs(CFG_DIR, exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "w") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp, path)
        except Exception as ex:
            print(f"handheld-kbd: could not persist {key} ({ex})", file=sys.stderr)

    # ---- Transparency cycle ----
    def on_opacity(self, btn):
        """Step to the next (more transparent) opacity level, wrapping back to opaque.
        Persists it and applies live so it survives hide/show and respawns."""
        if self._stray_tap():
            return
        steps = self.cfg.get("opacity_steps", DEFAULT_CONFIG["opacity_steps"])
        cur = float(self.cfg.get("opacity", 0.72))
        nxt = next((s for s in steps if s < cur - 1e-6), steps[0])  # first below cur, else wrap
        self.cfg["opacity"] = nxt
        self._persist("opacity", nxt)
        self._apply_opacity(nxt)
        if self.opacity_btn:
            self.opacity_btn.set_label(f"{int(round(nxt * 100))}%")

    def _apply_opacity(self, val):
        """Our opacity is compositor-controlled (a Wayland client can't set its own),
        so patch the persistent handheld-kbd-opacity KWin script's `var OP` and reload
        it — reloading re-runs setOp on every window, applying the new value live and
        keeping it for future shows/respawns."""
        opscript = os.path.expanduser(
            "~/.local/share/kwin/scripts/handheld-kbd-opacity/contents/code/main.js")
        # Regenerate with the shared writer where it exists. Patching the file in place used
        # to be the only route, and it failed silently against a script that had no `var OP`
        # line — every reload then snapped the keyboard back to the value baked into that
        # file. Generating leaves nothing to go stale.
        writer = os.path.expanduser("~/.local/bin/handheld-kbd-kwin-script")
        written = False
        if os.access(writer, os.X_OK):
            try:
                subprocess.run([writer, "--opacity", str(val), "--out", opscript],
                               check=True, timeout=5)
                written = True
            except Exception as ex:
                print(f"handheld-kbd: kwin-script writer failed ({ex})", file=sys.stderr)
        if not written:
            try:
                with open(opscript) as f:
                    text = f.read()
                if "var OP =" in text:
                    text = re.sub(r"var OP = [^;]+;", f"var OP = {val};", text, count=1)
                else:
                    # very old script: the value is inlined in the handheld-kbd branch
                    text = re.sub(r'(indexOf\("handheld-kbd"\) !== -1\) w\.opacity = )[0-9.]+',
                                  rf"\g<1>{val}", text, count=1)
                with open(opscript, "w") as f:
                    f.write(text)
            except Exception as ex:
                print(f"handheld-kbd: could not patch opacity script ({ex})", file=sys.stderr)
        S = "org.kde.kwin.Scripting."
        for args in (["unloadScript", "handheld-kbd-opacity"],
                     ["loadScript", opscript, "handheld-kbd-opacity"],
                     ["start"]):
            try:
                subprocess.run(["qdbus6", "org.kde.KWin", "/Scripting", S + args[0]] + args[1:],
                               check=False, timeout=3)
            except Exception:
                pass

    def _placement_key(self):
        """Everything a placement depends on. Compared to skip needless compositor work."""
        outs = self._outputs()
        return (self.big, self.unlocked, self.cfg.get("position_mode", "bottom"),
                json.dumps(self.cfg.get("geometry", {}), sort_keys=True),
                tuple((o["name"], o["x"], o["y"], o["w"], o["h"]) for o in outs))

    def ensure_placed(self, force=False):
        """Place the window, but only if the placement actually needs redoing.

        Called on every show. Re-running the full path each time meant a kwriteconfig write,
        a KWin reconfigure and a script reload before the keyboard could appear, which is
        the slowest possible way to answer a button press."""
        key = self._placement_key()
        if not force and key == getattr(self, "_placed_key", None):
            return
        self._placed_key = key
        self.apply_size()

    def apply_size(self):
        """Toggle between the normal centred layout and 'big' mode, where every key
        stretches to fill the whole window (both axes) so no screen space is wasted."""
        big = self.big
        # Grid fill behaviour: big → keys expand to fill; normal → tidy centred cluster.
        self.grid.set_halign(Gtk.Align.FILL if big else Gtk.Align.CENTER)
        self.grid.set_valign(Gtk.Align.FILL)
        self.grid.set_row_homogeneous(big)
        # In Desktop big mode the resized window + row_homogeneous drive key height, so
        # keep the size_request floor at the normal height (a taller floor would exceed
        # the per-row allocation and distort the grid). Game Mode has no window resize,
        # so there big_key_h is what actually grows the docked strip.
        kh = self.cfg.get("big_key_h", 100) if (big and GAMEMODE) else self.norm_kh
        g = (self.cfg.get("big_geometry", DEFAULT_CONFIG["big_geometry"])
             if big else self.cfg.get("geometry", DEFAULT_CONFIG["geometry"]))
        rect = None
        if not GAMEMODE:
            # Work out the target window height FIRST, then size the keys to fit inside it.
            # Without this the keys keep their natural height, the window's minimum height
            # exceeds the dock height, and the compositor hands back a taller window whose
            # bottom hangs off the screen. It also means the keyboard occupies the same
            # fraction of the display on a 800px panel as on a 1200px one.
            rect = self._slot_rect(g, big)
            # The suggestion row eats into that height. apply_size() also runs before the
            # window is realised, where the row measures as ~0 — so trust the configured
            # height (plus its margins) and only prefer the measured value once it is real.
            bar = 0
            if self.sugbar is not None:
                bar = max(int(self.cfg.get("suggest_height", 44)) + 8,
                          self.sugbar.get_preferred_height()[0])
            handle = (int(self.cfg.get("handle_height", 30)) + 4) if self.unlocked else 0
            fit = (rect["h"] - bar - handle - 8) // self.nrows   # 8 = grid margins
            kh = max(24, min(kh, fit))
        for child in self.grid.get_children():
            child.set_vexpand(big)
            child.set_valign(Gtk.Align.FILL)
            child.set_size_request(-1, kh)
        if self.size_btn:
            self._set_label(self.size_btn, "⤡" if big else "⤢", "")
        # Window geometry. Game Mode is a fullscreen gamescope overlay (keys docked at
        # the bottom) — the taller key rows above already grow the strip, no resize/rule.
        if GAMEMODE:
            return
        rect = rect or self._slot_rect(g, big)
        self.resize(rect["w"], rect["h"])
        self.move(rect["x"], rect["y"])
        if self.unlocked:                    # the user is placing it by hand
            return
        # The KWin script is the only thing that positions the window — in both docked and
        # custom modes. A window rule doing it too meant two authorities re-asserting
        # different rects, which is why a dragged keyboard jumped back a second later.
        self._set_rule_mode(1)               # DontAffect: rules never place us
        self._reload_kwin_script()

    def _is_internal(self, name):
        want = (self.cfg.get("internal_output", "") or "").lower()
        n = (name or "").lower()
        return n.startswith(want) if want else n.startswith("edp")

    def _outputs(self):
        """Enabled displays as [{name, x, y, w, h, internal}], internal panel first, in
        LOGICAL pixels — the coordinate space KWin rules and window positions use.

        Scaling is the whole reason this is careful. A Legion Go 2 is a 1920x1200 panel at
        scale 1.5, so the compositor's desktop is 1280x800: writing 1920-wide physical
        pixels into a KWin rule puts the window mostly off the side of a 1280-wide desktop.
        GDK reports exactly the logical space we need, so ask it first; kscreen-doctor is
        the fallback and there we divide the mode size by the output's scale ourselves."""
        outs = []
        try:
            display = Gdk.Display.get_default()
            for i in range(display.get_n_monitors()):
                m = display.get_monitor(i)
                g = m.get_geometry()          # already logical on both X11 and Wayland
                # GDK's model is like "eDP-1-AMS881KB01-0"; the connector is the head of it
                name = (m.get_model() or "").strip()
                outs.append({"name": name, "x": g.x, "y": g.y, "w": g.width, "h": g.height,
                             "internal": self._is_internal(name), "primary": m.is_primary()})
        except Exception as ex:
            print(f"handheld-kbd: GDK monitors unavailable ({ex})", file=sys.stderr)
        if not outs:
            try:
                data = json.loads(subprocess.check_output(
                    ["kscreen-doctor", "-j"], text=True, timeout=3))
                for o in data.get("outputs", []):
                    if not o.get("enabled"):
                        continue
                    pos = o.get("pos") or {}
                    mode = next((m for m in (o.get("modes") or [])
                                 if m.get("id") == o.get("currentModeId")), {})
                    sz = mode.get("size") or o.get("size") or {}
                    if not sz.get("width") or not sz.get("height"):
                        continue
                    scale = float(o.get("scale") or 1) or 1.0
                    name = o.get("name") or ""
                    outs.append({
                        "name": name,
                        "x": int(pos.get("x", 0)), "y": int(pos.get("y", 0)),
                        "w": int(round(int(sz["width"]) / scale)),
                        "h": int(round(int(sz["height"]) / scale)),
                        "internal": self._is_internal(name), "primary": False,
                    })
            except Exception:
                return []
        outs.sort(key=lambda o: (not o["internal"], not o.get("primary"), o["x"], o["y"]))
        return outs

    def _panel_origin(self):
        """Logical origin (x,y) of the INTERNAL panel (eDP*), so we dock on the built-in
        touchscreen even when an external display shifts the coordinate space (an external
        at 0,0 would otherwise steal position 0,378). Returns (0,0) on a single display or
        any failure — i.e. the original behaviour."""
        outs = self._outputs()
        if len(outs) < 2:
            return (0, 0)                    # single display → no offset needed
        m = next((o for o in outs if o["internal"]), None)
        return (m["x"], m["y"]) if m else (0, 0)

    # ---- Unlock / drag / lock ----
    def _set_rule_mode(self, mode):
        """Set our KWin rule's position/size mode: 2 = Force, 4 = Remember.

        Forced is the normal state — it keeps the keyboard docked and stops anything
        nudging it. Remember lets the user drag and resize it freely, and KWin writes
        wherever they leave it straight back into kwinrulesrc, which is how we read the
        result afterwards (a Wayland client can't ask where its own window is)."""
        rid = self.cfg.get("kwin_rule_id", "")
        if not rid:
            return False
        try:
            for key in ("positionrule", "sizerule"):
                subprocess.run(["kwriteconfig6", "--file", "kwinrulesrc", "--group", rid,
                                "--key", key, str(mode)], check=False, timeout=3)
            subprocess.run(["qdbus6", "org.kde.KWin", "/KWin", "reconfigure"],
                           check=False, timeout=3)
            return True
        except Exception as ex:
            print(f"handheld-kbd: rule mode {mode} failed ({ex})", file=sys.stderr)
            return False

    def request_geometry(self):
        """Ask KWin, right now, where our window is.

        Relying on frameGeometryChanged alone is not enough: after a real interactive drag
        the signal may not have been delivered by the time the user taps ✓, and then we
        would fall back to reading kwinrulesrc — which still holds the OLD forced rect, so
        the keyboard appears to jump home. This pushes the answer to us instead."""
        js = "/tmp/handheld-kbd-report.js"
        try:
            with open(js, "w") as f:
                f.write(
                    'workspace.windowList().forEach(function(w){\n'
                    '  if (("" + w.resourceClass).indexOf("handheld-kbd") !== -1) {\n'
                    '    var g = w.frameGeometry;\n'
                    '    callDBus("org.handheld.Keyboard", "/org/handheld/Keyboard",\n'
                    '             "org.handheld.Keyboard", "SetGeometry",\n'
                    '             "" + g.x + "," + g.y + "," + g.width + "," + g.height);\n'
                    '  }\n});\n')
            S = "org.kde.kwin.Scripting."
            name = "handheld-kbd-report"
            for args in (["unloadScript", name], ["loadScript", js, name], ["start"]):
                subprocess.run(["qdbus6", "org.kde.KWin", "/Scripting", S + args[0]] + args[1:],
                               check=False, timeout=3)
        except Exception as ex:
            print(f"handheld-kbd: geometry request failed ({ex})", file=sys.stderr)

    def set_reported_geometry(self, rect):
        """KWin telling us where our window actually is, as "x,y,w,h" (logical pixels)."""
        try:
            x, y, w, h = (int(v) for v in rect.split(","))
        except Exception:
            return
        if w >= 160 and h >= 80:
            if self.reported_rect is None:
                print(f"handheld-kbd: KWin reports geometry {x},{y} {w}x{h}", file=sys.stderr)
            self.reported_rect = {"x": x, "y": y, "w": w, "h": h}

    def _reload_kwin_script(self, report=False):
        """Regenerate the KWin script and reload it. The script reads the dock settings out
        of config.json, so this is how a mode/size change reaches the compositor."""
        writer = os.path.expanduser("~/.local/bin/handheld-kbd-kwin-script")
        opscript = os.path.expanduser(
            "~/.local/share/kwin/scripts/handheld-kbd-opacity/contents/code/main.js")
        if not os.access(writer, os.X_OK):
            return
        try:
            args = [writer, "--out", opscript, "--report", "1" if report else "0"]
            if report:
                args += ["--dock", "0"]   # hands off while the user is placing it
            subprocess.run(args, check=False, timeout=5)
            S = "org.kde.kwin.Scripting."
            for args in (["unloadScript", "handheld-kbd-opacity"],
                         ["loadScript", opscript, "handheld-kbd-opacity"],
                         ["start"]):
                subprocess.run(["qdbus6", "org.kde.KWin", "/Scripting", S + args[0]] + args[1:],
                               check=False, timeout=3)
        except Exception as ex:
            print(f"handheld-kbd: kwin script reload failed ({ex})", file=sys.stderr)

    def _read_rule_geometry(self):
        """What KWin remembered while we were unlocked: {"x","y","w","h"} or None."""
        rid = self.cfg.get("kwin_rule_id", "")
        if not rid:
            return None
        try:
            def read(key):
                return subprocess.check_output(
                    ["kreadconfig6", "--file", "kwinrulesrc", "--group", rid, "--key", key],
                    text=True, timeout=3).strip()
            px, py = (int(v) for v in read("position").split(",", 1))
            sw, sh = (int(v) for v in read("size").split(",", 1))
            if sw < 160 or sh < 80:
                return None
            return {"x": px, "y": py, "w": sw, "h": sh}
        except Exception:
            return None

    def on_move(self, btn):
        """Free move: turn the drag bar on, put the keyboard wherever you like, turn it off
        again. Leaving free-move keeps it exactly where you left it; ⤓ (reset) is what puts
        it back to the default dock."""
        if self._stray_tap():
            return
        if GAMEMODE:
            # gamescope draws us as a fullscreen overlay — there is no window to drag.
            print("handheld-kbd: move/lock is Desktop Mode only", file=sys.stderr)
            return
        self.unlocked = not self.unlocked
        if self.unlocked:
            self.reported_rect = None
            self._set_rule_mode(1)              # DontAffect: nothing pins it while dragging
            self._reload_kwin_script(report=True)   # script stops placing, starts reporting
        else:
            # Leaving free-move must never move the window. Ask KWin where it is, give the
            # reply a moment to land (the main loop has to stay free to receive it), then
            # pin it exactly there.
            self.reported_rect = None     # never finish on a value from before the drag
            self.request_geometry()
            self._finish_tries = 0
            # Wait for the answer instead of guessing how long it takes. A fixed delay was
            # a race: when the reply landed late we had already given up, and giving up
            # means the script re-docks — which is exactly the "✓ resets it" report.
            GLib.timeout_add(100, self._finish_move)
        self._apply_handle()

    def _finish_move(self):
        g = self.reported_rect
        if not g:
            self._finish_tries = getattr(self, "_finish_tries", 0) + 1
            if self._finish_tries <= 20:          # up to ~2s, re-asking as we go
                if self._finish_tries in (3, 7, 12, 17):
                    self.request_geometry()
                return True                       # keep waiting
            # No answer: freeze by doing nothing. Forcing the rect from kwinrulesrc here is
            # what used to yank the keyboard back to the dock, because that file still holds
            # the old forced position until the window closes.
            # Never leave it in docking mode after a move: docking re-asserts itself on the
            # next geometry change, which is the keyboard snapping back a moment later —
            # intermittent, because it only happens when the reply was too slow. "free"
            # means nothing places the window at all, so where the user left it is where it
            # stays. ⤓ is how you get back to the dock.
            print("handheld-kbd: no geometry from KWin; freezing placement so it cannot "
                  "snap back", file=sys.stderr)
            self.cfg["position_mode"] = "free"
            self._persist("position_mode", "free")
            self._reload_kwin_script(report=False)
            self._placed_key = None
            return False
        # Stored exactly as KWin reports it, in absolute compositor coordinates, with no
        # clamping: a keyboard you moved by hand should stay where you put it, including
        # half off the edge, like any other window. ⤓ is the way back to the dock.
        self.cfg["geometry"] = dict(g)
        self.cfg["position_mode"] = "custom"
        # Persist BEFORE regenerating: the script reads both to decide where to hold the
        # window, and would otherwise reload still thinking it should dock.
        self._persist("geometry", self.cfg["geometry"])
        self._persist("position_mode", "custom")
        self._reload_kwin_script(report=False)
        self._placed_key = None
        return False

    def on_reset(self, btn):
        """Reset: back to the default bottom dock, forgetting wherever it was moved to."""
        if self._stray_tap():
            return
        self.unlocked = False
        self.cfg["position_mode"] = "bottom"
        self._persist("position_mode", "bottom")
        self._last_rect = None
        self.ensure_placed(force=True)       # switches the rule off and reloads the script
        self._apply_handle()

    def _apply_handle(self):
        """Show the drag bar and resize grips only while unlocked, and relabel the key."""
        if self.handle is not None:
            if self.unlocked:
                self.handle.set_no_show_all(False)
                self.handle.show_all()       # the bar was never shown, so show its children
            else:
                self.handle.hide()
                self.handle.set_no_show_all(True)
        if self.move_btn:
            self._set_label(self.move_btn, "✓" if self.unlocked else "✥", "")
            ctx = self.move_btn.get_style_context()
            (ctx.add_class if self.unlocked else ctx.remove_class)("unlocked")

    def _build_handle(self):
        """A thin bar: drag anywhere along it to move, use either end to resize.

        A Wayland client can't place itself, so both gestures hand off to the compositor
        (begin_move_drag / begin_resize_drag) — the same mechanism a titlebar uses."""
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        bar.set_size_request(-1, int(self.cfg.get("handle_height", 30)))

        def grip(edge, label):
            ev = Gtk.EventBox()
            ev.add(Gtk.Label(label=label))
            ev.get_style_context().add_class("handle-grip")
            ev.connect("button-press-event", self._on_resize_press, edge)
            return ev

        drag = Gtk.EventBox()
        drag.add(Gtk.Label(label="drag to move  ·  ✓ when done  ·  ⤓ reset position"))
        drag.get_style_context().add_class("handle-drag")
        drag.connect("button-press-event", self._on_drag_press)
        bar.pack_start(grip(Gdk.WindowEdge.NORTH_WEST, "⤡"), False, False, 0)
        bar.pack_start(drag, True, True, 0)
        bar.pack_start(grip(Gdk.WindowEdge.NORTH_EAST, "⤢"), False, False, 0)
        return bar

    def _on_drag_press(self, widget, event):
        try:
            self.begin_move_drag(event.button, int(event.x_root), int(event.y_root),
                                 event.time)
        except Exception as ex:
            print(f"handheld-kbd: move drag failed ({ex})", file=sys.stderr)
        return True

    def _on_resize_press(self, widget, event, edge):
        try:
            self.begin_resize_drag(edge, event.button, int(event.x_root),
                                   int(event.y_root), event.time)
        except Exception as ex:
            print(f"handheld-kbd: resize drag failed ({ex})", file=sys.stderr)
        return True

    def _clamp_rect(self, rect, out):
        """Keep a rect inside `out`, whatever the resolution.

        The shipped geometry is sized for a 1280x800 panel, so on anything shorter or
        narrower the configured rect would hang off the edge — and a Wayland window that
        is partly outside its output still takes taps while not being fully visible. Sizes
        shrink to fit first, then the position is pulled back inside. No-op when it
        already fits, so the usual case is untouched."""
        if not out:
            return rect
        w = max(160, min(rect["w"], out["w"]))
        h = max(80, min(rect["h"], out["h"]))
        x = min(max(rect["x"], out["x"]), out["x"] + out["w"] - w)
        y = min(max(rect["y"], out["y"]), out["y"] + out["h"] - h)
        return {"x": x, "y": y, "w": w, "h": h}

    def _dock_rect(self, out, big):
        """The default spot: full width, flush with the bottom edge, height a fixed
        fraction of the panel. Steam's own on-screen keyboard sits like this, and because
        it's a fraction rather than a pixel count it lands identically on a 1280x800 Deck,
        an 800p OLED and a 1920x1200 Legion Go."""
        frac = float(self.cfg.get("big_height_frac" if big else "dock_height_frac",
                                  DEFAULT_CONFIG["big_height_frac" if big else "dock_height_frac"]))
        h = max(120, min(int(round(out["h"] * frac)), out["h"]))
        return {"x": out["x"], "y": out["y"] + out["h"] - h, "w": out["w"], "h": h}

    def _slot_rect(self, g, big=False):
        """Where the window goes: the bottom dock by default, or the position the user
        dragged it to and locked (`position_mode: custom`). Always clamped to the panel."""
        outs = self._outputs()
        anchor = next((o for o in outs if o["internal"]), outs[0] if outs else None)
        if self.cfg.get("position_mode", "bottom") != "custom" or not g:
            if anchor:
                return self._dock_rect(anchor, big)   # the dock IS clamped: it is ours to place
            return dict(g or DEFAULT_CONFIG["geometry"])
        # Custom: the user placed it. Hand it back untouched — no clamping, no anchoring.
        return {"x": g["x"], "y": g["y"], "w": g["w"], "h": g["h"]}

    def _apply_kwin_geometry(self, g):
        """Rewrite our KWin window-rule's forced position/size so it follows the toggle
        and the internal-panel anchor; without this the Force rule would snap the window
        back. Skips the write when the rect is unchanged (re-anchoring on every show would
        otherwise reconfigure KWin needlessly and flicker)."""
        rid = self.cfg.get("kwin_rule_id", "")
        if not rid:
            return
        rect = (g["x"], g["y"], g["w"], g["h"])
        if rect == getattr(self, "_last_rect", None):
            return
        self._last_rect = rect
        try:
            for key, val in (("position", f"{g['x']},{g['y']}"), ("size", f"{g['w']},{g['h']}")):
                subprocess.run(["kwriteconfig6", "--file", "kwinrulesrc", "--group", rid,
                                "--key", key, val], check=False, timeout=3)
            subprocess.run(["qdbus6", "org.kde.KWin", "/KWin", "reconfigure"],
                           check=False, timeout=3)
        except Exception as ex:
            print(f"handheld-kbd: kwin geometry update failed ({ex})", file=sys.stderr)

    def _refresh_mods(self):
        for b, k in self.modbtns:
            ctx = b.get_style_context()
            (ctx.add_class if k in self.mods else ctx.remove_class)('mod-on')

    def on_mod(self, btn, kc):
        if self._stray_tap():
            return
        if kc in self.mods: del self.mods[kc]
        else: self.mods[kc] = True
        self._refresh_mods()
        if kc == e.KEY_RIGHTALT:
            self._relabel()

    def _stray_tap(self):
        """True just after a swipe ends: GTK may still deliver a click for the key the
        finger lifted over, which is not something the user meant to press."""
        return time.time() < getattr(self, "_swipe_guard", 0.0)

    def on_key(self, btn, kc):
        if self._stray_tap():
            return
        s = self.settle
        mods = list(self.mods)
        for m in mods: self.ui.write(e.EV_KEY, m, 1)
        if mods: self.ui.syn(); time.sleep(s)
        self.ui.write(e.EV_KEY, kc, 1); self.ui.syn(); time.sleep(s)
        self.ui.write(e.EV_KEY, kc, 0); self.ui.syn(); time.sleep(s)
        for m in reversed(mods): self.ui.write(e.EV_KEY, m, 0)
        if mods: self.ui.syn()
        had_alt = e.KEY_RIGHTALT in mods
        self.mods.clear(); self._refresh_mods()
        if had_alt:
            self._relabel()          # the third level is spent; go back to showing the first
        self._track(kc, mods)

    def dismiss(self):
        """Hide key: put us away, and in mirror mode get rid of Steam's on-screen keyboard
        too — an invisible-but-mapped window of theirs still swallows every tap in its
        rectangle (ValveSoftware/steam-for-linux#9099). One shot, on the press; this used
        to be a latch that a 10Hz poll picked up."""
        if self._stray_tap():
            return
        if self.cfg.get("mirror", True) and not GAMEMODE:
            self._dismiss_steam_osk()
        if self.hide_cb is not None:
            self.hide_cb()               # routes through main()'s hide, keeping state in sync
            return
        if GAMEMODE:
            self.gm_hide()
        self.hide()

    def _dismiss_steam_osk(self):
        """Unmap Steam's OSK, once, in the background so the hide stays instant."""
        script = (
            'for w in $(xwininfo -root -tree 2>/dev/null | grep -i "$1" '
            '| grep -oE "0x[0-9a-f]+"); do xdotool windowunmap "$w" 2>/dev/null; done')
        try:
            subprocess.Popen(["sh", "-c", script, "sh", "Steam Input On-screen Keyboard"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as ex:
            print(f"handheld-kbd: could not dismiss Steam's OSK ({ex})", file=sys.stderr)

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


SERVICE_XML = """
<node>
  <interface name='org.handheld.Keyboard'>
    <method name='Show'/>
    <method name='Hide'/>
    <method name='Toggle'/>
    <method name='FreeMove'/>
    <method name='Reset'/>
    <method name='SetGeometry'>
      <arg type='s' name='rect' direction='in'/>
    </method>
  </interface>
</node>
"""

_service_keepalive = []


def setup_service(show, hide, toggle, set_geometry=None, free_move=None, reset=None):
    """Expose Show/Hide/Toggle on the session bus.

    This is what replaced polling. The KWin script calls these the moment Steam's
    on-screen keyboard maps or unmaps, so the swap daemon no longer has to walk the window
    tree ten times a second to notice — that poll was both the latency in summoning the
    keyboard and a constant drip of xwininfo/xprop processes."""
    from gi.repository import Gio
    handlers = {"Show": show, "Hide": hide, "Toggle": toggle,
                "FreeMove": free_move, "Reset": reset}

    def on_call(conn, sender, path, iface, method, params, invocation):
        try:
            if method == "SetGeometry" and set_geometry is not None:
                set_geometry(params.unpack()[0])
            else:
                fn = handlers.get(method)
                if fn is not None:
                    fn()
        except Exception as ex:
            print(f"handheld-kbd: {method} failed ({ex})", file=sys.stderr)
        invocation.return_value(None)

    def on_acquired(conn, name, _user=None):   # GLib calls this with 2 args
        try:
            node = Gio.DBusNodeInfo.new_for_xml(SERVICE_XML)
            # register_object() is deprecated in newer PyGObject; the *_with_closures form
            # is the replacement but doesn't exist everywhere yet.
            reg = getattr(conn, "register_object_with_closures", None) or conn.register_object
            reg("/org/handheld/Keyboard", node.interfaces[0], on_call)
        except Exception as ex:
            print(f"handheld-kbd: service registration failed ({ex})", file=sys.stderr)

    try:
        oid = Gio.bus_own_name(Gio.BusType.SESSION, "org.handheld.Keyboard",
                               Gio.BusNameOwnerFlags.REPLACE, on_acquired, None, None)
        _service_keepalive.append(oid)
    except Exception as ex:
        print(f"handheld-kbd: could not own the service name ({ex})", file=sys.stderr)


_dbus_keepalive = []   # keep the bus connection alive or the subscription is GC'd


def setup_dbus_trigger(config, toggle):
    """Toggle when InputPlumber fires its configured DBus InputEvent (the hardware
    keyboard button, remapped to this event). No key is emitted, so nothing leaks to
    Steam/KDE. This is the seamless trigger on InputPlumber handhelds."""
    ev = config.get("dbus_trigger") or ""
    if not ev:
        return
    try:
        from gi.repository import Gio
        bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
    except Exception as ex:
        print(f"handheld-kbd: dbus trigger unavailable ({ex})", file=sys.stderr)
        return

    def on_sig(conn, sender, path, iface, signal, params):
        try:
            name, val = params.unpack()
        except Exception:
            return
        if name == ev and val >= 1.0:        # press only (release = 0.0)
            toggle()
    bus.signal_subscribe(None, "org.shadowblip.Input.DBusDevice", "InputEvent",
                         None, None, Gio.DBusSignalFlags.NONE, on_sig)
    _dbus_keepalive.append(bus)              # prevent GC of the subscribed connection
    print(f"handheld-kbd: dbus trigger listening for {ev}", file=sys.stderr)


_atspi_keepalive = []   # keep the AT-SPI listener alive or it's GC'd


def setup_focus_trigger(config, show):
    """show_on_focus: pop the keyboard whenever an editable text field gains focus,
    detected via AT-SPI accessibility events. Show-only — hiding stays manual. Desktop
    Mode only (Game Mode / gamescope has no accessibility bridge). Runs on the same
    GLib main loop as GTK, so no extra thread."""
    if not config.get("show_on_focus", False) or GAMEMODE:
        return
    # AT-SPI often can't auto-locate the running a11y bus from a service env; point it there.
    if not os.environ.get("AT_SPI_BUS_ADDRESS"):
        try:
            addr = subprocess.check_output(
                ["qdbus6", "org.a11y.Bus", "/org/a11y/bus", "org.a11y.Bus.GetAddress"],
                text=True, timeout=3).strip()
            if addr:
                os.environ["AT_SPI_BUS_ADDRESS"] = addr
        except Exception:
            pass
    try:
        gi.require_version("Atspi", "2.0")
        from gi.repository import Atspi
    except Exception as ex:
        print(f"handheld-kbd: show_on_focus unavailable ({ex})", file=sys.stderr)
        return
    edit_roles = {Atspi.Role.ENTRY, Atspi.Role.TEXT, Atspi.Role.PASSWORD_TEXT,
                  Atspi.Role.DOCUMENT_TEXT, Atspi.Role.TERMINAL, Atspi.Role.DOCUMENT_FRAME}

    def on_focus(ev):
        try:
            if ev.detail1 != 1:                    # 1 = gained focus
                return
            acc = ev.source
            if acc.get_state_set().contains(Atspi.StateType.EDITABLE) or acc.get_role() in edit_roles:
                show()
        except Exception:
            pass
    try:
        lis = Atspi.EventListener.new(on_focus)
        lis.register("object:state-changed:focused")
        _atspi_keepalive.append(lis)
        print("handheld-kbd: show_on_focus listening (AT-SPI editable focus)", file=sys.stderr)
    except Exception as ex:
        print(f"handheld-kbd: show_on_focus register failed ({ex})", file=sys.stderr)


def setup_gesture(config, show):
    """gesture_summon: a two-finger (gesture_fingers) swipe up from the bottom edge of
    the touchscreen shows the keyboard. Two fingers avoids clashing with normal
    one-finger scrolling/swiping. Reads the touch device in parallel with the
    compositor (no exclusive grab), on the GLib loop. Show-only. Desktop Mode only."""
    if not config.get("gesture_summon", False) or GAMEMODE:
        return
    try:
        from evdev import InputDevice, list_devices
    except Exception:
        return
    dev = None
    try:
        path = config.get("gesture_device", "") or ""
        if path:
            dev = InputDevice(path)
        else:                                   # auto-detect: a real touchSCREEN
            # Match multitouch + BTN_TOUCH, but require INPUT_PROP_DIRECT (touchscreen)
            # and skip INPUT_PROP_POINTER (touchpads such as a Magic Trackpad also report
            # BTN_TOUCH + ABS_MT_POSITION_X and would otherwise hijack the gesture).
            fallback = None
            for p in sorted(list_devices()):
                try:
                    d = InputDevice(p)
                    caps = d.capabilities()
                    if e.BTN_TOUCH not in caps.get(e.EV_KEY, []) or \
                       e.ABS_MT_POSITION_X not in [c for c, _ in caps.get(e.EV_ABS, [])]:
                        continue
                    props = d.input_props()
                    if e.INPUT_PROP_POINTER in props:       # touchpad → not a touchscreen
                        continue
                    if e.INPUT_PROP_DIRECT in props:        # definite touchscreen → take it
                        dev = d
                        break
                    if fallback is None:                    # ambiguous; last resort
                        fallback = d
                except Exception:
                    continue
            if dev is None:
                dev = fallback
    except Exception as ex:
        print(f"handheld-kbd: gesture device open failed ({ex})", file=sys.stderr)
        return
    if dev is None:
        print("handheld-kbd: gesture_summon on but no touchscreen found", file=sys.stderr)
        return
    absinfo = dict(dev.capabilities().get(e.EV_ABS, []))
    yaxis = absinfo.get(e.ABS_MT_POSITION_Y) or absinfo.get(e.ABS_Y)
    ymax = yaxis.max if yaxis else 1
    START_FRAC = float(config.get("gesture_start_frac", 0.92))   # start in bottom (1-frac) edge
    TRAVEL_FRAC = float(config.get("gesture_travel_frac", 0.10))  # travel up ≥ this frac of height
    MAX_MS = 1200                                                 # within 1.2s
    dbg = config.get("gesture_debug", False)
    FINGERS = int(config.get("gesture_fingers", 2))   # require this many fingers; 2 avoids
                                                       # clashing with 1-finger scroll/swipe
    # Track each contact via the MT-B slot protocol (ABS_MT_SLOT + ABS_MT_TRACKING_ID).
    # A gesture spans first-finger-down .. last-finger-up; fire show() only if it peaked at
    # EXACTLY FINGERS contacts (so 2- and 3-finger gestures stay distinct) and they all
    # started in the bottom edge and moved up.
    strokes = {}                                       # slot -> {"y0", "y"}
    st = {"cur": 0, "active": 0, "peak": 0, "t0": 0.0}

    def evaluate():
        dt = time.time() - st["t0"] if st["t0"] else 999.0
        oky = [s for s in strokes.values()
               if s["y0"] is not None and s["y"] is not None
               and s["y0"] > START_FRAC * ymax and (s["y0"] - s["y"]) > TRAVEL_FRAC * ymax]
        # EXACT finger count so counts stay distinct (a 3-finger swipe must NOT trigger a
        # 2-finger binding). peak == FINGERS + all of them did the bottom-up swipe.
        fired = st["peak"] == FINGERS and len(oky) >= FINGERS and dt < MAX_MS / 1000.0
        if dbg:
            try:
                with open("/tmp/handheld-kbd-gesture.log", "a") as f:
                    f.write(f"gesture peak={st['peak']} up_ok={len(oky)} need={FINGERS} "
                            f"dt={dt:.2f} fired={fired} ymax={ymax} "
                            f"strokes={[(s['y0'], s['y']) for s in strokes.values()]}\n")
            except Exception:
                pass
        if fired:
            show()

    def on_touch(fd, cond):
        try:
            for ev in dev.read():
                if ev.type != e.EV_ABS:
                    continue
                if ev.code == e.ABS_MT_SLOT:
                    st["cur"] = ev.value
                elif ev.code == e.ABS_MT_TRACKING_ID:
                    if ev.value >= 0:                  # a new contact begins
                        if st["active"] == 0:          # first finger → start a fresh gesture
                            strokes.clear(); st["peak"] = 0; st["t0"] = time.time()
                        st["active"] += 1
                        st["peak"] = max(st["peak"], st["active"])
                        strokes[st["cur"]] = {"y0": None, "y": None}
                    else:                              # a contact lifts
                        st["active"] = max(0, st["active"] - 1)
                        if st["active"] == 0:          # all fingers up → judge the gesture
                            evaluate()
                elif ev.code in (e.ABS_MT_POSITION_Y, e.ABS_Y):
                    s = strokes.get(st["cur"])
                    if s is None:                      # position before tracking_id (rare)
                        s = {"y0": None, "y": None}; strokes[st["cur"]] = s
                    if s["y0"] is None:
                        s["y0"] = ev.value
                    s["y"] = ev.value
        except OSError:
            return False                               # device gone → drop the watch
        return True
    GLib.io_add_watch(dev.fd, GLib.IO_IN, on_touch)
    print(f"handheld-kbd: gesture_summon listening on {dev.name}", file=sys.stderr)


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
            if dev.name == "handheld-kbd":        # skip our own injected-key device
                continue
            if codes <= set(dev.capabilities().get(e.EV_KEY, [])):
                GLib.io_add_watch(dev.fd, GLib.IO_IN, on_input, dev)
                opened += 1
        except Exception:
            pass
    if opened == 0:
        print("handheld-kbd: hotkey set but no readable input device "
              "(need 'input' group / udev rule)", file=sys.stderr)


_instance_lock = None


PROVEN = os.path.expanduser("~/.local/share/handheld-kbd/trigger-proven")


def _mark_proven():
    """Record that this keyboard really did come up on this machine.

    The swap daemon only makes Steam's on-screen keyboard transparent once this
    exists, so a trigger that never fires leaves the stock keyboard usable instead
    of leaving the user with no keyboard at all."""
    try:
        os.makedirs(os.path.dirname(PROVEN), exist_ok=True)
        open(PROVEN, "w").close()
    except Exception:
        pass


def _single_instance():
    """Ensure only ONE keyboard runs — duplicates leave a ghost window that still
    catches taps after the visible one hides. Exit silently if already running."""
    global _instance_lock
    import fcntl
    _instance_lock = open("/tmp/handheld-kbd.lock", "w")
    try:
        fcntl.flock(_instance_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        sys.exit(0)


def main():
    _single_instance()
    config = load_config()
    layout = load_layout(config.get("layout", "full"))
    rows, allkeys = resolve_rows(layout)
    if not allkeys:
        rows, allkeys = resolve_rows(DEFAULT_LAYOUT)
    # Prediction types whole words back out, so these must exist on the uinput device
    # even if the user's layout happens not to include them.
    allkeys = sorted(set(allkeys) | {e.KEY_BACKSPACE, e.KEY_SPACE, e.KEY_LEFTSHIFT})
    locale = resolve_locale(config)

    w = OSK(config, rows, allkeys, locale)

    def _flush_learned():
        """Persist the personal vocabulary now (normal saves are debounced)."""
        if getattr(w, "pred", None) is not None:
            w.pred.maybe_save(force=True)

    def _on_destroy(*_):
        _flush_learned()
        Gtk.main_quit()

    def _on_term(*_):
        _flush_learned()
        Gtk.main_quit()
        return False

    w.connect("destroy", _on_destroy)
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, _on_term, None)
    open("/tmp/handheld-kbd.pid", "w").write(str(os.getpid()))
    VIS = "/tmp/handheld-kbd.vis"

    state = {"shown": False}

    def _setvis(v):
        # The file is for the daemon's benefit; the in-memory flag is what we act on, so a
        # show/hide never waits on disk.
        state["shown"] = (v == "1")
        try: open(VIS, "w").write(v)
        except Exception: pass

    def _show(*_):
        if state["shown"]:
            return True                   # already up: nothing to do, no flicker
        # Placement is compositor work (rule writes, script reloads); doing it on every
        # show made summoning slow. Only redo it when something that affects it changed.
        w.ensure_placed()
        w.show_all()
        if GAMEMODE:                      # set overlay atoms once gamescope has mapped us
            GLib.timeout_add(250, w.gm_show)
        _mark_proven()
        _setvis("1"); return True

    def _hide(*_):
        if not state["shown"]:
            return True
        if GAMEMODE: w.gm_hide()
        w.hide(); _setvis("0"); return True
    w.hide_cb = _hide                 # the hide key routes through here, so state stays in sync
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGUSR1, _show, None)
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGUSR2, _hide, None)

    def _toggle():
        (_hide if state["shown"] else _show)()

    def _focus_show():
        if not state["shown"]:            # show-only, idempotent (no auto-hide)
            _show()

    # KWin talks to us here; FreeMove/Reset are the same actions as the ✥ and ⤓ keys, so
    # they can be scripted or bound to a shortcut.
    setup_service(_show, _hide, _toggle, w.set_reported_geometry,
                  lambda: w.on_move(None), lambda: w.on_reset(None))
    setup_dbus_trigger(config, _toggle)   # seamless hardware-button trigger (InputPlumber)
    setup_hotkey(config, _toggle)         # optional evdev hotkey (attached kbd / Steam Input chord)
    setup_focus_trigger(config, _focus_show)  # optional: auto-show when a text field is focused
    setup_gesture(config, _focus_show)        # optional: swipe up from bottom edge to summon

    # Do the placement work up front so even the FIRST summon is instant: it involves a
    # config write, a KWin reconfigure and a script reload, which is ~300ms the user should
    # never wait for.
    GLib.idle_add(lambda: (w.ensure_placed(), False)[1])
    _setvis("1" if os.environ.get("HANDHELD_KBD_SHOW") == "1" else "0")
    if os.environ.get("HANDHELD_KBD_SHOW") == "1":
        _show()
    Gtk.main()


if __name__ == "__main__":
    import faulthandler, traceback
    try:
        faulthandler.enable(open("/tmp/handheld-kbd-fault.log", "w"))
    except Exception:
        pass
    try:
        main()
    except SystemExit:
        raise                       # e.g. the single-instance lock bowing out; not a crash
    except BaseException:
        try:
            with open("/tmp/handheld-kbd-crash.log", "w") as _f:
                traceback.print_exc(file=_f)
        except Exception:
            pass
        raise
