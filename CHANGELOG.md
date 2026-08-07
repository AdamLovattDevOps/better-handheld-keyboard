# Changelog

Releases are cut by pushing a tag. `.github/workflows/release.yml` takes the notes for
that version from the section below, packages the tree, and publishes the GitHub release.

```bash
git tag -a v1.2.3 -m "v1.2.3" && git push origin v1.2.3
```

The heading must be `## v<version> — <title>` and the version must match the tag.

## v1.0.11 — Twenty languages

Pre-release. The mechanism is tested; the individual layouts are not — I read Latin
scripts and can spot-check Cyrillic and Greek, and that is the end of my usefulness as a
proofreader for Arabic, Hebrew, Devanagari and Thai. Corrections very welcome.

### Added

- **Key labels for twenty XKB layouts.** English (US/UK), German, French, Spanish (Spain
  and Latin America), Italian, Portuguese (Portugal and Brazil), Dutch, Polish, Turkish,
  Russian, Ukrainian, Greek, Arabic, Hebrew, Hindi (Devanagari), Thai and Vietnamese.
  🌐 switches between the layouts KDE has configured and re-skins the keys to match.

  These are *labels*, not behaviour. The keyboard injects real keycodes, so what a key
  types was always decided by the OS layout — what was missing is the keyboard admitting
  it, by drawing `й` on the key that types `й` instead of `q`. A layout with no labels
  still works; it is just drawn with US captions.

  They are generated from [xkeyboard-config](https://gitlab.freedesktop.org/xkeyboard-config/xkeyboard-config)
  and xorgproto's `keysymdef.h` by `tools/build-locales.py`, and committed. Typing them
  out by hand would have been twenty chances to be subtly wrong in scripts I cannot
  proofread. All twenty resolve all 47 keys — anything less is treated as a parser bug,
  which is how these were found:

  - Comments were counted when scanning for the end of a block. These files annotate keys
    with the characters they produce, and those annotations contain braces —
    `key <AB03> {[...]};  // ؤ }` — so the Arabic layout ended after three keys and
    silently lost the other seven, leaving `v b n m , . /` drawn in Latin.
  - Keysyms were resolved by their own `U+` comment, but several names share a code and
    only one carries the annotation; the rest read "deprecated alias for …". That lost
    `masculine` and `guillemotleft`, and with them `º` on the Spanish layout and `«` `»`
    on the Portuguese one. Resolution now goes through the keysym code.
  - Greek redefines only levels 3 and 4 over `gr(simple)` using `any` for the first two,
    so replacing whole entries threw the alphabet away — levels merge individually now.
  - `key <AD08> { type[group1] = "…", [ i, I ] }` — that first bracket is not a symbol
    list, and taking it lost Turkish's dotted/dotless `i`.

  Three parser bugs, each of which shipped a layout that looked plausible and put
  characters on the wrong keys, is three too many to keep finding by eye — particularly
  in scripts I can't read. Every label is now checked against **libxkbcommon**, which is
  the same library the compositor uses to decide what a key actually types, by
  `tools/verify-locales.py`. A label that disagrees is a key drawn with a character it
  does not produce. All 940 key/level pairs across the twenty layouts agree, and CI
  re-checks it on every push.

- **AltGr.** Most non-English layouts keep a third of their characters on the third level
  — Polish `ą`, French `@`, Turkish `î`, Italian `[` — and without an AltGr key they were
  simply unreachable. Holding it re-skins the keys to show what they will type, rather
  than printing three glyphs on a key the size of a fingernail. Existing installs get the
  key added to their layout on upgrade.

- **A system tray icon.** Tap it to show or hide the keyboard; right-click for restart,
  reset position, fix the trackpad pointer, and stop/start. The Show/Hide and Stop/Start
  entries say which one they'll do, rather than offering you the dead half of the pair.

  It speaks the StatusNotifierItem and DBusMenu protocols to Plasma directly rather than
  going through libappindicator — SteamOS is an immutable image with no pip and no
  appindicator package, so a dependency here would be one that cannot be installed. It
  runs as its own process, because its whole job is rescuing a misbehaving keyboard and
  "Restart" shouldn't mean killing yourself mid-click. The supervisor keeps it alive, so
  a Plasma restart doesn't take it away for good.

  Its own process turned out not to be enough. The supervisor runs as a transient systemd
  unit, and stopping a unit stops its whole cgroup — which contained the tray *and* the
  restart script the tray had just launched. The stop half ran, the start half never did,
  and the keyboard did not come back. `start_new_session()` does not help; a cgroup is not
  a session. The tray is now a unit in its own right, and `handheld-kbd-ctl` re-runs
  itself in a transient unit before touching anything, so it cannot be killed by the stop
  it just issued.

- **`handheld-kbd-locales`** — list, add, remove or set the layouts KDE offers, since
  🌐 can only reach layouts KDE has been told about, and with one configured it has
  nowhere to go. Reports which have labels and which don't.

  Four layouts can be live at once, and the tool enforces that. An XKB keymap holds
  four groups — ask libxkbcommon for a fifth and it is discarded outright
  (`[XKB-595] Unrecognized RMLVO layout "es" was ignored`), so a longer list silently
  becomes its first four and the rest never appear. Twenty sets of labels ship; which
  four are live is a `set` plus a log out.

  It also shows which layouts KWin is *actually* running with, and offers to log you
  out. That distinction matters more than it sounds: KWin builds its xkb keymap when the
  session starts and there is no way to make it re-read the list — neither
  `org.kde.KWin.reconfigure` nor reloading kded's keyboard module works, both verified.
  So a freshly added layout sits in the config file looking configured while 🌐 refuses
  to reach it, which is a confusing few minutes if nothing says so.

### Notes on what this can't do

- **Chinese, Japanese and Korean are absent and will stay absent.** They are input methods,
  not keyboard layouts; no mapping of keycodes to characters produces them. Fcitx and IBus
  work with this keyboard exactly as with any other, because the keystrokes are real.
- **Vietnamese is a halfway case.** The `vn` layout puts `ă â ê ô ơ ư đ` on the number row
  and tone marks on `5`–`9` — which costs you the digits and still cannot produce every
  syllable. Most Vietnamese typing uses an IME (Telex/VNI) over a US layout. That works
  here; the layout is shipped for those who want it.

### Verified

Every one of the twenty languages typed into Kate through `/dev/uinput`, saved with
Ctrl+S, and the file read back off disk and compared character by character. Key
positions come from the locale files this keyboard ships, so a label on the wrong key
fails the test — in scripts nobody here can proofread. `tools/kate-type.py`.

All twenty pass. Spanish, Greek and Vietnamese type everything except the characters
needing dead-key or combining composition, as expected.

### Added: `handheld-kbd-locales --check`

Shipping labels for twenty languages does not make twenty languages work. The layout
comes from xkeyboard-config and the glyphs from the system fonts, and a machine missing
either draws boxes or types the wrong thing. `--check` reports both per language, and the
installer runs it so you learn at install time rather than by discovery. Font coverage is
probed once per script through fontconfig, not guessed. Verified on a Legion Go 2: all
twenty layouts present, all scripts drawable — Arabic and Hebrew via DejaVu, Devanagari
and Thai via Noto.

### Known: keep one Latin layout among your four

Application shortcuts are bound to Latin keysyms. With only non-Latin layouts loaded the
S key produces `Cyrillic_yeru`, and Ctrl+S never reaches Save — Ctrl+C and Ctrl+V go the
same way. KDE's Latin fallback covers global shortcuts, not an application's own. Found
by this test failing every save under `ru ua gr ara`, and passing the moment `us` was in
the group. `handheld-kbd-locales` now warns when a selection has no Latin layout.

### Fixed since rc5

- **A label can no longer resize the keyboard.** The key grid is column-homogeneous, so
  every column is as wide as the widest cell — and the 🌐 key reading `🌐LATAM` inflated
  all thirty-six of them, pushing the window to 1728px on a 1280px desktop. GTK refuses
  to shrink a window below its natural width, so ⤓ re-docked to 1280, was refused, and
  looked broken. Labels (and predicted words, which had the same power) now ellipsize;
  the window's size is the dock's business alone.
- **The 🌐 badge names what the OS is actually typing.** The layout list was read from
  `kxkbrc` and the index from the live session — but the file is what the *next* session
  loads. Edit it and `list[index]` names some other layout: the keyboard drew Brazilian
  labels while the OS typed US. Both halves now come from the live session.
- **"Keyboard languages…" in the tray.** A kdialog checklist of all twenty languages —
  tick up to four, get offered the logout. Configuring the keyboard by typing commands
  was exactly backwards. Also `handheld-kbd-locales --gui`.
- **The four-layout ceiling is enforced and explained**, rather than silently truncated
  by libxkbcommon.

## v1.0.10 — The Steam Deck keeps its trackpads

### Fixed

- **The trackpads and stick pointer keep working while the keyboard is up.** On a Steam
  Deck the keyboard is summoned by Steam's own on-screen keyboard appearing, and we hid
  that keyboard by setting its opacity to zero. The window stayed mapped, so Steam went on
  believing its keyboard was open — and while it believes that, it forces the controller
  into its "KB ActionSet", where the sticks and trackpads navigate *that* keyboard instead
  of moving the desktop pointer. Steam says so in its own log:

  ```
  Set OSK active 1 and appid 413080
  OnFocusWindowChanged On Screen Keyboard Forcing to window type: KB ActionSet, AppID 769
  ```

  So you got a keyboard you could only use by touch, and no pointer at all until Steam was
  restarted. Steam's keyboard is now closed rather than hidden, which makes Steam set
  OSK-active back to 0 and reload the desktop controller config. Fixes #14.

  This never affected the Legion Go, where the hardware button is remapped through
  InputPlumber and Steam's keyboard is never involved.

- **The hardware keyboard button toggles again.** Closing Steam's keyboard means Steam no
  longer reports a second press as a close — it just opens a fresh one — so the button is
  handled as a toggle in the compositor rather than mirroring Steam's show and hide.

- **A session that is already stuck recovers without restarting Steam.** Loading the KWin
  script closes any Steam keyboard left over from before, and `handheld-kbd-fix-pointer`
  does the same on demand. It no longer restarts Steam: a half-started Steam client leaves
  you with no pointer at all, which is worse than what it was fixing.

- **`handheld-kbd-ctl` starts the keyboard under the user service manager.** Started from
  an SSH shell it used to inherit no display and no session bus, and came up unable to draw
  or to answer on DBus — precisely when you are least able to debug it.

### Added

- **Application-menu shortcuts.** Show/hide, restart, stop, reset position, and fix the
  trackpad pointer. Typing a command is the one thing you cannot do when the keyboard is
  the problem, so every recovery action is also something you can click.
- **`handheld-kbd-ctl`** — `status`, `start`, `stop`, `restart`, `reset` for the keyboard
  and its supervisor, without logging out. Every action is safe to repeat.

## v1.0.9 — The tick actually holds the position

### Fixed

- **✓ no longer resets the keyboard.** Finishing a move asked KWin where the window was and
  then waited a fixed 250 ms for the answer. When the reply came back later than that — which
  it does after a real drag, as opposed to a scripted one — we had already given up, and
  giving up hands placement back to the script, which re-docks. It now waits for the answer
  (up to ~1.5s, re-asking half way through) and only then saves and holds the position.
- **Geometry reporting no longer depends on one signal name.** KWin has moved these around
  between versions, so the script connects to whichever of `frameGeometryChanged`,
  `geometryChanged`, `moveResizedChanged`, `interactiveMoveResizeFinished` and
  `interactiveMoveResizeStepped` exist, and logs how many it found.

### Changed

- **The free-move indicator is much quieter.** The bar appearing is signal enough; the blue
  fill on the key and the accent stripe on the bar were shouting about it. Muted bar, muted
  grips, and the key takes a thin outline instead of a solid block.

- **No stale position is ever saved.** Starting free movement used to report the window's
  rect immediately, which is the *dock* position. If the drag then emitted none of the
  connected signals that stale value survived, and ✓ saved it — putting the keyboard back on
  the dock. Nothing is seeded now, and finishing clears the value before asking, so it can
  only ever finish on a rect from after the drag.
- **Reloading the KWin script no longer moves the keyboard.** A custom position is applied
  only to a window the script has not seen before, i.e. one that was just created. That is
  how a window manager treats a window you placed yourself: the compositor holds it, and the
  saved rect exists to restore it next time rather than to re-assert it while it is up.
- **A move never falls back to docking.** When the geometry reply arrived too slowly we gave
  up and left the config in dock mode — and docking re-asserts itself on the next geometry
  change, so the keyboard snapped back a moment later. That is what made the reset
  intermittent. There is now a third mode, `free`: nothing places the window at all, so where
  you left it is where it stays even if the readback fails. ⤓ still returns it to the dock.

Verified on a Legion Go 2: moved to an arbitrary 220,140 (not snapped to an edge), held
through the tick, still there three seconds later and after a hide/show cycle, saved as
`custom {x: 220, y: 140}`.

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
