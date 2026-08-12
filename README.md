# Better Handheld Keyboard

> **Heads up:** this is for **Desktop Mode** (KDE Plasma). Game Mode works
> differently under the hood and isn't covered here.

![Better Handheld Keyboard — colour themes, split, 1×–4× sizes, adjustable transparency, layout-aware labels and custom super-key icons](docs/showcase.gif)

If you've ever tried to do something *real* on a SteamOS handheld in Desktop
Mode — open a terminal, use an app with keyboard shortcuts — you've probably hit
the same wall I did.

The built-in on-screen keyboard just couldn't do it. No working `Ctrl`, so no
`Ctrl+C` in the terminal. No reliable `Tab`, `Esc`, or arrow keys. It was opaque
and covered half the screen, and it felt sluggish to bring up. Fine for typing a
Wi-Fi password; useless for actually using the machine.

So I built the keyboard I wanted instead. Here's what it does differently:

- **It types real keystrokes.** Instead of faking input, it injects keys through
  `/dev/uinput` — the same path a real USB keyboard uses. So `Ctrl`, `Alt`,
  `Shift`, `Super`, `F1`–`F12`, `Tab`, `Esc`, and arrows all genuinely work,
  everywhere. `Ctrl+C` in a terminal just works.
- **It uses the button you already press.** I remapped the hardware keyboard
  button so it summons this keyboard instead of the stock one. Press to show,
  press again to hide — no menus, no Steam Input fiddling.
- **It's see-through.** Adjustable transparency, so it's not blinding the screen
  behind it.
- **It's mine to theme, and yours too.** Layout, colours, key sizes, and opacity
  all live in a JSON file. No code to touch.
- **Twenty layouts.** English (US/UK), German, French, Spanish (Spain and Latin
  America), Italian, Portuguese (Portugal and Brazil), Dutch, Polish, Turkish,
  Russian, Ukrainian, Greek, Arabic, Hebrew, Hindi, Thai and Vietnamese. The 🌐 key
  switches between the ones you've configured and re-skins the keys, so `£`, `ñ`, `ç`,
  `й` and `ก` are drawn where they actually are. `handheld-kbd-locales` picks which.
- **AltGr.** Most layouts keep a third of their alphabet behind it — Polish `ą`, French
  `@`, Turkish `î`. Hold it and the keys show what they'll type.
- **Live Shift preview.** Hold Shift and every key shows the capital or symbol it will
  actually type as its main label — no colour change, just the glyph swaps. Toggle it in
  the tray **Settings ▸ Shift preview**.
- **Predictive text.** A row of tappable suggestions above the keys. It learns
  what *you* type, and `handheld-kbd-build-dict` adds corpus frequencies so it's
  useful from the first keypress. Tapping a suggestion types it as real keys, so
  it works in any app. Off with `"prediction": false`.
- **Four sizes.** The size key cycles **1× → 2× → 3× → 4×** (labelled with the size, no
  cryptic arrow) — each step a genuinely larger keyboard with bigger keys, for thumbs on a
  7-inch panel or precision when you're docked. Cycles live, no relogin (also in the tray
  **Settings ▸ Keyboard size**), and it's kept within the panel so even 4× doesn't clip off
  the edges.
- **Colour themes.** Six ready-made palettes — Midnight, Light, High contrast, Nord,
  Solarized and Rose — from the tray **Settings ▸ Colour theme** or
  `handheld-kbd-ctl set color_theme <name>`. The whole keyboard recolours — keys, labels
  and the predictive-text bar — the super-key logo tints to match, and the labels stay
  legible whatever your desktop GTK theme is.
- **Custom super-key icon.** Put a **Windows**, **Arch** or **Tux** logo on the meta key —
  tray **Settings ▸ Super key icon** or `handheld-kbd-ctl super-icon <name>`. It tints to
  the current theme, so it stays visible on the light themes too.
- **Split keyboard.** Turn on `split` (tray **Settings ▸ Split keyboard**, or
  `handheld-kbd-ctl set split true`) and each row's two halves slide out to the
  left and right edges with a clear gap down the middle — thumb-typing while you
  grip the device. Works over any layout; `split_gap` sets the gap width.
- **Cycle transparency from the keyboard.** The ◐ key steps through
  `opacity_steps` instead of making you edit JSON to see what's underneath.
- **Same place on every device.** It docks flush with the bottom edge, full
  width, at a fixed fraction of the panel height — a Deck LCD, a Deck OLED and a
  Legion Go 2 all get the same keyboard in the same spot.
