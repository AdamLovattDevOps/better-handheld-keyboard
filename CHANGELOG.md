# Changelog

Releases are cut by pushing a tag. `.github/workflows/release.yml` takes the notes for
that version from the section below, packages the tree, and publishes the GitHub release.

```bash
git tag -a v1.2.3 -m "v1.2.3" && git push origin v1.2.3
```

The heading must be `## v<version> — <title>` and the version must match the tag.

## v1.0.8 — Event-driven, free movement, and prediction that works out of the box

### Changed

- **Free move, not lock.** ✥ turns free movement on — a drag bar appears, drag it anywhere,
  grab either end to resize — and ✓ finishes, leaving the keyboard exactly where you put
  it, including half off the edge of the screen if that is what you want. It behaves like
  an ordinary window while you are placing it. ⤓ puts it back to the bottom dock.
- **One thing places the keyboard.** A KWin window rule and the KWin script were both
  asserting a position, and the rule won about a second later — which is why a keyboard you
  had just dragged snapped back. Rules are now `DontAffect` permanently and the script is
  the sole authority: it computes the dock (logical pixels, panels excluded) or applies
  your custom spot once and then leaves the window alone.
- Custom positions are stored exactly as the compositor reports them, with no clamping.
  Only the dock is clamped, because that one is ours to compute.

### Added

- **`handheld-kbd-toggle`** — show/hide without going through Steam. Mirror mode summons the
  keyboard by watching Steam's on-screen keyboard, so if Steam dies you have no keyboard,
  which is a poor place to be when you need to type a command to fix Steam. Bind it to a KDE
  shortcut, or use the `Toggle Keyboard.desktop` launcher.
- **A DBus service** (`org.handheld.Keyboard`): `Show`, `Hide`, `Toggle`, `FreeMove`,
  `Reset`, `SetGeometry`. This is how the compositor drives the keyboard, and it makes every
  action scriptable.
- **Prediction data builds itself.** The installer built nothing and only printed a hint, so
  a fresh install had an empty dictionary and prediction appeared not to work at all. It is
  now built in the background at install time, and the keyboard self-heals on startup if the
  data is missing.
- **Optional profanity filtering of suggestions.** Suggestions come from a web-frequency
  corpus and appear unbidden above the keys. Deciding which words to withhold is a job for a
  maintained library, so `handheld-kbd-install-filter` fetches `better-profanity` (no pip on
  SteamOS) and the release archive bundles it, so offline installs get it too. It governs
  only what is *offered* — you can always type anything. Measured on a Legion Go 2: 403 of
  80,000 corpus words are withheld.

### Fixed

- **The swap daemon no longer polls.** In mirror mode — which is what every device without
  a dedicated keyboard button uses, including a stock Steam Deck — it walked the whole X
  window tree ten times a second (`xwininfo` + `grep`, plus an `xprop` write per match) to
  notice Steam's on-screen keyboard appearing, and unmapped that window through `xdotool`.
  That is a constant drip of processes poking Steam's own windows, on a device where Steam
  Input drives the trackpads. The KWin script now calls the keyboard over DBus the moment
  that window maps or unmaps, and the daemon's loop is a 2-second supervisor that only
  respawns the keyboard and keeps the script loaded. Measured on a Legion Go 2: the old
  daemon used 27.2s of CPU in a session, the new one 1.4s, and 0 ticks per 5s at idle.
- **Summoning is fast and repeatable.** Showing the keyboard used to redo placement every
  time — a config write, a KWin reconfigure and a script reload before anything appeared.
  Placement is now cached and only redone when something it depends on changes (mode, size,
  display layout). Show/hide round trip over DBus measured at 3-6 ms, 28 ms on the first
  show when placement really does run. Show and hide are also idempotent, so a repeat
  press can't double-fire or leave the state file disagreeing with the window.
- **The hide key dismisses Steam's keyboard directly** instead of setting a latch for the
  poll to pick up, so it happens on the press rather than up to 100 ms later.
- The keyboard's own output is no longer thrown away when the daemon respawns it; it goes
  to `/tmp/handheld-kbd-out.log`, which is where a startup failure would show up.

### Known issue: Steam Deck stick-mouse

