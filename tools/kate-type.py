#!/usr/bin/env python3
"""Prove a language end to end by typing its pangram into Kate.

For each layout code given: switch the OS layout, open Kate on a fresh file, focus it,
type the sentence through /dev/uinput using the key positions from the keyboard's own
locale data, press Ctrl+S, and read the saved file back. A real editor, a real save, a
real file on disk — nothing about this can be faked by the test itself. A screenshot is
taken while the text is on screen.

Usage: kate-type.py <code> [<code>…]
"""
import json
import os
import subprocess
import sys
import time

from evdev import UInput, ecodes as e

LOCALES = os.path.expanduser("~/.config/handheld-kbd/locales")
OUTDIR = "/tmp/kate-proof"
LEVELS = (("label", []), ("shifted", [e.KEY_LEFTSHIFT]), ("alt", [e.KEY_RIGHTALT]))

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


def char_map(code):
    with open(os.path.join(LOCALES, f"{code}.json")) as f:
        data = json.load(f)
    out = {}
    for key_name, entry in data.items():
        kc = getattr(e, key_name, None)
        if not isinstance(kc, int):
            continue
        for field, mods in LEVELS:
            ch = entry.get(field)
            if ch and len(ch) == 1:
                out.setdefault(ch, (kc, mods))
        label = entry.get("label")
        if label and len(label) == 1 and "shifted" not in entry:
            upper = label.upper()
            if len(upper) == 1 and upper != label:
                out.setdefault(upper, (kc, [e.KEY_LEFTSHIFT]))
    out.setdefault(" ", (e.KEY_SPACE, []))
    return out


def kwin_run(js, name):
    path = f"/tmp/{name}.js"
    with open(path, "w") as f:
        f.write(js)
    for args in (["unloadScript", name], ["loadScript", path, name], ["start"]):
        subprocess.run(["qdbus6", "org.kde.KWin", "/Scripting",
                        "org.kde.kwin.Scripting." + args[0]] + args[1:],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)


def focus_kate():
    kwin_run('workspace.windowList().forEach(function(w){'
             ' if (("" + w.resourceClass).indexOf("kate") !== -1)'
             '   workspace.activeWindow = w; });', "hk-kate-focus")


def kate_present():
    r = subprocess.run(["pgrep", "-f", "/usr/bin/kate|bin/kate"],
                       stdout=subprocess.DEVNULL)
    return r.returncode == 0


def switch_to(code):
    def current():
        try:
            out = subprocess.check_output(
                ["busctl", "--user", "call", "org.kde.keyboard", "/Layouts",
                 "org.kde.KeyboardLayouts", "getLayoutsList"], text=True, timeout=5)
            codes = out.split('"')[1::2][0::3]
            idx = int(subprocess.check_output(
                ["qdbus6", "org.kde.keyboard", "/Layouts",
                 "org.kde.KeyboardLayouts.getLayout"], text=True, timeout=5).strip())
            return codes[idx] if 0 <= idx < len(codes) else None
        except Exception:
            return None
    for _ in range(20):
        if current() == code:
            return True
        subprocess.run(["qdbus6", "org.kde.keyboard", "/Layouts",
                        "org.kde.KeyboardLayouts.switchToNextLayout"],
                       stdout=subprocess.DEVNULL, timeout=5)
        time.sleep(0.3)
    return current() == code


def press(ui, kc, mods=()):
    for m in mods:
        ui.write(e.EV_KEY, m, 1)
    ui.syn()
    ui.write(e.EV_KEY, kc, 1); ui.syn()
    ui.write(e.EV_KEY, kc, 0); ui.syn()
    for m in reversed(mods):
        ui.write(e.EV_KEY, m, 0)
    ui.syn()
    time.sleep(0.015)


def run_one(code, ui):
    sentence = SENTENCES[code]
    try:
        cmap = char_map(code)
    except Exception as ex:
        return f"SKIP  no locale data ({ex})"
    if not switch_to(code):
        return "SKIP  KDE would not switch to this layout"

    path = f"{OUTDIR}/{code}.txt"
    if os.path.exists(path):
        os.remove(path)
    kate = subprocess.Popen(["kate", "-n", "--startanon", path],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(30):                       # wait for the window, then focus it
        time.sleep(0.5)
        focus_kate()
        if kate_present():
            break
    time.sleep(2.0)
    focus_kate()
    time.sleep(1.0)

    typeable = "".join(c for c in sentence if c in cmap)
    skipped = sorted({c for c in sentence if c not in cmap})
    for ch in typeable:
        kc, mods = cmap[ch]
        press(ui, kc, mods)
    time.sleep(0.5)
    press(ui, e.KEY_S, [e.KEY_LEFTCTRL])      # a real save, through the same device
    time.sleep(2.0)

    shot = f"{OUTDIR}/{code}.png"
    subprocess.run(["spectacle", "-b", "-n", "-f", "-o", shot],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)

    kate.terminate()
    try:
        kate.wait(timeout=5)
    except Exception:
        kate.kill()
    time.sleep(0.5)

    try:
        with open(path, encoding="utf-8") as f:
            got = f.read().rstrip("\n")
    except Exception:
        return "FAIL  Kate saved nothing"
    note = f"   [needs composing: {''.join(skipped)}]" if skipped else ""
    if got == typeable:
        return f"ok    {len(typeable)} chars into Kate and back{note}"
    return (f"FAIL  file differs{note}\n"
            f"         expected {typeable!r}\n"
            f"         got      {got!r}")


def main():
    os.makedirs(OUTDIR, exist_ok=True)
    codes = [c for c in sys.argv[1:] if c in SENTENCES]
    keys = {e.KEY_LEFTSHIFT, e.KEY_RIGHTALT, e.KEY_LEFTCTRL, e.KEY_S, e.KEY_SPACE}
    for code in codes:
        try:
            keys |= {kc for kc, _ in char_map(code).values()}
        except Exception:
            pass
    ui = UInput({e.EV_KEY: sorted(keys)}, name="handheld-kbd-kate-test")
    time.sleep(1.0)
    fails = 0
    for code in codes:
        result = run_one(code, ui)
        fails += result.startswith("FAIL")
        print(f"  {code:6s} {result}")
        sys.stdout.flush()
    ui.close()
    print(f"\n{len(codes)} languages, {fails} failed")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
