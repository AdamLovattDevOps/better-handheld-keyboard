#!/usr/bin/env python3
"""Generate config/locales/*.json from xkeyboard-config.

This keyboard injects real keycodes, so what a key TYPES is decided entirely by the OS
XKB layout. A locale file therefore contains no behaviour at all — only the labels to
paint on the keys so that what you see matches what you get.

Typing those by hand for twenty layouts would be twenty chances to be subtly wrong, in
scripts most of us can't proofread. So they are generated from the same data the OS
itself uses: xkeyboard-config's symbol files for the key-to-keysym mapping, and
xorgproto's keysymdef.h for the keysym-to-character mapping.

    tools/build-locales.py --fetch          download the sources, then generate
    tools/build-locales.py --src DIR        generate from an existing checkout
                                            (or /usr/share/X11/xkb on a Linux box)

Output is committed to the repo: an install needs no network and no xkb parsing.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), "config", "locales")

XKB_BASE = ("https://gitlab.freedesktop.org/xkeyboard-config/xkeyboard-config"
            "/-/raw/master/symbols/")
KEYSYMDEF = ("https://gitlab.freedesktop.org/xorg/proto/xorgproto"
             "/-/raw/master/include/X11/keysymdef.h")

# The twenty layouts we ship labels for. Chosen for reach — the most widely spoken
# languages an XKB layout can actually serve — plus the two that were asked for.
#
# Deliberately absent: Chinese, Japanese and Korean. Those are not keyboard layouts but
# input methods; no mapping of keycodes to characters can produce them, and pretending
# otherwise with a labelled keyboard would be a lie about what pressing the key does.
LAYOUTS = [
    ("us",    "English (US)"),
    ("gb",    "English (UK)"),
    ("de",    "German"),
    ("fr",    "French"),
    ("es",    "Spanish"),
    ("latam", "Spanish (Latin America)"),
    ("it",    "Italian"),
    ("pt",    "Portuguese"),
    ("br",    "Portuguese (Brazil)"),
    ("nl",    "Dutch"),
    ("pl",    "Polish"),
    ("tr",    "Turkish"),
    ("ru",    "Russian"),
    ("ua",    "Ukrainian"),
    ("gr",    "Greek"),
    ("ara",   "Arabic"),
    ("il",    "Hebrew"),
    ("in",    "Hindi (Devanagari)"),
    ("th",    "Thai"),
    ("vn",    "Vietnamese"),
]

# XKB's key names for the keys this keyboard actually has. Anything else in a symbol
# file (keypad, the extra key on a 102-key board) has nowhere to go.
XKB_TO_EVDEV = {
    "TLDE": "KEY_GRAVE",
    **{f"AE{i:02d}": f"KEY_{d}" for i, d in enumerate("1234567890", start=1)},
    "AE11": "KEY_MINUS", "AE12": "KEY_EQUAL",
    **{f"AD{i:02d}": f"KEY_{c}" for i, c in enumerate("QWERTYUIOP", start=1)},
    "AD11": "KEY_LEFTBRACE", "AD12": "KEY_RIGHTBRACE",
    **{f"AC{i:02d}": f"KEY_{c}" for i, c in enumerate("ASDFGHJKL", start=1)},
    "AC10": "KEY_SEMICOLON", "AC11": "KEY_APOSTROPHE",
    "BKSL": "KEY_BACKSLASH",
    **{f"AB{i:02d}": f"KEY_{c}" for i, c in enumerate("ZXCVBNM", start=1)},
    "AB08": "KEY_COMMA", "AB09": "KEY_DOT", "AB10": "KEY_SLASH",
}

# Dead keys produce nothing on their own, so keysymdef has no character for them. Show
# the spacing form of the accent they will add — that is what the key means to a user.
DEAD_KEYS = {
    "dead_grave": "`", "dead_acute": "´", "dead_circumflex": "ˆ", "dead_tilde": "˜",
    "dead_macron": "¯", "dead_breve": "˘", "dead_abovedot": "˙", "dead_diaeresis": "¨",
    "dead_abovering": "˚", "dead_doubleacute": "˝", "dead_caron": "ˇ",
    "dead_cedilla": "¸", "dead_ogonek": "˛", "dead_iota": "ͺ", "dead_belowdot": "◌̣",
    "dead_hook": "◌̉", "dead_horn": "◌̛", "dead_stroke": "◌̸", "dead_belowcomma": "◌̦",
    "dead_greek": "μ", "dead_currency": "¤",
}

SKIP = {"NoSymbol", "VoidSymbol", "any"}

_KEY_RE = re.compile(r"""^\s*key\s*<(\w+)>\s*\{(.*?)\}\s*;""", re.M | re.S)
_GROUP_RE = re.compile(r"\[([^\]]*)\]")
_TYPE_RE = re.compile(r'\b(?:type|symbols|actions|virtualMods)\s*(?:\[[^\]]*\])?\s*=\s*(?:"[^"]*"|\w+)')
_INCLUDE_RE = re.compile(r'^\s*include\s+"([^"]+)"', re.M)
_BLOCK_RE = re.compile(r'(default\s+)?[\w\s]*xkb_symbols\s+"([^"]+)"\s*\{')


def fetch(url, path):
    if os.path.exists(path):
        return path
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        with urllib.request.urlopen(url, timeout=30) as r, open(path, "wb") as f:
            f.write(r.read())
        return path
    except Exception as ex:
        # A Python without a usable CA bundle is common enough (macOS system python,
        # among others) that failing here would just be annoying. curl has its own.
        if subprocess.run(["curl", "-sSfL", "-o", path, url]).returncode == 0:
            return path
        if os.path.exists(path):
            os.remove(path)
        raise ex


def load_keysyms(path):
    """keysym name -> character, from keysymdef.h's U+XXXX comments."""
    table = {}
    pat = re.compile(r"^#define\s+XK_(\w+)\s+0x[0-9a-fA-F]+\s*/\*[<\s]*U\+([0-9A-Fa-f]{4,6})")
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            m = pat.match(line)
            if m:
                table[m.group(1)] = chr(int(m.group(2), 16))
    table.update(DEAD_KEYS)
    return table


