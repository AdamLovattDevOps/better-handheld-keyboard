#!/usr/bin/env python3
"""Type a pangram in each language and check what actually arrives.

`verify-locales.py` proves the labels agree with the keymap. It says nothing about the
chain that carries a keypress: /dev/uinput → kernel → compositor → XKB → application.
This tests that end to end, on real hardware, because there is nowhere else to test it.

It does not use a hand-written key sequence, which would only test my assumptions. For
each character of the sentence it looks up the key and level *from the locale file this
keyboard ships* — the same data the keyboard draws with — presses that, and compares what
landed. So a label on the wrong key fails here too, and it fails in a script no one
involved has to be able to read.

    tools/typing-test.py                 every language with a sentence
    tools/typing-test.py it ru ara       just these

Run it in the graphical session, on a machine where the layouts are configured (see
`handheld-kbd-locales`) and you are in the `input` group.
"""
import json
import os
import subprocess
import sys
import time

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib      # noqa: E402
from evdev import UInput, ecodes as e    # noqa: E402

LOCALES = os.path.expanduser("~/.config/handheld-kbd/locales")

# Real pangrams where the language has one — they exist precisely to exercise the
# awkward characters, which is what we want to put through the keymap. Where a language
# has no traditional pangram, a sentence that uses its distinctive letters.
SENTENCES = {
    "us":    "The quick brown fox jumps over the lazy dog",
    "gb":    "The quick brown fox jumps over the lazy dog",
    "de":    "Victor jagt zwölf Boxkämpfer quer über den großen Sylter Deich",
    "fr":    "Portez ce vieux whisky au juge blond qui fume",
    "es":    "El veloz murciélago hindú comía feliz cardillo y kiwi",
    "latam": "El veloz murciélago hindú comía feliz cardillo y kiwi",
    "it":    "Ma la volpe col suo balzo ha raggiunto il quieto Fido",
    "pt":    "Um pequeno jabuti xereta viu dez cegonhas felizes",
    "br":    "Um pequeno jabuti xereta viu dez cegonhas felizes",
    "nl":    "Pa's wijze lynx bezag vroom het fikse aquaduct",
    "pl":    "Pchnąć w tę łódź jeża lub ośm skrzyń fig",
    "tr":    "Pijamalı hasta yağız şoföre çabucak güvendi",
    "ru":    "Съешь же ещё этих мягких французских булок да выпей чаю",
    "ua":    "Чуєш їх доцю га кумедна ж ти",
    "gr":    "Ξεσκεπάζω την ψυχοφθόρα βδελυγμία",
    "ara":   "نص حكيم له سر قاطع وذو شأن عظيم",
    "il":    "דג סקרן שט בים מאוכזב ולפתע מצא חברה",
    "in":    "ऋषि को क्षमा चाहिए",
    "th":    "เป็นมนุษย์สุดประเสริฐเลิศคุณค่า",
    "vn":    "Do bạch kim rất quý nên sẽ dùng để lắp vô xe",
}

LEVELS = (("label", []), ("shifted", [e.KEY_LEFTSHIFT]), ("alt", [e.KEY_RIGHTALT]))


def char_map(code):
    """character -> (keycode, [modifiers]) from the locale file we ship."""
    try:
        with open(os.path.join(LOCALES, f"{code}.json")) as f:
            data = json.load(f)
    except Exception as ex:
        return None, f"no locale file ({ex})"
    out = {}
    for key_name, entry in data.items():
        kc = getattr(e, key_name, None)
        if not isinstance(kc, int):
            continue
        for field, mods in LEVELS:
            ch = entry.get(field)
            if not ch or len(ch) != 1:
                continue          # dotted-circle combining marks are not typeable alone
            out.setdefault(ch, (kc, mods))
        # A locale file records `shifted` only when it is something other than the
        # upper-case of the label — printing "Q" in the corner of the Q key is noise.
        # Shift still produces it, so the map has to know that or every capital in
        # every sentence looks untypeable.
        label = entry.get("label")
        if label and len(label) == 1 and "shifted" not in entry:
            upper = label.upper()
            if len(upper) == 1 and upper != label:
                out.setdefault(upper, (kc, [e.KEY_LEFTSHIFT]))
    # Space is on no locale file, being the same everywhere.
    out.setdefault(" ", (e.KEY_SPACE, []))
    return out, None


