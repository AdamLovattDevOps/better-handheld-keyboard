# Changelog

Releases are cut by pushing a tag. `.github/workflows/release.yml` takes the notes for
that version from the section below, packages the tree, and publishes the GitHub release.

```bash
git tag -a v1.2.3 -m "v1.2.3" && git push origin v1.2.3
```

The heading must be `## v<version> — <title>` and the version must match the tag.

## v1.0.2 — Predictive text and a bigger keyboard

Everything from v1.0.1 stays: the trigger detection fix, the fail-visible KWin rule, the
recovery script. This adds the features that had been living on my own Legion Go 2.

### Added

- **Predictive text.** A row of tappable suggestions above the keys, backed by
  `handheld_kbd_predict.py`. Learns the words you commit (`predict_learn`, stored in
  `~/.local/share/handheld-kbd/learned.json`, never leaves the device) and blends that
  with corpus frequencies built once by the new `handheld-kbd-build-dict`. Tapping a
  suggestion erases the partial word and types the full one as real keystrokes, so it
  works in any application. Falls back to a plain keyboard if the engine or its data is
  missing, and off entirely with `"prediction": false`.
- **Big mode.** A `size` key (⤢) toggles between `geometry` and the new `big_geometry`,
  stretching every key to fill the window and rewriting the KWin rule live — no relogin.
  `start_big` comes up in it.
- **Opacity cycling.** An `opacity` key (◐) steps through `opacity_steps` and persists
  the choice, instead of editing JSON to see what's behind the keyboard.
- **Swipe typing.** Drag across the letters to type a word (`handheld_kbd_swipe.py`).
  A drag only counts once it travels `swipe_min_travel` key-widths and crosses
  `swipe_min_keys` distinct letters, so ordinary taps are untouched. Runner-up decodings
  appear in the suggestion row.
- **Two more ways to summon it.** `gesture_summon` shows the keyboard on a two-finger
  swipe up from the bottom edge of the touchscreen; `show_on_focus` shows it whenever a
  text field takes focus, via AT-SPI (`handheld-kbd-focus-probe` helps identify what the
  bridge reports). Both show-only and both off by default.
- **Resume handling.** `handheld-kbd-resume-watch.py` listens for logind's
  `PrepareForSleep` and re-initialises the keyboard on wake, fixing a stale trigger or
  uinput handle after sleep. Installed as an autostart entry.
- **Multi-display docking.** The window anchors to the internal panel (`internal_output`,
  auto-detecting `eDP*`) so an external display doesn't drag the keyboard off-screen.

### Changed

- The KWin script now also keeps the keyboard above fullscreen windows (temporarily
  dropping the fullscreen window to `keepBelow`, restored afterwards) and re-asserts
  focus on the window you were actually typing into when the keyboard maps.
- `full.json` gains the ◐ and ⤢ keys.

Prediction data (`unigrams.txt`, `bigrams.txt`, `learned.json`, `raw/`) is generated on
device and git-ignored — the repo ships the builder, not the data.

## v1.0.1 — Legion Go 1 keyboard recovery

**If you installed v1.0.0 on a Legion Go 1 — or on a Steam Deck or ROG Ally running Bazzite
or ChimeraOS — and lost your on-screen keyboard entirely, this release fixes it.** Sorry
about that.

### Recover an affected install

Double-click **`Recover My Keyboard.desktop`**, or run:

```bash
handheld-kbd-recover
```

Re-running `./install.sh` repairs the same thing. Either route restores Steam's keyboard and
switches this one to mirror mode. `handheld-kbd-recover --stock-only` stands everything down
and hands the desktop back to Steam's keyboard.

### What was broken

The installer chose its "seamless" trigger by grepping InputPlumber's default profile for
`button: Keyboard`. That profile is generic — it carries the mapping on every device — so
seamless mode was selected on hardware where no button can ever emit the event. The Legion
Go 1's InputPlumber driver declares `Gamepad:Button:Keyboard` but nothing physical sends it;
the Steam Deck and ROG Ally drivers don't reference it at all. The remapped button did
nothing, and because the KWin script still forced Steam's on-screen keyboard to
`opacity = 0.0`, both keyboards were gone.

Stock SteamOS on a Steam Deck was unaffected — it doesn't ship InputPlumber — as was the
Legion Go 2, which has a real keyboard button.

### Fixed

- Seamless mode is selected by DMI product name (Legion Go 2) rather than by the generic
  InputPlumber profile; every other device defaults to mirror mode, which needs no hardware
  button
- Steam's keyboard is only made transparent once this one is known to appear — mirror mode
  qualifies inherently, seamless mode waits for proof the trigger fired. A dead trigger now
  leaves you with the stock keyboard instead of nothing
- The daemon falls back to mirror mode for the session if the InputPlumber remap fails
- `handheld-kbd-ip-remap` verifies the profile actually loaded, warns when a device reports
  no keyboard button, and fails loudly instead of silently
- `Home` and `End` dropped from the full layout — the arrow cluster and `PgUp`/`PgDn` already
  cover that navigation

### Added

- `handheld-kbd-recover` and a double-clickable `Recover My Keyboard.desktop`, because typing
  is not an option when you have no keyboard
- This changelog, and a tag-driven release workflow

Thanks to the Legion Go 1 user who reported it and confirmed the fix.

## v1.0.0 — First release

Real-keystroke on-screen keyboard for SteamOS / KDE Plasma handhelds in Desktop Mode.

- Keys injected through `/dev/uinput` as a virtual input device, so `Ctrl`, `Alt`, `Super`,
  `F1`–`F12`, `Tab`, `Esc` and the arrows reach any focused application — including `Ctrl+C`
  in a terminal
- Triggered by the hardware keyboard button: mirror mode follows Steam's OSK visibility,
  seamless mode remaps the button via InputPlumber to fire a DBus event so no keystroke leaks
  to Steam or KDE
- Adjustable transparency via a KWin script, default `0.72`
- Full and compact layouts, US and UK locales; the 🌐 key switches KDE's XKB layout and
  re-skins the labels so printed and typed stay in sync
- Everything configurable in `~/.config/handheld-kbd/config.json`

Requires KDE Plasma 6, `python3`, `python-gobject` (GTK 3), `python-evdev`.
