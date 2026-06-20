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
- **Configurable hotkey** — toggle the keyboard with a key combo of your choice
  (default `Ctrl`+`Alt`+`K`). Works regardless of which window is focused.
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

After that, press your hotkey (**`Ctrl`+`Alt`+`K`** by default) to toggle it.

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
