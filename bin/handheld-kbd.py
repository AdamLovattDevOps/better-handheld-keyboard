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
import gi, sys, time, os, signal, json, subprocess, math
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk, GLib
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
            if kind in ("locale", "hide", "size", "opacity"):    # action keys: no keycode
                dflt = {"locale": "🌐", "hide": "⌵", "size": "⤢", "opacity": "◐"}.get(kind, "")
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
        self.big = bool(config.get("start_big", False))
        self.norm_kh = config["key_size"][1]
        self.nrows = max(1, len(rows))
        prov = Gtk.CssProvider(); prov.load_from_data(build_css(config["theme"]))
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), prov,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        # Uniform aligned grid: every key snaps to a column grid (column_homogeneous),
        # widths come from per-kind unit spans, rows centred → tidy, even alignment.
        kh = config["key_size"][1]
        SPAN = {'': 2, 'wide': 3, 'mod': 3, 'space': 8, 'locale': 2, 'hide': 2, 'size': 2, 'opacity': 2}
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
        elif self.sugbar is not None:
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
            box.pack_start(self.sugbar, False, False, 0)
            box.pack_start(grid, True, True, 0)
            self.add(box)
        else:
            self.add(grid)
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
                print("handheld-kbd: no prediction data — run handheld-kbd-build-dict",
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
        lmap = load_locale_map(code)
        for (b, name, base_label, base_shifted) in self.keybtns:
            ov = lmap.get(name, {})
            self._set_label(b, ov.get("label", base_label), ov.get("shifted", base_shifted))
        if self.locale_btn:
            self._set_label(self.locale_btn, "🌐" + code.upper(), "")

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
        self.apply_size()
        self._persist_big()

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
        try:
            with open(opscript) as f:
                lines = f.read().splitlines()
            for i, l in enumerate(lines):
                if l.strip().startswith("var OP ="):
                    lines[i] = f"var OP = {val};"
                    break
            with open(opscript, "w") as f:
                f.write("\n".join(lines) + "\n")
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
             if big else self.cfg["geometry"])
        if not GAMEMODE:
            # The suggestion row eats into a window whose size is FORCED by the KWin
            # rule. Left alone, full-height keys push the window's minimum past that
            # forced height, and an over-constrained Wayland window keeps its input
            # region but stops painting — it takes taps while being invisible. So the
            # keys shrink to fit whatever the suggestion row leaves behind.
            # apply_size() runs before the window is realised, where the row still
            # measures as ~0 — so trust the configured height (plus its margins) and
            # only prefer the measured value once it is real and larger.
            bar = 0
            if self.sugbar is not None:
                bar = max(int(self.cfg.get("suggest_height", 44)) + 8,
                          self.sugbar.get_preferred_height()[0])
            fit = (g["h"] - bar - 8) // self.nrows        # 8 = grid top+bottom margins
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
        ox, oy = self._panel_origin()        # anchor to the internal touchscreen, not an external
        rect = {"x": g["x"] + ox, "y": g["y"] + oy, "w": g["w"], "h": g["h"]}
        self.resize(rect["w"], rect["h"])
        self.move(rect["x"], rect["y"])
        self._apply_kwin_geometry(rect)

    def _panel_origin(self):
        """Logical origin (x,y) of the INTERNAL panel (eDP*), so we dock on the built-in
        touchscreen even when an external display shifts the coordinate space (an external
        at 0,0 would otherwise steal position 0,378). Returns (0,0) on a single display or
        any failure — i.e. the original behaviour."""
        want = (self.cfg.get("internal_output", "") or "").lower()
        try:
            data = json.loads(subprocess.check_output(
                ["kscreen-doctor", "-j"], text=True, timeout=3))
            outs = [o for o in data.get("outputs", []) if o.get("enabled")]
            if len(outs) < 2:
                return (0, 0)                # single display → no offset needed
            def internal(o):
                n = (o.get("name") or "").lower()
                return n == want if want else n.startswith("edp")
            m = next((o for o in outs if internal(o)), None)
            if m is None:
                return (0, 0)
            pos = m.get("pos") or {}
            return (int(pos.get("x", 0)), int(pos.get("y", 0)))
        except Exception:
            return (0, 0)

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
        self.mods.clear(); self._refresh_mods()
        self._track(kc, mods)

    def dismiss(self):
        """Hide button: hide now and tell the mirror daemon to stay hidden until the
        next time the device's keyboard button is pressed (so it doesn't pop right back)."""
        if self._stray_tap():
            return
        try: open("/tmp/handheld-kbd.suppress", "w").write("1")
        except Exception: pass
        try: open("/tmp/handheld-kbd.vis", "w").write("0")
        except Exception: pass
        if GAMEMODE:
            self.gm_hide()
        self.hide()

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

    def _setvis(v):
        try: open(VIS, "w").write(v)
        except Exception: pass

    def _show(*_):
        w.apply_size()                    # re-anchor to the internal panel (handles display hotplug)
        w.show_all()
        if GAMEMODE:                      # set overlay atoms once gamescope has mapped us
            GLib.timeout_add(250, w.gm_show)
        _mark_proven()
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

    def _focus_show():
        cur = "0"
        try: cur = open(VIS).read().strip()
        except Exception: pass
        if cur != "1":                    # show-only, idempotent (no auto-hide)
            _show()

    setup_dbus_trigger(config, _toggle)   # seamless hardware-button trigger (InputPlumber)
    setup_hotkey(config, _toggle)         # optional evdev hotkey (attached kbd / Steam Input chord)
    setup_focus_trigger(config, _focus_show)  # optional: auto-show when a text field is focused
    setup_gesture(config, _focus_show)        # optional: swipe up from bottom edge to summon

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
    except BaseException:
        try:
            with open("/tmp/handheld-kbd-crash.log", "w") as _f:
                traceback.print_exc(file=_f)
        except Exception:
            pass
        raise