def keysym_char(sym, table):
    """One keysym as the character it produces, or None if it isn't printable."""
    sym = sym.strip()
    if not sym or sym in SKIP:
        return None
    if sym in table:
        return table[sym]
    # Direct Unicode forms used throughout the symbol files.
    m = re.fullmatch(r"0x100([0-9a-fA-F]{4})", sym)
    if not m:
        m = re.fullmatch(r"U([0-9a-fA-F]{4,6})", sym)
    if m:
        ch = chr(int(m.group(1), 16))
        # A combining mark needs something to combine with, or it lands on the key label
        # before it and looks like a rendering bug.
        return ("◌" + ch) if 0x0300 <= ord(ch) <= 0x036F else ch
    if len(sym) == 1:
        return sym
    return None


class Symbols:
    """Reads a symbol file and resolves its include chain the way xkbcomp would."""

    def __init__(self, src, fetch_missing):
        self.src = src
        self.fetch_missing = fetch_missing
        self.cache = {}

    def _text(self, name):
        if name in self.cache:
            return self.cache[name]
        path = os.path.join(self.src, name)
        if not os.path.exists(path) and self.fetch_missing:
            try:
                fetch(XKB_BASE + name, path)
            except Exception as ex:
                print(f"  ! cannot fetch symbols/{name}: {ex}", file=sys.stderr)
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                text = f.read()
        except Exception:
            text = ""
        self.cache[name] = text
        return text

    def block(self, name, variant=None):
        """The body of one xkb_symbols block — the named variant, else the default."""
        text = self._text(name)
        if not text:
            return ""
        best = None
        for m in _BLOCK_RE.finditer(text):
            is_default, vname = m.group(1), m.group(2)
            if variant is not None and vname != variant:
                continue
            if variant is None and not is_default and best is not None:
                continue
            start = m.end()
            depth, i = 1, start
            while i < len(text) and depth:
                if text[i] == "{":
                    depth += 1
                elif text[i] == "}":
                    depth -= 1
                i += 1
            body = text[start:i - 1]
            if variant is not None or is_default:
                return body
            if best is None:
                best = body
        return best or ""

    def levels(self, name, variant=None, seen=None):
        """{xkb key name: [level1, level2, level3, ...]} with includes merged in first."""
        seen = seen if seen is not None else set()
        key = (name, variant)
        if key in seen:
            return {}
        seen.add(key)
        body = self.block(name, variant)
        out = {}
        for inc in _INCLUDE_RE.findall(body):
            m = re.fullmatch(r"([\w+/-]+)(?:\(([\w-]+)\))?", inc.strip())
            if not m:
                continue
            out.update(self.levels(m.group(1), m.group(2), seen))
        for kname, spec in _KEY_RE.findall(body):
            # A key may declare its type before its symbols:
            #   key <AD08> { type[group1] = "FOUR_LEVEL_ALPHABETIC", [ i, I, ... ] };
            # and that bracket is not a symbol list. Turkish writes its dotted/dotless i
            # exactly this way, which is a good reminder to strip these first.
            spec = _TYPE_RE.sub("", spec)
            groups = _GROUP_RE.findall(spec)
            if not groups:
                continue
            syms = [s.strip() for s in groups[0].split(",")]
            # A redefinition overrides the included one level by level, and `any` at a
            # level means "leave that one alone". Greek is written this way: it includes
            # gr(simple) for the letters and then redefines only levels 3 and 4, so
            # replacing the whole entry would throw the alphabet away.
            old = out.get(kname, [])
            merged = list(syms)
            for i, s in enumerate(merged):
                if s in ("any", "NoSymbol", "") and i < len(old):
                    merged[i] = old[i]
            if len(old) > len(merged):
                merged += old[len(merged):]
            out[kname] = merged
        return out


