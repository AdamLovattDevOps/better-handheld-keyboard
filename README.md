# Claude OSK

A dark, transparent on-screen keyboard for **KDE Plasma Wayland handhelds** (Steam Deck,
Legion Go, ROG Ally on a KDE desktop) that injects **real hardware keystrokes** via
`/dev/uinput` — so every modifier, F-key, and combo works in every app, unlike the
text-input-protocol OSKs (maliit) that can only send named key sequences.

It replaces both maliit and Steam's desktop on-screen keyboard: when Steam's OSK appears
(via the keyboard hardware button), ours mirrors it on top while Steam's is hidden.

## Features

- **Real keycodes via `/dev/uinput`** — full Ctrl/Alt/Shift/Super, F1–F12, arrows, nav
  cluster, symbols; works in Game Mode UI, desktop apps, and games.
- **JSON-configurable** — the button list (`config/layouts/*.json`), transparency, theme,
  geometry, and key sizes (`config/config.json`). No code edits to re-skin or re-map.
- **US / UK locale switching** — a 🌐 key cycles the OS XKB layout via KDE's
  `KeyboardLayouts` DBus and re-skins the key labels to match (`config/locales/*.json`).
  Because we inject keycodes, the typed character is decided by the OS layout — the locale
  maps keep the painted labels honest.
- **Sticky one-shot modifiers** with an obvious armed indicator.
- **Self-healing** — a watchdog respawns the keyboard if a Steam/compositor restart kills
  it; the Steam OSK is force-hidden via `_NET_WM_WINDOW_OPACITY` (reliable) + a KWin script.

## Architecture

Two processes (both autostart at login):

| File | Role |
|------|------|
| `bin/claude-kbd.py` | The keyboard. GTK3 + python-evdev `UInput`. Normal undecorated window pinned by a KWin window-rule; starts hidden; `SIGUSR1`=show / `SIGUSR2`=hide. Reads `~/.config/claude-osk/`. |
| `bin/claude-kbd-swap.sh` | Mirror daemon. Detects Steam's OSK, hides it (`xprop` opacity 0), mirrors visibility to ours, regenerates the KWin opacity script from `config.json`, and watchdogs the keyboard. |
| `bin/claude-osk-relogin` | Notifies / prompts a logout when newly-added KDE layouts need a relogin to register. |
| `kwin/claude-osk-opacity/` | KWin script that makes our window translucent (opacity from config) and Steam's OSK invisible. `main.js` is regenerated at runtime; `metadata.json` is the package descriptor. |

### Config (installed to `~/.config/claude-osk/`)
- `config.json` — `layout`, `locale` (`auto`/`us`/`gb`), `opacity`, `geometry`, key sizes, `theme`, `game_overlay` (Phase 2).
- `layouts/<name>.json` — rows of keys: `{"label","key":"KEY_*","kind":"wide|space|mod|hide|locale","shifted":"…"}`. `key` is an evdev name; unknown keys are skipped, not fatal.
- `locales/<code>.json` — per-XKB-layout label overrides by key name.

The keyboard ships built-in fallback defaults, so a missing/corrupt config never leaves you keyboardless.

## Status

**v0.0.1 — Desktop Mode (KDE/KWin) working.** JSON config, transparency, and US/UK locale
switching all verified on a Legion Go 2 (CachyOS, Plasma 6 Wayland).

### Roadmap
- **P0** — Game Mode overlay via gamescope `GAMESCOPE_EXTERNAL_OVERLAY` (overlay running games), with a toggle to fall back to desktop-only when a game misbehaves.
- **P2** — dual-mode daemon: KWin path on desktop, gamescope path in Game Mode.
- **P3** — packaging: `install.sh` (pkexec udev rule for `/dev/uinput`; **non-destructive** merge of `us,gb` into `kxkbrc` then a relogin prompt; `~/.local` + autostart deploy) wrapped in a `.desktop` launcher; AUR package. (`legacy/claude-osk.OLD` is the previous monolithic installer, kept for its kwinrulesrc rule logic — to be rewritten here.)
- **P4** — optional Decky plugin front-end once the Game Mode overlay exists.

## Requirements
- KDE Plasma 6 (Wayland), gamescope/Steam session
- `python3`, `python-gobject` (GTK3), `python-evdev`
- write access to `/dev/uinput` (udev rule + `input` group)

## License
TBD