On a Steam Deck, a single keystroke from *any* virtual keyboard stops Steam Input's
stick-mouse working, while the trackpad (absolute pointer motion) keeps working. It is not
specific to this keyboard: it reproduces with a bare `uinput` device emitting one key, with
no window and no KWin script, and the device's identity (bus type, vendor, product) makes no
difference. Nothing changes at the device layer — same devices, handlers and grabs before
and after. Recovery, without a reboot:

```bash
steam -shutdown && sleep 5 && steam -silent &
```

`handheld-kbd-toggle` exists partly for this: it summons the keyboard even when Steam is
down.

## v1.0.7 — Correct at any resolution and any scale

v1.0.6 docked the keyboard using the display's *physical* pixels. KWin positions windows
in *logical* ones, and the two are only the same at scale 1. A Legion Go 2 is a 1920x1200
panel at scale 1.5 — a 1280x800 desktop — so a 1920-wide rect went mostly off the side.

### Fixed

- **Display scaling.** Screen geometry now comes from GDK, which reports the same logical
  space the compositor uses, so any scale factor (including fractional) is handled without
  arithmetic on our part. The `kscreen-doctor` fallback divides the mode size by the
  output's scale, and `handheld-kbd-dock-rect` does the same.
- **The panel is no longer covered, and the keyboard no longer hangs off the bottom.**
  Docking is now done by the KWin script using `clientArea(MaximizeArea)` — the only
  source that knows the usable area (logical, panels excluded). In docked mode the window
  rule is set to DontAffect so it can't fight the script; the rule is only forced for a
  position you locked yourself.
- **Keys are sized to the dock height before the window is placed.** Previously they kept
  their natural height, the window's minimum exceeded the dock height, and the compositor
  returned a taller window whose bottom fell off the screen (measured: a 336px dock coming
  back as 438px). Key height is now derived from the target height, so the keyboard takes
  the same fraction of the display on an 800px panel as on a 1200px one. The script also
  re-anchors to whatever height the client insists on, as a backstop.

Measured on a Legion Go 2 (1920x1200 @ 1.5): keyboard `0,440 1280x336` against a work area
of `0,0 1280x776` — full width, bottom edge flush with the top of the Plasma panel.

## v1.0.6 — Same place on every device

### Changed

- **Docked to the bottom, identically everywhere.** The default position is no longer a
  pixel rect that happened to suit a 1280×800 Deck. `position_mode: "bottom"` (the new
  default) ignores `geometry` and computes the spot from the panel: full width, flush with
  the bottom edge, height a fraction of the display (`dock_height_frac`, 0.42; big mode
  `big_height_frac`, 0.55). A Deck LCD, a Deck OLED and a Legion Go 2 now get the same
  keyboard in the same place, which is how Steam's own OSK behaves.
- **The lock key locks, it no longer moves anything.** Locking used to re-apply the
  configured geometry, so the keyboard jumped back instead of staying where you dragged
  it. It now reads back where you left it, forces exactly that rect, and stores it as
  `position_mode: "custom"`. If the position can't be read back it still locks and leaves
  the window alone rather than yanking it somewhere you didn't choose.
- **Reset is its own key** (`kind: "reset"`, ⤓). Puts the keyboard back to the bottom dock
  and forgets the custom spot.
- **Unlocked mode looks calmer.** The drag bar was bright orange (it was reusing the
  active-modifier colour). It's now a dark slate bar with a thin accent line, muted grip
  labels, and the lock key uses its own accent style instead of the modifier one. Themable
  via `handle_bg` / `handle_fg`.

### Fixed

- A second instance exiting on the single-instance lock no longer writes a crash log —
  that's ordinary behaviour when the watchdog and autostart race, not a failure.
- `geometry` and `big_geometry` are gone from the shipped config; they're derived. The
  installer now uses `handheld-kbd-dock-rect` to seed the KWin rule so the first show
  doesn't flash at the wrong size.

## v1.0.5 — Upgrades that actually upgrade

Two bugs with the same shape: files that were only ever written on a *fresh* install, so
an upgrade left the system in a state the rest of the code didn't expect.

### Fixed

