# Infinity Blade through RomM

This deployment adds a deliberately narrow Wine backend to the existing
RomM/WebStation/Selkies service. It recognizes only Infinity Blade I, II and
III, reuses the existing NVIDIA, display, PulseAudio and browser-input stack,
and stores Wine under the persistent WebStation `/config` mount.

No game files are included or downloaded by this repository. Supply copies
you are legally entitled to use. The community release pages are useful for
version and installation notes, but are not a license grant:

- [Infinity Blade I release and documentation](https://archive.org/details/infinity-blade-pc), current documented package `v1.0.4`
- [Infinity Blade II release and documentation](https://archive.org/details/infinity-blade-ii-pc), current documented package `v1.0.6b`
- [Infinity Blade III release and documentation](https://archive.org/details/infinity-blade-3-pc), current documented package `v1.0.0`

The corresponding community announcements are [IB1](https://www.reddit.com/r/infinityblade/comments/1avsqtx/infinity_blade_1_has_been_ported_over_to_pc/),
[IB2](https://www.reddit.com/r/infinityblade/comments/1jovz6c/infinity_blade_ii_has_been_ported_to_pc/), and
[IB3](https://www.reddit.com/r/infinityblade/comments/1wt8jaq/infinity_blade_iii_has_been_ported_to_pc/).

## One-time installation

Extract each supplied port on Sophia so Box sees this layout:

```text
/mnt/sophia/games/Windows/
  Infinity Blade/
    Binaries/Win64/IB1.exe
    SwordGame/...
  Infinity Blade II/
    Binaries/Win32/IB2.exe
    SwordGame/...
  Infinity Blade III/
    Binaries/Infinity Blade III.exe
    SwordGame/...
```

Keep the whole extracted directory for each game, not just the executable.
The backend also recognizes the documented launcher fallbacks and common
Win64 layouts. File matching is case-insensitive. If a future release moves
an executable, set the corresponding relative path in Compose with
`INFINITY_BLADE_IB1_EXE`, `INFINITY_BLADE_IB2_EXE`, or
`INFINITY_BLADE_IB3_EXE`; absolute paths and `..` are rejected.

Initialize the image and Wine runtime:

```bash
cd /home/service/repos/emulator
scripts/setup-infinity-blade.sh
```

The script builds the derived WebStation image, recreates WebStation (and runs
the existing one-shot mount guard), creates
`/srv/emulator/webstation/infinity-blade/prefix`, and installs the documented
Visual C++ 2010 and DirectX 9 helper libraries with Winetricks. It does not
fetch a game. Re-running it is safe; remove only the marker
`/srv/emulator/webstation/infinity-blade/prefix/.infinity-blade-runtime-ready`
if the runtime installation genuinely needs to be repeated.

In RomM, run a quick scan or scan the Windows platform. The `Windows: win`
binding makes the three directories separate Windows games, and the
`win: infinity-blade` streaming mapping adds **Infinity Blade (Wine)** to each
game's Play actions.

## Playing

Open a game in RomM and choose **Infinity Blade (Wine)**. WebStation starts
the known game executable through Wine and RomM opens the existing tokenized
Selkies stream. Use **Save & Quit** or the stream's normal exit control before
leaving when possible; this lets the broker stop Wine, archive changed files,
and let RomM collect them.

Selkies' direct-touch mode already supplies the required mapping:

```text
tap             -> absolute pointer position + left click
drag past 10 px -> left button down + absolute pointer movement
touch end       -> left button up
long press      -> right click
two fingers     -> wheel scrolling
```

The stream-coordinate transform accounts for the rendered canvas and display
resolution, and the touch handlers call `preventDefault`, so Safari scrolling
does not steal an active gesture. Select **Touch** rather than **Trackpad** in
the Selkies touch-input control. Trackpad mode is relative and is not suitable
for sword swipes. Desktop mouse input continues through the normal pointer
path.

The game ports themselves use mouse drags as sword swipes. For IB1, direct
`IB1.exe` is preferred over its configuration launcher so every RomM Play
action reaches the game without another click. If fullscreen or key bindings
must be changed, run the port's launcher once from RomM's WebStation admin
desktop; subsequent game starts remain automatic.

## Saves and recovery

The Wine prefix is persistent at `/srv/emulator/webstation/infinity-blade`.
For session isolation and RomM history, the broker clears and restores only:

```text
prefix/drive_c/users/abc/Documents/My Games/
```

The documented game locations beneath it are:

```text
Infinity Blade/SwordGame/Saves
Infinity Blade II/SwordGame/Cloud
Infinity Blade III/SwordGame/Cloud
```

On exit, changed files from `My Games` are archived under the `infinity-blade`
emulator namespace and stored with that RomM user and game. The rest of the
prefix (Wine registry and installed DirectX/VC++ components) remains local and
persistent. RomM also pulls the broker export if the broker's optional direct
callback cannot reach RomM; a callback warning in WebStation is not by itself
a save failure.

To inspect failures without a desktop:

```bash
docker compose --env-file .env logs --tail=200 romm-webstation
tail -n 200 /srv/emulator/webstation/infinity-blade/wine.log
docker compose --env-file .env exec -T romm-webstation wine --version
```

Do not delete the prefix while a session is active. Normal NAS asset backups
already cover the RomM save archives; include `/srv/emulator/webstation` in
the local application-state backup if retaining the configured Wine runtime
without rebuilding it matters.

## Validation status

As of 2026-10-12, Box has the derived image, registered broker backend,
initialized mixed 32/64-bit Wine prefix, VC++ 2010, and DirectX 9 runtime. RomM
loads the `Windows -> win -> infinity-blade` mapping and its normal health
checks pass. No Infinity Blade game files were present on Box or Sophia, so an
actual game executable, rendering, audio, mouse/touch combat, and real save
round trip have **not** been validated. After supplying the files, test IB1
first, exit after an in-game save, launch it again, and confirm the restored
progress before adding IB2 and IB3.
