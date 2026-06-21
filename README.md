# Better Handheld Keyboard

A dark, translucent **on-screen keyboard** for SteamOS / KDE Plasma handhelds
(Steam Deck, Legion Go, ROG Ally) that injects **real hardware keystrokes** via
`/dev/uinput` — so every modifier, function key, and shortcut combo works in
every application, unlike the built-in keyboard which can only send a limited set.

It replaces the system's on-screen keyboard with something that actually has
Ctrl, Alt, Super, F1–F12, arrows, a full symbol set, and live US/UK switching.

## Features

- **Real keystrokes** — full `Ctrl` / `Alt` / `Shift` / `Super`, `F1`–`F12`,
  arrows, navigation cluster, and every symbol. Works everywhere, including games.
- **Uses your device's keyboard button** — press the hardware keyboard button
  you already use (the one that pops the built-in keyboard) and *this* one comes
  up instead. No setup, nothing to press on a keyboard you don't have.
- **Fully themeable via JSON** — the button layout, transparency, key sizes, and
  colours all live in plain config files. No code editing.
- **US / UK layout switching** — a 🌐 key flips the system layout and re-labels
  the keys to match (so `£`, `@`, `#`, `"` land where they should).
- **Sticky one-shot modifiers** with a clear "armed" highlight.

## How it works

```
  ┌──────────────┐  remap   ┌──────────────┐   DBus      ┌──────────────────┐
  │  keyboard    │ ───────▶ │ InputPlumber │ ──────────▶ │  handheld-kbd.py │
  │  button (HW) │          │              │  ui_select  │  (GTK keyboard)  │
  └──────────────┘          └──────────────┘             └────────┬─────────┘
                                                          tap key  │
                                                                   ▼
                                       /dev/uinput  ◀──  inject  ──┘
                                            │
                                            ▼  real hardware keystroke
                                     focused app / game
```

- The hardware button is remapped (via **InputPlumber**) to fire a **DBus event**,
  not a keystroke — so nothing else (Steam, KDE) reacts to it. No key collisions.
- Key taps are injected through **`/dev/uinput`** as real kernel-level key events,
  so they reach *any* app — including games and full-screen Wayland clients.
- A tiny daemon (`handheld-kbd-swap.sh`) applies the remap at login, restarts the
  keyboard if it dies (watchdog), and handles translucency + single-instance locking.

## Install

**Easy way:** double-click **`Install Better Handheld Keyboard.desktop`**. A terminal opens,
it copies everything into place, and asks for your password **once** (to grant
access to `/dev/uinput`, which is how it types). Then **log out and back in**.

**Terminal way:**
```sh
./install.sh
```
then log out and back in.

## How you bring it up

**Press your device's keyboard button** — the same hardware button you already use.
This keyboard appears in its place. Press again to hide. That's it.

The installer auto-picks the best method for your device:
- **Seamless** (Legion Go & other InputPlumber handhelds): the keyboard button is
  remapped to summon *this* keyboard directly — Steam's OSK is out of the loop, so
  show/hide is clean with no "ghost typing."
- **Mirror** (other KDE handhelds): when the system on-screen keyboard appears, this
  one takes its place on top.

To force one, set `"mirror"` in `config.json` (`false` = seamless, `true` = mirror).
The seamless trigger is the InputPlumber DBus event in `dbus_trigger` (default
`ui_select`) — change it if it ever collides on your hardware.

## Configure

Everything lives in `~/.config/handheld-kbd/`:

- **`config.json`**
  - `hotkey` — keys to toggle the keyboard, e.g. `["KEY_LEFTCTRL","KEY_LEFTALT","KEY_K"]` (use any [evdev key names](https://github.com/torvalds/linux/blob/master/include/uapi/linux/input-event-codes.h); `[]` disables)
  - `opacity` — `0.0`–`1.0` translucency
  - `layout` — which file in `layouts/` to use (`full`, `compact`, or your own)
  - `locale` — `auto`, `us`, or `gb`
  - `geometry`, `key_size`, `theme` colours
- **`layouts/<name>.json`** — the button grid. Each key:
  `{"label": "/", "key": "KEY_SLASH", "kind": "wide|space|mod|locale", "shifted": "?"}`
- **`locales/<code>.json`** — per-layout label overrides

Edits apply next time the keyboard (re)starts.

## Requirements

- KDE Plasma 6 (Wayland)
- `python3`, `python-gobject` (GTK 3), `python-evdev`
- Membership of the `input` group (the installer adds you)

## Uninstall

```sh
./uninstall.sh
```

## Notes

The keyboard reads input devices only to detect its activation hotkey — it
matches one specific combo and ignores everything else. It's all local; nothing
leaves your device.

## Troubleshooting

- Nothing happens on the keyboard button → make sure you **logged out and back in**
  after installing (autostart + the InputPlumber remap apply at login).
- Check the log: `cat /tmp/handheld-kbd-out.log` (should say `dbus trigger listening…`).
- Missing deps → install `python-gobject` (GTK 3) and `python-evdev`.

## License

MIT — see [LICENSE](LICENSE).

