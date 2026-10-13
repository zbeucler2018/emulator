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
    Binaries/Win64/IB3.exe
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

The script builds the derived WebStation image, refreshes a Box-side runtime
cache from the canonical copies on Sophia, recreates WebStation (and runs the
existing one-shot mount guard), creates
`/srv/emulator/webstation/infinity-blade/prefix`, and installs the documented
Visual C++ 2010 and DirectX 9 helper libraries with Winetricks. It does not
fetch a game. The cache lives at
`/srv/emulator/webstation/infinity-blade/game-cache` and avoids UE3's hundreds
of thousands of small startup reads crossing the NAS; saves remain in RomM
and the Wine prefix, not in that cache. Re-run the setup script after replacing
a port with a newer release. Re-running it is safe; remove only the marker
`/srv/emulator/webstation/infinity-blade/prefix/.infinity-blade-runtime-ready`
if the runtime installation genuinely needs to be repeated.

In RomM, run a quick scan or scan the Windows platform. The `Windows: win`
binding makes the three directories separate Windows games, and the
`win: infinity-blade` streaming mapping adds **Wine** to each
game's Play actions.

## Playing

Open a game in RomM and choose **Wine**. WebStation starts
the known game executable through Wine and RomM opens the existing tokenized
Selkies stream. Use **Save & Quit** or the stream's normal exit control before
leaving when possible; this lets the broker stop Wine, archive changed files,
and let RomM collect them.

WebStation is intentionally locked to a 1280x720 virtual desktop. Mobile
Safari otherwise asks Selkies to resize the compositor to its CSS viewport
(390x668 was observed on an iPhone), which is below Infinity Blade's minimum
and produces a `The current resolution is too low to run this game` dialog.
Selkies scales the fixed canvas to each browser, so this lock does not prevent
desktop or mobile clients from fitting the stream to their screens.

Selkies defaults to its WebSocket transport and continuous video mode. In the
WebRTC transport, the encoder could stay pinned to the all-black GOP captured
while Wine replaced the loading splash even though the live Xwayland display
was already rendering gameplay. WebSockets retains Selkies, NVIDIA encoding,
audio, and browser input while avoiding that late-frame recovery failure.

IB1's small splash is a loading window, not a launcher. Leave it open: it
closes itself when the main window is ready, and closing it manually can
interrupt initialization. The Box-side cache reduced a clean tested launch
from several NAS-bound minutes to roughly 20 seconds.

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

IB3 is launched with UE3's `1280x720` fullscreen flags. Its v1.0.0 DX9 build
still creates a smaller decorated Wine parent during the opening movie, so a
scoped labwc rule puts the mapped `ib3.exe` window into compositor fullscreen.
The same rule covers `ib1.exe` and `ib2.exe`. This avoids rewriting the ports'
generated INIs, which made IB3's startup movie black, while filling the locked
1280x720 Selkies canvas without borders or desktop background.

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

On exit, files from `My Games` are archived under the `infinity-blade`
emulator namespace and stored with that RomM user and game. The launcher moves
the restored tree's mtimes past WebStation's launch baseline so each archive is
a complete, independently restorable snapshot instead of a delta that depends
on an older ZIP. The rest of the prefix (Wine registry and installed
DirectX/VC++ components) remains local and persistent. RomM also pulls the
broker export if the broker's optional direct callback cannot reach RomM; a
callback warning in WebStation is not by itself a save failure.

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

## RomM metadata

The three RomM records use their original iOS release dates, ChAIR/Epic
developer and publisher credits, single-player mode, action-RPG genres, age
ratings, community-port versions, MobyGames IDs, English/worldwide tags, and
locally cached cover files. Descriptions and dates are based on Epic's
[IB1](https://www.epicgames.com/infinityblade/en-US/game-info/infinity-blade-i),
[IB2](https://www.epicgames.com/infinityblade/en-US/game-info/infinity-blade-ii),
and [IB3](https://www.epicgames.com/infinityblade/en-US/game-info/infinity-blade-iii)
pages. Cover provenance is the title's published promotional art; RomM keeps
its own copies under `/srv/emulator/resources/roms/17/<rom-id>/cover` so the
library does not depend on a remote image remaining available.

## Validation status

As of 2026-10-13, all three supplied packages are installed on Sophia and
appear as separate Windows games in RomM. Box has the derived image,
registered broker backend, initialized mixed 32/64-bit Wine prefix, VC++ 2010,
and DirectX 9 runtime. The tests below used RomM's authenticated
`/api/streaming/sessions` path, the RomM-issued Selkies URL, and RomM's own
Save & Quit path rather than calling the broker directly. The normal repository
health check passes.

- IB1: the real cached `IB1.exe` rendered combat in about 20 seconds, produced
  browser audio, and accepted a desktop mouse drag. RomM collected a complete
  10-file save ZIP, then restored all 10 payload files with zero failures on a
  second launch that rendered correctly. Its compositor window was verified at
  1280x720 with `_NET_WM_STATE_FULLSCREEN`. A clean diagnostic also proved that
  gameplay was live in Xwayland while WebRTC still displayed its initial black
  frame; the deployment now defaults to WebSockets.
- IB2: the real cached `IB2.exe` rendered gameplay in about 20 seconds,
  produced browser audio, and accepted a desktop mouse drag. RomM collected a
  complete 15-file save ZIP, restored all 15 payload files with zero failures,
  and rendered the game again. Its compositor window was also verified at
  1280x720 with `_NET_WM_STATE_FULLSCREEN`.
- IB3: the real cached `IB3.exe` showed the unambiguous `Infinity Blade III
  (64-bit, DX9)` title and animated opening through Selkies in about 20 seconds
  with audio active. RomM collected a complete 24-file save snapshot and
  restored all 24 payload files with zero failures; the restored launch again
  rendered the animated opening with audio. Its compositor window filled the
  1280x720 stream in fullscreen without making the movie black. The full
  opening and touchscreen combat have not yet been played through.
- Selkies' deployed touch path was inspected and covers tap, held drag,
  direction-preserving swipe, release, long press, two-finger scrolling,
  letterbox-aware coordinate scaling, and `preventDefault` on mobile touch
  events. A physical iPhone/iPad combat session remains the final device-side
  validation; desktop mouse combat is verified.
