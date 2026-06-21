# Better Handheld Keyboard

If you've tried to do anything *real* on a SteamOS handheld, you know the pain.

You open a terminal, or an app with a keyboard shortcut, and reach for the
on-screen keyboard — and it can't do the thing. No `Ctrl`. No `Tab` that works.
No `Esc`, no arrows you can trust, no `Ctrl+C`. It's opaque, it's slow to come
up, and it covers half the screen. It's a keyboard for typing your Wi-Fi password,
not for using your computer.

This is the keyboard that should have shipped. It types **real keystrokes** —
the same as a USB keyboard plugged in — so every modifier, every shortcut, and
every key works in every app, including games and the terminal. It's translucent
so you can see behind it, it comes up the instant you press your keyboard button,
and you can theme the whole thing in a JSON file.

## What you get

- **Real `Ctrl` / `Alt` / `Shift` / `Super`** — and `F1`–`F12`, `Tab`, `Esc`,
  arrows, the lot. `Ctrl+C` in a terminal just works.
- **Instant + on your existing button** — press the hardware keyboard button you
  already use; this comes up in place of the stock one. Press again to hide.
- **See-through** — adjustable transparency, so the keyboard doesn't blind you.
- **Themeable in JSON** — layout, colours, key sizes, opacity. No code.
- **US / UK switching** — a 🌐 key flips the layout so `£`, `@`, `#`, `"` land right.

## Install

Double-click **`Install Better Handheld Keyboard.desktop`**, enter your password
once (it needs access to `/dev/uinput` — that's how it types real keys), then
**log out and back in**.

Prefer the terminal? `./install.sh`, then log out and back in.

## How it works

```
  keyboard button ──remap──▶ InputPlumber ──DBus event──▶ handheld-kbd
                                                    tap a key │
                                                              ▼
                              focused app/game ◀── real keystroke ◀── /dev/uinput
```

Your keyboard button is remapped to fire a **DBus event** instead of a keystroke,
so nothing else reacts to it. Key taps are injected through **`/dev/uinput`** at
the kernel level — which is why they reach *every* app, games included.

## Configure

Everything lives in `~/.config/handheld-kbd/config.json` — `opacity`, `layout`,
`locale`, `theme`, key sizes, and an optional `hotkey`. Edits apply next time the
keyboard restarts. Layouts and locales are plain JSON files alongside it.

## Uninstall

`./uninstall.sh` (your config is left in place).

## Requirements

KDE Plasma 6 (Wayland) · `python3`, `python-gobject` (GTK 3), `python-evdev`.
The installer adds you to the `input` group.

## License

MIT — see [LICENSE](LICENSE). Nothing leaves your device.
