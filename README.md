# Claude OSK

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

## Install

**Easy way:** double-click **`Install Claude OSK.desktop`**. A terminal opens,
it copies everything into place, and asks for your password **once** (to grant
access to `/dev/uinput`, which is how it types). Then **log out and back in**.

**Terminal way:**
```sh
./install.sh
```
then log out and back in.

## How you bring it up

**Just press your device's keyboard button** — the same hardware button that used
to summon the built-in keyboard. This one takes its place automatically. No
keyboard chord required (you don't have a keyboard — that's the whole point).

**Seamless mode (Legion Go & other InputPlumber handhelds) — recommended.** Set
`"mirror": false` in `config.json`. The daemon then remaps your **hardware keyboard
button** (via InputPlumber) to drive *this* keyboard directly — Steam's OSK is taken
out of the loop entirely. Same button you already press, but now: clean show/hide
toggle, the on-screen hide button works, no "ghost typing." Nothing to configure in
Steam Input. (Internally it remaps the button to F13 and the keyboard listens for it;
change `hotkey` if you want a different key. Falls back gracefully on devices whose
button InputPlumber doesn't expose.)

## Configure

Everything lives in `~/.config/claude-osk/`:

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

## License

MIT