def build(code, syms, table):
    levels = syms.levels(code)
    out = {}
    for xkbname, entry in levels.items():
        evdev = XKB_TO_EVDEV.get(xkbname)
        if not evdev:
            continue
        chars = [keysym_char(s, table) for s in entry[:4]]
        label = chars[0] if len(chars) > 0 else None
        shifted = chars[1] if len(chars) > 1 else None
        alt = chars[2] if len(chars) > 2 else None
        if label is None:
            continue
        rec = {"label": label}
        # A shift level that just upper-cases the letter is what every keyboard does;
        # printing it in the corner of the key is noise.
        if shifted and shifted != label and shifted != label.upper():
            rec["shifted"] = shifted
        if alt and alt not in (label, shifted):
            rec["alt"] = alt
        out[evdev] = rec
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=os.path.join(HERE, ".xkb"),
                    help="xkb data dir (a checkout, or /usr/share/X11/xkb)")
    ap.add_argument("--fetch", action="store_true",
                    help="download missing symbol files from xkeyboard-config")
    args = ap.parse_args()

    symdir = args.src
    if os.path.isdir(os.path.join(symdir, "symbols")):
        symdir = os.path.join(symdir, "symbols")
    os.makedirs(symdir, exist_ok=True)

    keysymdef = os.path.join(args.src, "keysymdef.h")
    if not os.path.exists(keysymdef):
        for candidate in ("/usr/include/X11/keysymdef.h",):
            if os.path.exists(candidate):
                keysymdef = candidate
                break
        else:
            if not args.fetch:
                sys.exit("no keysymdef.h — pass --fetch, or --src a tree containing it")
            fetch(KEYSYMDEF, keysymdef)
    table = load_keysyms(keysymdef)
    print(f"keysyms: {len(table)}")

    syms = Symbols(symdir, args.fetch)
    os.makedirs(OUT, exist_ok=True)
    index = {}
    for code, name in LAYOUTS:
        data = build(code, syms, table)
        if len(data) < 20:
            print(f"  ! {code}: only {len(data)} keys resolved — not written",
                  file=sys.stderr)
            continue
        with open(os.path.join(OUT, f"{code}.json"), "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False, sort_keys=True)
            f.write("\n")
        index[code] = name
        alt = sum(1 for v in data.values() if "alt" in v)
        print(f"  {code:6s} {len(data):3d} keys, {alt:3d} with AltGr  — {name}")

    with open(os.path.join(OUT, "index.json"), "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2, ensure_ascii=False, sort_keys=True)
        f.write("\n")
    print(f"wrote {len(index)} locales to {OUT}")


if __name__ == "__main__":
    main()