def switch_to(code):
    """Ask KDE for this layout. Returns the code actually active."""
    def current():
        try:
            ll = subprocess.check_output(
                ["kreadconfig6", "--file", "kxkbrc", "--group", "Layout", "--key",
                 "LayoutList"], text=True, timeout=5).strip().split(",")
            idx = int(subprocess.check_output(
                ["qdbus6", "org.kde.keyboard", "/Layouts",
                 "org.kde.KeyboardLayouts.getLayout"], text=True, timeout=5).strip())
            return ll[idx] if 0 <= idx < len(ll) else None
        except Exception:
            return None

    for _ in range(30):
        if current() == code:
            return code
        subprocess.run(["qdbus6", "org.kde.keyboard", "/Layouts",
                        "org.kde.KeyboardLayouts.switchToNextLayout"],
                       stdout=subprocess.DEVNULL, timeout=5)
        time.sleep(0.25)
    return current()


class Sink(Gtk.Window):
    """A focused text entry, which is the only honest way to ask what arrived."""

    def __init__(self):
        super().__init__(title="handheld-kbd typing test")
        self.entry = Gtk.Entry()
        self.entry.set_width_chars(80)
        self.add(self.entry)
        self.set_keep_above(True)
        self.show_all()
        self.entry.grab_focus()

    def typed(self):
        return self.entry.get_text()

    def clear(self):
        self.entry.set_text("")


def pump(seconds):
    end = time.time() + seconds
    while time.time() < end:
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)
        time.sleep(0.01)


def run_one(code, ui, sink, settle):
    sentence = SENTENCES[code]
    cmap, err = char_map(code)
    if err:
        return code, None, err, []

    active = switch_to(code)
    if active != code:
        return code, None, f"KDE would not switch to it (stuck on {active})", []

    unmapped = sorted({c for c in sentence if c not in cmap})
    typeable = "".join(c for c in sentence if c in cmap)

    sink.clear()
    pump(0.4)
    for ch in typeable:
        kc, mods = cmap[ch]
        for m in mods:
            ui.write(e.EV_KEY, m, 1)
        ui.syn()
        ui.write(e.EV_KEY, kc, 1); ui.syn()
        ui.write(e.EV_KEY, kc, 0); ui.syn()
        for m in reversed(mods):
            ui.write(e.EV_KEY, m, 0)
        ui.syn()
        pump(settle)
    pump(0.6)
    return code, typeable, None, [sink.typed(), unmapped]


def main():
    wanted = [c for c in sys.argv[1:] if c in SENTENCES] or list(SENTENCES)
    ui = UInput({e.EV_KEY: sorted({getattr(e, n) for n in dir(e)
                                   if n.startswith("KEY_")
                                   and isinstance(getattr(e, n), int)})},
                name="handheld-kbd-typing-test")
    sink = Sink()
    pump(1.0)

    failures = 0
    for code in wanted:
        code, expected, err, rest = run_one(code, ui, sink, 0.012)
        if err:
            print(f"  {code:6s} SKIP  {err}")
            continue
        got, unmapped = rest
        ok = got == expected
        failures += 0 if ok else 1
        note = ""
        if unmapped:
            # Not a failure: dead-key sequences and combining marks need composing, which
            # is a different feature from "the key types what it says".
            note = f"   [{len(unmapped)} char(s) need composing: {''.join(unmapped)}]"
        print(f"  {code:6s} {'ok  ' if ok else 'FAIL'}  {len(expected)} chars{note}")
        if not ok:
            print(f"           expected {expected!r}")
            print(f"           got      {got!r}")
            for i, (a, b) in enumerate(zip(expected, got)):
                if a != b:
                    print(f"           first difference at {i}: wanted {a!r}, got {b!r}")
                    break
    ui.close()
    print(f"\n{len(wanted)} languages, {failures} failed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