- **Or put it where you want it.** ✥ turns on free movement: a bar appears along
  the top, drag it anywhere, grab either end to resize, then press ✓ to finish —
  it stays exactly where you left it, like any other window. ⤓ resets it to the
  bottom dock.
- **It doesn't need Steam.** `handheld-kbd-toggle` shows and hides it directly, so
  a dead Steam client can't leave you without a keyboard. Bind it to a shortcut.
- **Your trackpads still work.** While Steam thinks its own keyboard is open, the
  sticks and trackpads navigate *that* instead of moving the pointer. So whenever
  Steam's keyboard appears — the button press that summons this one on a Deck, or a
  controller focusing a text field on any device — it's closed rather than hidden,
  whatever trigger mode you're in, and the pointer stays yours.
- **A tray icon.** Tap to show or hide; right-click for restart, reset position, fix the
  trackpad pointer, stop and start — and a **Settings** submenu that toggles prediction,
  glide typing and the rest, and picks the layout, super-key icon,
  suggestion count and more, without touching `config.json`. The settings are grouped
  under **Typing**, **Layout & appearance** and **Summoning & input** headings.
- **Shortcuts for when it goes wrong.** The same actions appear in the application menu —
  clickable, because typing is the one thing you can't do when the keyboard is the
  problem.
- **Swipe typing.** Drag across the letters instead of tapping them. Taps are
  unaffected — a drag only counts once it's unmistakably not one.
- **Optional summon gestures.** Two-finger swipe up from the bottom edge
  (`gesture_summon`), or auto-show whenever a text field takes focus
  (`show_on_focus`, via AT-SPI). Both off by default.
- **Survives sleep and fullscreen.** It re-initialises after resume, and stays
  visible above fullscreen windows instead of disappearing behind them.

## Install

Upgrading? Just re-run the installer — it won't ask for a password, because the
permission it needs is already there from last time.

