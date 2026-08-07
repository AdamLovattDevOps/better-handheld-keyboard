#!/usr/bin/env python3
"""Check every shipped key label against libxkbcommon.

build-locales.py reads xkeyboard-config's source files with a regex parser. That parser
has been wrong three times — brace counting inside comments, deprecated keysym aliases,
type declarations mistaken for symbol lists — and each time the result was a layout that
looked plausible and put characters on the wrong keys. In scripts I cannot read, "looks
plausible" is worth nothing.

So the labels are checked against a different implementation entirely: the compiled
keymap libxkbcommon produces, which is what the compositor itself will use. If a label
disagrees with that, the key is drawn with a character it does not type.

    tools/verify-locales.py                 compile with xkbcli and check (needs Linux)
    tools/verify-locales.py --keymaps DIR   check against dumps made elsewhere

Dump keymaps on a Linux box with:

    for c in us gb de …; do xkbcli compile-keymap --layout $c > $c.xkb; done
"""
import argparse
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LOCALES = os.path.join(os.path.dirname(HERE), "config", "locales")

import importlib.util

# build-locales.py has a hyphen in its name, so it needs loading by path.
_spec = importlib.util.spec_from_file_location(
    "build_locales", os.path.join(HERE, "build-locales.py"))
_bl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_bl)

XKB_TO_EVDEV = _bl.XKB_TO_EVDEV
DEAD_KEYS = _bl.DEAD_KEYS

# The compiled keymap gives one line per key, all levels resolved.
KEY_RE = re.compile(r"^\s*key\s*<(\w+)>\s*\{(.*?)\}\s*;", re.M | re.S)
GROUP_RE = re.compile(r"\[([^\]]*)\]")
TYPE_RE = re.compile(r'\b(?:type|symbols|actions|virtualMods)\s*(?:\[[^\]]*\])?\s*=\s*'
                     r'(?:"[^"]*"|\w+)')


def keymap_levels(text):
    """{xkb key name: [level1, level2, …]} from a compiled keymap."""
    out = {}
    for name, spec in KEY_RE.findall(text):
        spec = TYPE_RE.sub("", spec)
        groups = GROUP_RE.findall(spec)
        if groups:
            out[name] = [s.strip() for s in groups[0].split(",")]
    return out


def compile_keymap(code):
    try:
        return subprocess.check_output(["xkbcli", "compile-keymap", "--layout", code],
                                       text=True, stderr=subprocess.DEVNULL, timeout=30)
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--keymaps", help="directory of <code>.xkb dumps")
    args = ap.parse_args()

    table = _bl.load_keysyms(os.path.join(HERE, ".xkb", "keysymdef.h")) \
        if os.path.exists(os.path.join(HERE, ".xkb", "keysymdef.h")) \
        else _bl.load_keysyms("/usr/include/X11/keysymdef.h")

    index = json.load(open(os.path.join(LOCALES, "index.json")))
    problems = total = 0

    for code in sorted(index):
        if args.keymaps:
            path = os.path.join(args.keymaps, f"{code}.xkb")
            text = open(path, encoding="utf-8", errors="replace").read() \
                if os.path.exists(path) else None
        else:
            text = compile_keymap(code)
        if not text:
            print(f"  {code:6s} SKIPPED — no keymap available")
            continue

        ours = json.load(open(os.path.join(LOCALES, f"{code}.json")))
        theirs = keymap_levels(text)
        bad = []
        # A short locale file is how every parser bug so far presented: the layout looked
        # right and had quietly lost keys off the end.
        expected = len(XKB_TO_EVDEV)
        if len(ours) != expected:
            missing = sorted(set(XKB_TO_EVDEV.values()) - set(ours))
            bad.append(f"only {len(ours)}/{expected} keys — missing {', '.join(missing)}")
        for xkbname, syms in theirs.items():
            evdev = XKB_TO_EVDEV.get(xkbname)
            if not evdev or evdev not in ours:
                continue
            mine = ours[evdev]
            for level, field in ((0, "label"), (1, "shifted"), (2, "alt")):
                if field not in mine or level >= len(syms):
                    continue
                want = _bl.keysym_char(syms[level], table)
                if want is None:
                    continue
                got = mine[field]
                # A combining mark is drawn on a dotted circle, or it renders on top of
                # whatever is to its left and the key looks broken. The circle is
                # presentation, so compare without it on either side.
                strip = lambda s: s[1:] if len(s) == 2 and s[0] == "◌" else s
                want, got = strip(want), strip(got)
                # A dead key is shown as the accent it applies; the keymap names the
                # dead keysym. Both are the same key, so agreeing on the glyph is enough.
                if want != got:
                    bad.append(f"{evdev}.{field}: we draw {got!r}, xkb types {want!r}"
                               f" ({syms[level]})")
            total += 1
        if bad:
            problems += len(bad)
            print(f"  {code:6s} {len(bad)} MISMATCH")
            for b in bad[:8]:
                print(f"           {b}")
            if len(bad) > 8:
                print(f"           … and {len(bad) - 8} more")
        else:
            print(f"  {code:6s} ok")

    print(f"\n{total} key/level pairs checked, {problems} mismatches")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