- **Opacity cycling stopped working after a re-install.** The KWin script had two writers:
  the installer copied a static `main.js` with `w.opacity` hardcoded to `0.72` and no
  `var OP` line, while the swap daemon generated a different one that had it. The opacity
  key patches `var OP`, so against the static copy it silently patched nothing and every
  reload snapped the keyboard back to `0.72` — the config recorded each step down, the
  window ignored them. There is now one writer, `bin/handheld-kbd-kwin-script`, shared by
  the installer, the daemon and the opacity key; the static copy is gone. The key
  regenerates through it, falling back to patching either historical script shape.
- **New keys never reached existing installs.** Layouts are only written when absent, so a
  release could ship the code for a key while the user's layout had no button for it —
  which is exactly what happened to v1.0.4's ✥. The installer now merges in any action key
  (`locale`, `hide`, `size`, `opacity`, `move`) the release has and the layout lacks,
  backing the file up first, and prunes settings that no longer do anything (`dock` and
  `dock_edges`, from the superseded slot design). Idempotent, and it leaves your own
  customisations alone.

## v1.0.4 — Unlock, drag, lock

The v1.0.3 move key cycled through preset docking slots. It didn't work well, so this
replaces it with the obvious thing: unlock the keyboard, put it where you want, lock it.

### Changed

- **The move key (✥) is now a lock toggle.** Press it and the keyboard unlocks: KWin
  stops forcing its position and size, and a bar appears along the top — drag anywhere on
  it to move the window, or use either end (⤡ / ⤢) to resize. Press again and it locks
  exactly where you left it, saving the result as `geometry` so a respawn or relogin comes
  back to the same place.
  - Wayland clients can't place their own windows, so both gestures hand off to the
    compositor (`begin_move_drag` / `begin_resize_drag`) — the same mechanism a titlebar
    uses — and the position is read back from what KWin remembered.
  - Unlocking switches the rule to Remember (4) and locking switches it back to Force (2),
    so nothing nudges the keyboard while it's locked.
  - It always starts locked; an unlocked keyboard that got respawned would drift.
  - Desktop Mode only — in Game Mode there's no window to drag, and the key says so.
- Removed the docking-slot cycle, `dock` and `dock_edges`. `handle_height` (default 30)
  sets the drag bar's height.

The v1.0.3 resolution clamping stays: the configured geometry is still clamped to the
panel it lands on, so a saved position can't put the keyboard off-screen.

## v1.0.3 — A move key (superseded by v1.0.4)

### Added

- **Move key** (`kind: "move"`, ✥). Steps the keyboard through docking slots instead of
  leaving it pinned wherever the KWin rule put it:
  - slot 0 is the configured `geometry`, anchored to the internal panel — unchanged
    default, so nothing moves unless you ask it to
  - then one slot per (display, edge) pair — `bottom`, `top`, `middle` by default via
    `dock_edges` — internal panel first, centred horizontally on that display
  - the slot list is resolved live from `kscreen-doctor`, so plugging in a monitor adds
    its slots without a restart, and unplugging wraps the selection back into range
  - it also forces the KWin rule to be rewritten even when the rect looks unchanged,
    which is the way out of a position that has got stuck
  - the chosen slot persists to `config.json` as `dock`, and the key's label shows the
    edge — plus the display name once there's more than one to choose from

### Fixed

- **Works on any panel resolution.** Every rect — including the configured one — is now
  clamped to the display it's going onto: sizes shrink to fit, then the position is pulled
  back inside. The shipped geometry is sized for a 1280×800 Steam Deck, so on a 1280×720
  panel it used to hang 78px off the bottom, and a partly-off-screen Wayland window still
  takes taps while not being fully visible. No-op where it already fits, so the Deck and
  the Legion Go 2 are unchanged.
- **The installer sizes for the panel it's on.** On a fresh install, `geometry` and
  `big_geometry` are derived from the internal display (full width, 55% / 64% height,
  bottom-docked) instead of assuming 1280×800, and the forced KWin rule is written from
  that geometry rather than a hardcoded `0,378 1280,422`. Existing configs are left alone.

### Changed

- Display enumeration moved into one `_outputs()` helper (name, position, current-mode
  size, internal flag), which `_panel_origin()` now uses too.

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