Double-click **`Install Better Handheld Keyboard.desktop`**, enter your password
once (it needs `/dev/uinput` access — that's how it types real keys), then **log
out and back in**.

Prefer the terminal? `./install.sh`, then log out and back in.

## How it works

```
  keyboard button ──remap──▶ InputPlumber ──DBus event──▶ handheld-kbd
                                                    tap a key │
                                                              ▼
                              focused app ◀── real keystroke ◀── /dev/uinput
```

The button is remapped to fire a **DBus event** rather than a keystroke, so
nothing else reacts to it. Key taps go through **`/dev/uinput`** at the kernel
level — which is why they reach any app.

## No keyboard at all? Read this

If you installed an earlier version on a **Legion Go 1** — or on a Steam Deck / ROG Ally
running Bazzite or ChimeraOS — you may have ended up with *no* on-screen keyboard. Sorry.
The installer picked its "seamless" trigger by looking at InputPlumber's default profile,
which advertises a keyboard button on every device, and remapped a button your hardware
never actually sends. Meanwhile it kept Steam's own keyboard transparent. Both keyboards
gone.

Fix it either way:

```bash
handheld-kbd-recover          # puts Steam's keyboard back, switches this one to mirror mode
./install.sh                  # re-running the installer now repairs the same thing
```

Or double-click **`Recover My Keyboard.desktop`** in this folder — no typing required, which
rather matters when you have no keyboard.

Want out entirely? `handheld-kbd-recover --stock-only` stands everything down and hands the
desktop back to Steam's keyboard.

## Trackpads or stick pointer stopped working?

Versions before 1.0.10 hid Steam's on-screen keyboard instead of closing it. Steam kept
believing its keyboard was open, and while it believes that it puts the controller in its
"KB ActionSet" — sticks and trackpads navigate Steam's keyboard rather than moving the
pointer. 1.0.10 and 1.0.11 closed it, but only in mirror mode, so a device on the DBus or
hotkey trigger (a Legion Go 2, say) could still get stuck; since 1.0.12 it's closed in
every trigger mode. Update, and if a session is still stuck:

```bash
handheld-kbd-fix-pointer
```

Or click **Fix Trackpad and Stick Pointer** in the application menu. It closes the leftover
window; no Steam restart, no relogin.

## Controlling it

The tray icon is the quickest route: tap to show or hide, right-click for the rest. If it
isn't in your system tray, Plasma may be hiding it — check the tray's overflow arrow, or
its settings. `handheld-kbd-tray` starts it by hand.

```bash
handheld-kbd-ctl status      # what's running, and where the keyboard is
handheld-kbd-ctl restart     # the usual fix
handheld-kbd-ctl stop        # until you start it again or log back in
handheld-kbd-ctl reset       # back to the bottom dock
handheld-kbd-ctl set prediction false bool   # set any config key, then restart
handheld-kbd-ctl set layout compact str      # (the tray Settings menu drives this)
```

All of these are in the application menu too.

## Predictive text

Prediction works out of the box from what you type. For suggestions that are useful
before it has learned anything, build the corpus data once:

```bash
handheld-kbd-build-dict
```

That writes `unigrams.txt` and `bigrams.txt` into `~/.local/share/handheld-kbd/`. It
prefers Peter Norvig's `count_1w.txt` / `count_2w.txt` if you drop them in
`~/.local/share/handheld-kbd/raw/`, and falls back to the system aspell dictionary
when offline. Re-runnable, and it never touches `learned.json` — that's your personal
vocabulary, stays on the device, and is in `.gitignore` for a reason.

Turn learning off with `"predict_learn": false` (corpus only), or prediction entirely
with `"prediction": false`.

## Languages

```bash
handheld-kbd-locales                # what's configured, and what labels exist
handheld-kbd-locales set us gb it ru
```

Then log out and back in — KDE reads its layout list at session start — and 🌐 cycles
through them.

Check what this machine can actually manage:

```bash
handheld-kbd-locales --check
```

Shipping labels for twenty languages doesn't make twenty languages work — the layout
comes from `xkeyboard-config` and the glyphs from your system fonts. `--check` reports
both per language, and the installer runs it for you. A missing font means the keys type
correctly but draw as empty boxes; install the Noto font for that script.

**Keep one Latin layout among your four.** Application shortcuts are bound to Latin
keysyms, so with only non-Latin layouts loaded the S key produces (say) `Cyrillic_yeru`
and `Ctrl+S` never reaches Save — likewise `Ctrl+C`, `Ctrl+V`. KDE's Latin fallback
covers global shortcuts, not an application's own. `handheld-kbd-locales` warns if you
pick four without one.

**Four at a time.** Labels ship for twenty layouts, but an XKB keymap holds four groups
at most, so four can be live at once. That is the keymap format, not a setting: ask
libxkbcommon for a fifth and it discards it outright (`Unrecognized RMLVO layout "es" was
ignored`). Swapping which four is a `set` plus a log out.

Worth knowing how this works, because it explains what it can and can't do. The keyboard
injects real keycodes, exactly like a USB keyboard; **what a key types is decided by the
OS layout**, not by this program. So a locale file here contains no behaviour at all, only
the labels to paint on the keys. They're generated from
[xkeyboard-config](https://gitlab.freedesktop.org/xkeyboard-config/xkeyboard-config) — the
same data the OS uses — by `tools/build-locales.py`, rather than typed out by hand in
scripts most of us can't proofread.

Two consequences:

- **A layout with no labels still works.** It types correctly; the keys are just drawn
  with US captions. Any of the hundreds of layouts KDE offers can be added.
- **Chinese, Japanese and Korean aren't here, and can't be.** Those are input methods, not
  keyboard layouts — no mapping of keycodes to characters produces them. Use Fcitx or
  IBus; this keyboard's keystrokes reach it like any other keyboard's.

Vietnamese is a halfway case worth calling out. The `vn` layout puts `ă â ê ô ơ ư đ` on
the number row and tone marks on `5`–`9`, which costs you the digits and can't produce
every syllable. Most Vietnamese typing is done with an IME (Telex or VNI) on a US layout
instead — that works here too, and is probably what you want.

## Configure

Everything's in `~/.config/handheld-kbd/config.json` — `opacity`, `layout`,
`locale`, `color_theme`, `size_level`, `super_icon`, `split`, per-key `theme`
colours, key dimensions, optional `hotkey`. Edits apply next time the keyboard
restarts. Layouts and locales sit beside it as plain JSON.

## Uninstall

`./uninstall.sh` — removes the program, autostart, shortcuts, the KWin script and
the udev rule. Your config in `~/.config/handheld-kbd/` is left in place; delete it
yourself if you want the learned predictions gone too.

## Requirements

KDE Plasma 6 (Wayland) · `python3`, `python-gobject` (GTK 3), `python-evdev`.
The installer adds you to the `input` group.

## License

MIT — see [LICENSE](LICENSE). It's all local; nothing leaves your device.
