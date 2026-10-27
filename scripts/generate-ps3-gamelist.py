#!/usr/bin/env python3
"""Create RomM's PS3 gamelist.xml from installed-game PARAM.SFO files.

This is deliberately metadata-only: it neither renames nor alters the game
directories.  The expected library shape is PS3/<category>/<game>/..., which
matches the PS3 filesystem rule in config/config.yml.
"""

from __future__ import annotations

import argparse
import os
import struct
import sys
import tempfile
from pathlib import Path
from xml.etree.ElementTree import Element, ElementTree, SubElement, indent


PSF_MAGIC = b"\x00PSF"
PSF_HEADER = struct.Struct("<4sIIII")
PSF_INDEX = struct.Struct("<HHIII")
UTF8_FORMAT = 0x0204

# A few installed titles report a data/DLC label in PARAM.SFO even though the
# directory contains the base game's executable. Entries can also name a
# verified standalone PKG. Keep these presentation-only corrections here; the
# serial and game files are never changed.
TITLE_OVERRIDES = {
    "digital_games/BLUS30464": ("Skate 3", "BLUS30464"),
    "disk_games/Watch_Dogs (USA) (En,Fr,Es,Pt)": ("Watch Dogs", "BLUS31176"),
    # The package's local header names content ID
    # UP0006-NPUB30569_00-DS1HDDNAEFS00001 (Dead Space, US PSN release).
    "digital_games/JpnzMoXYQxLVoDQuYjTLkRaBMTwvKkRUpTPFZPObbAVkNQgBbGqlAMtQmcChmbokRQeHvcnocHDqdrGNpbYVKYpuQXPBSSZurxive.pkg": (
        "Dead Space",
        "NPUB30569",
    ),
    "digital_games/Call of Duty - Black Ops (NPUB30584).pkg": (
        "Call of Duty: Black Ops",
        "NPUB30584",
    ),
}

# Offline presentation metadata for the titles currently verified in this
# library. This is deliberately explicit: folders that are merely PS3 game
# data or updates must never acquire metadata that makes them look launchable.
# All values are local gamelist fields and can be replaced by a configured
# online provider later.
METADATA_OVERRIDES = {
    "BLUS30537": {
        "desc": "Ezio Auditore builds a new Assassin brotherhood in Rome while fighting the Borgia and uncovering another piece of the conflict between Assassins and Templars.",
        "releasedate": "20101116T000000",
        "developer": "Ubisoft Montreal",
        "publisher": "Ubisoft",
        "genre": "Action, Adventure, Stealth",
        "family": "Assassin's Creed",
        "players": "1-8",
    },
    "BLUS30991": {
        "desc": "During the American Revolution, Connor fights for liberty while Desmond's modern-day story brings the conflict between Assassins and Templars toward its conclusion.",
        "releasedate": "20121030T000000",
        "developer": "Ubisoft Montreal",
        "publisher": "Ubisoft",
        "genre": "Action, Adventure, Stealth",
        "family": "Assassin's Creed",
        "players": "1-8",
    },
    "BLUS31176": {
        "desc": "An open-world action-adventure game about hacker Aiden Pearce using Chicago's connected infrastructure to pursue his own agenda.",
        "releasedate": "20140527T000000",
        "developer": "Ubisoft Montreal",
        "publisher": "Ubisoft",
        "genre": "Action, Adventure, Open world",
        "family": "Watch Dogs",
        "players": "1-8",
    },
    "NPUB31254": {
        "desc": "An open-world action-adventure game about hacker Aiden Pearce using Chicago's connected infrastructure to pursue his own agenda.",
        "releasedate": "20140527T000000",
        "developer": "Ubisoft Montreal",
        "publisher": "Ubisoft",
        "genre": "Action, Adventure, Open world",
        "family": "Watch Dogs",
        "players": "1-8",
    },
    "BLUS30721": {
        "desc": "A cinematic action game inspired by Asian mythology, following the demigod Asura on a quest for vengeance.",
        "releasedate": "20120221T000000",
        "developer": "CyberConnect2",
        "publisher": "Capcom",
        "genre": "Action, Hack and slash",
        "family": "Asura's Wrath",
        "players": "1",
    },
    "BLUS30464": {
        "desc": "An open-world skateboarding game set in Port Carverton, built around creating a skate team and completing challenges.",
        "releasedate": "20100511T000000",
        "developer": "EA Black Box",
        "publisher": "Electronic Arts",
        "genre": "Sports, Skateboarding",
        "family": "Skate",
        "players": "1-6",
    },
    "BLUS30089": {
        "desc": "An action-adventure game set during the Third Crusade, following Altaïr Ibn-La'Ahad.",
        "releasedate": "20071113T000000",
        "developer": "Ubisoft Montreal",
        "publisher": "Ubisoft",
        "genre": "Action, Adventure",
        "family": "Assassin's Creed",
        "players": "1",
    },
    "NPUB30742": {
        "desc": "A modern military first-person shooter featuring a cinematic campaign and large-scale multiplayer battles with infantry, vehicles, and destructible environments.",
        "releasedate": "20111025T000000",
        "developer": "DICE",
        "publisher": "Electronic Arts",
        "genre": "Action, First-person shooter",
        "family": "Battlefield",
        "players": "1-24",
    },
    "NPUB30065": {
        "desc": "A high-definition console release of the original Call of Duty campaign, following American, British, and Soviet soldiers across major battles of World War II.",
        "releasedate": "20091203T000000",
        "developer": "Infinity Ward, Aspyr",
        "publisher": "Activision",
        "genre": "Action, First-person shooter, World War II",
        "family": "Call of Duty",
        "players": "1-4",
    },
    "BLUS30838": {
        "desc": "Task Force 141 pursues Vladimir Makarov as a global conflict escalates across New York, London, Paris, and other battlefields.",
        "releasedate": "20111108T000000",
        "developer": "Infinity Ward, Sledgehammer Games",
        "publisher": "Activision",
        "genre": "Action, First-person shooter, Modern military",
        "family": "Call of Duty",
        "players": "1-18",
    },
    "BLUS30072": {
        "desc": "A modern military first-person shooter in which U.S. Marines and British SAS operatives confront an ultranationalist threat across a cinematic campaign.",
        "releasedate": "20071105T000000",
        "developer": "Infinity Ward",
        "publisher": "Activision",
        "genre": "Action, First-person shooter, Modern military",
        "family": "Call of Duty",
        "players": "1-18",
    },
    "BLUS31466": {
        "desc": "A futuristic Call of Duty campaign built around exoskeleton movement and private military conflict, with competitive multiplayer and cooperative Exo Survival.",
        "releasedate": "20141104T000000",
        "developer": "Sledgehammer Games",
        "publisher": "Activision",
        "genre": "Action, First-person shooter, Science fiction",
        "family": "Call of Duty",
        "players": "1-18",
    },
    "BLUS31270": {
        "desc": "After a devastating attack reshapes the United States, an elite unit called the Ghosts fights the technologically superior Federation.",
        "releasedate": "20131105T000000",
        "developer": "Infinity Ward",
        "publisher": "Activision",
        "genre": "Action, First-person shooter, Modern military",
        "family": "Call of Duty",
        "players": "1-18",
    },
    "NPUB30584": {
        "desc": "A Cold War first-person shooter following covert operative Alex Mason through deniable operations, with competitive multiplayer and the series' Zombies mode.",
        "releasedate": "20101109T000000",
        "developer": "Treyarch",
        "publisher": "Activision",
        "genre": "Action, First-person shooter, Cold War",
        "family": "Call of Duty",
        "players": "1-18",
    },
    "BLUS31011": {
        "desc": "A branching near-future campaign connects Cold War operations to a 2025 conflict, accompanied by competitive multiplayer and an expanded Zombies mode.",
        "releasedate": "20121113T000000",
        "developer": "Treyarch",
        "publisher": "Activision",
        "genre": "Action, First-person shooter, Science fiction",
        "family": "Call of Duty",
        "players": "1-18",
    },
    "NPUB31665": {
        "desc": "The PlayStation 3 edition focuses on competitive multiplayer and Zombies, bringing specialists, futuristic movement, and Shadows of Evil to the older console.",
        "releasedate": "20151106T000000",
        "developer": "Treyarch, Beenox, Mercenary Technology",
        "publisher": "Activision",
        "genre": "Action, First-person shooter, Science fiction",
        "family": "Call of Duty",
        "players": "1-18",
    },
    "BLUS30192": {
        "desc": "A World War II first-person shooter covering brutal Pacific and Eastern Front campaigns, with cooperative play, multiplayer, and the debut of Nazi Zombies.",
        "releasedate": "20081111T000000",
        "developer": "Treyarch",
        "publisher": "Activision",
        "genre": "Action, First-person shooter, World War II",
        "family": "Call of Duty",
        "players": "1-18",
    },
    "BLUS31146": {
        "desc": "A third-person action game starring Deadpool, mixing gunplay, melee combat, fourth-wall-breaking humor, and appearances from across the Marvel universe.",
        "releasedate": "20130625T000000",
        "developer": "High Moon Studios",
        "publisher": "Activision",
        "genre": "Action, Hack and slash, Third-person shooter",
        "family": "Marvel",
        "players": "1",
    },
    "BLUS30443": {
        "desc": "A dark action role-playing game set in the fallen kingdom of Boletaria, built around deliberate combat, difficult encounters, and distinctive online interactions.",
        "releasedate": "20091006T000000",
        "developer": "FromSoftware",
        "publisher": "Atlus",
        "genre": "Action, Role-playing, Soulslike",
        "family": "Souls",
        "players": "1-4",
    },
    "NPUB30643": {
        "desc": "A free-to-play online first-person shooter set in the EVE universe. Its battles affected EVE Online, but the official servers closed in May 2016.",
        "releasedate": "20130514T000000",
        "developer": "CCP Shanghai",
        "publisher": "CCP Games",
        "genre": "Action, First-person shooter, MMO, Online-only",
        "family": "EVE",
        "players": "Online multiplayer",
    },
    "NPUB30825": {
        "desc": "An open-world first-person shooter in which Jason Brody explores the Rook Islands, hunts wildlife, captures outposts, and confronts pirate leader Vaas Montenegro.",
        "releasedate": "20121204T000000",
        "developer": "Ubisoft Montreal",
        "publisher": "Ubisoft",
        "genre": "Action, First-person shooter, Open world",
        "family": "Far Cry",
        "players": "1-14",
    },
    "NPUB30702": {
        "desc": "Niko Bellic arrives in Liberty City seeking a new life and is drawn into its criminal underworld in an open-world story of loyalty, violence, and the American dream.",
        "releasedate": "20080429T000000",
        "developer": "Rockstar North",
        "publisher": "Rockstar Games",
        "genre": "Action, Adventure, Open world",
        "family": "Grand Theft Auto",
        "players": "1-16",
    },
    "BLUS30540": {
        "desc": "A family-friendly action-adventure spanning stories from The Clone Wars animated series, with large battles, vehicle missions, character switching, and cooperative play.",
        "releasedate": "20110322T000000",
        "developer": "Traveller's Tales",
        "publisher": "LucasArts",
        "genre": "Action, Adventure, Family",
        "family": "LEGO Star Wars",
        "players": "1-2",
    },
    "BLUS30079": {
        "desc": "A humorous LEGO retelling of all six original Star Wars films, combining platforming, puzzles, collectibles, and drop-in cooperative play.",
        "releasedate": "20071106T000000",
        "developer": "Traveller's Tales",
        "publisher": "LucasArts",
        "genre": "Action, Adventure, Family",
        "family": "LEGO Star Wars",
        "players": "1-2",
    },
    "BLUS30377": {
        "desc": "Task Force 141 hunts Russian ultranationalist Vladimir Makarov in a cinematic modern-warfare campaign, with competitive multiplayer and cooperative Special Ops missions.",
        "releasedate": "20091110T000000",
        "developer": "Infinity Ward",
        "publisher": "Activision",
        "genre": "Action, First-person shooter, Modern military",
        "family": "Call of Duty",
        "players": "1-18",
    },
    "BCUS98242": {
        "desc": "An arcade off-road racing game set during a collapsing city's natural disasters, featuring transforming tracks, aggressive opponents, and split-screen or online racing.",
        "releasedate": "20110503T000000",
        "developer": "Evolution Studios",
        "publisher": "Sony Computer Entertainment",
        "genre": "Racing, Arcade, Off-road",
        "family": "MotorStorm",
        "players": "1-16",
    },
    "BLUS30566": {
        "desc": "A high-speed racing game built around police pursuits, exotic cars, and competing as either a racer or a cop through the connected Autolog system.",
        "releasedate": "20101116T000000",
        "developer": "Criterion Games",
        "publisher": "Electronic Arts",
        "genre": "Racing, Arcade",
        "family": "Need for Speed",
        "players": "1-8",
    },
    "NPUA30073": {
        "desc": "A cooperative first-person shooter built around replayable heists, coordinated objectives, escalating police assaults, and character progression.",
        "releasedate": "20111018T000000",
        "developer": "Overkill Software",
        "publisher": "Sony Online Entertainment",
        "genre": "Action, First-person shooter, Cooperative",
        "family": "Payday",
        "players": "1-4",
    },
    "NPUB31257": {
        "desc": "The leader of the Saints becomes President of the United States and battles an alien invasion inside a virtual Steelport using weapons, vehicles, and superpowers.",
        "releasedate": "20130820T000000",
        "developer": "Volition",
        "publisher": "Deep Silver",
        "genre": "Action, Adventure, Open world",
        "family": "Saints Row",
        "players": "1-2",
    },
    "NPUA80665": {
        "desc": "Master thief Sly Cooper reunites his gang for a globe-spanning series of heists to reclaim the Cooper family vault, mixing stealth, platforming, and playable allies.",
        "releasedate": "20050926T000000",
        "developer": "Sucker Punch Productions",
        "publisher": "Sony Computer Entertainment",
        "genre": "Action, Platformer, Stealth",
        "family": "Sly Cooper",
        "players": "1-2",
    },
    "NPUB30035": {
        "desc": "A physics-driven vehicular soccer game from Psyonix in which rocket-powered cars compete to drive an oversized ball into the opposing goal.",
        "releasedate": "20081009T000000",
        "developer": "Psyonix",
        "publisher": "Psyonix",
        "genre": "Sports, Racing, Vehicular soccer",
        "family": "Rocket League",
        "players": "1-8",
    },
    "BLUS30226": {
        "desc": "An action game set during the War of the Ring, letting players fight large battles as warriors, archers, scouts, and mages on either side of the conflict.",
        "releasedate": "20090113T000000",
        "developer": "Pandemic Studios",
        "publisher": "Electronic Arts",
        "genre": "Action, Fantasy, Hack and slash",
        "family": "The Lord of the Rings",
        "players": "1-16",
    },
    "NPUB30569": {
        "desc": "A survival-horror game aboard the mining ship USG Ishimura, starring engineer Isaac Clarke.",
        "releasedate": "20081014T000000",
        "developer": "EA Redwood Shores",
        "publisher": "Electronic Arts",
        "genre": "Survival horror, Shooter",
        "family": "Dead Space",
        "players": "1",
    },
    "BLES80608": {
        "desc": "multiMAN's compatibility mode: a PlayStation 3 homebrew game and content manager.",
        "developer": "deank",
        "genre": "Utility",
    },
    "NP0APOLLO": {
        "desc": "A PlayStation 3 homebrew save-game manager.",
        "developer": "bucanero",
        "genre": "Utility",
    },
    "NPIA00005": {
        "desc": "Sony's discontinued PlayStation 3 social virtual-world client.",
        "publisher": "Sony Computer Entertainment",
        "genre": "Service",
    },
    "NPIA00025": {
        "desc": "Sony's PlayStation 3 digital-storefront client.",
        "publisher": "Sony Computer Entertainment",
        "genre": "Storefront",
    },
    "NPIA09002": {
        "desc": "Sony's discontinued PlayStation 3 music-streaming client.",
        "publisher": "Sony Computer Entertainment",
        "genre": "Service",
    },
}

# These are sidecar cover assets, never ROM files.  They are kept in a hidden
# directory under the PS3 platform so RomM can ingest them through gamelist.xml
# without turning them into library entries.
COVER_OVERRIDES = {
    "disk_games/AC": ".romm-assets/covers/assassins-creed.jpg",
    "digital_games/Call of Duty - Black Ops (NPUB30584).pkg": ".romm-assets/covers/call-of-duty-black-ops.png",
    "digital_games/JpnzMoXYQxLVoDQuYjTLkRaBMTwvKkRUpTPFZPObbAVkNQgBbGqlAMtQmcChmbokRQeHvcnocHDqdrGNpbYVKYpuQXPBSSZurxive.pkg": ".romm-assets/covers/dead-space.jpg",
    "digital_games/NPUA30073": ".romm-assets/covers/payday-the-heist.jpg",
}

# Two entries do not have a usable PIC1.PNG beside the launchable game. Keep
# their already-owned local artwork inside the hidden PS3 metadata directory.
SCREENSHOT_OVERRIDES = {
    "digital_games/Call of Duty - Black Ops (NPUB30584).pkg": ".romm-assets/screenshots/NPUB30584.png",
    "digital_games/NPUB30065": ".romm-assets/screenshots/NPUB30065.png",
}


def read_sfo(path: Path) -> dict[str, str]:
    """Read UTF-8 string fields from a PS3 PARAM.SFO without external tools."""
    raw = path.read_bytes()
    if len(raw) < PSF_HEADER.size:
        raise ValueError("file is shorter than a PSF header")

    magic, _version, key_offset, data_offset, entries = PSF_HEADER.unpack_from(raw)
    if magic != PSF_MAGIC:
        raise ValueError("not a PSF file")

    values: dict[str, str] = {}
    for index in range(entries):
        offset = PSF_HEADER.size + index * PSF_INDEX.size
        if offset + PSF_INDEX.size > len(raw):
            raise ValueError("truncated PSF index")
        key_rel, value_format, value_len, _value_max_len, value_rel = PSF_INDEX.unpack_from(
            raw, offset
        )
        key_start = key_offset + key_rel
        key_end = raw.find(b"\0", key_start)
        if key_end < key_start:
            continue
        key = raw[key_start:key_end].decode("ascii", errors="ignore")
        if value_format != UTF8_FORMAT or not key:
            continue
        value_start = data_offset + value_rel
        value_end = min(value_start + value_len, len(raw))
        value = raw[value_start:value_end].rstrip(b"\0").decode("utf-8", errors="replace")
        values[key] = " ".join(value.split())
    return values


def boot_file(game_dir: Path) -> Path | None:
    """Return the supported executable for a folder title, if it has one."""
    # Digital RPCS3 installs and decrypted disc dumps use these two layouts.
    # A PARAM.SFO by itself can describe DLC or game-data and is not launchable.
    for candidate in (
        game_dir / "USRDIR" / "EBOOT.BIN",
        game_dir / "PS3_GAME" / "USRDIR" / "EBOOT.BIN",
        game_dir / "EBOOT.BIN",
    ):
        if candidate.is_file():
            return candidate
    return None


def find_games(platform_dir: Path) -> tuple[dict[Path, tuple[str, str]], int]:
    """Map launchable category/game directories to their title and PS3 serial."""
    games: dict[Path, tuple[str, str]] = {}
    metadata_only = 0
    # Do not recursively walk a full PS3 install: it can contain millions of
    # files on a network share. The library shape guarantees a title directory
    # immediately under each category. Digital installs keep PARAM.SFO in that
    # directory; disc dumps commonly place it in PS3_GAME one level below.
    for category_dir in sorted(platform_dir.iterdir()):
        if not category_dir.is_dir():
            continue
        for game_dir in sorted(category_dir.iterdir()):
            if not game_dir.is_dir():
                continue
            relative_game_dir = game_dir.relative_to(platform_dir)
            if boot_file(game_dir) is None:
                # Keep reporting only folders with metadata: unrelated helper
                # directories should not make the report noisy.
                if (game_dir / "PARAM.SFO").is_file() or (
                    game_dir / "PS3_GAME" / "PARAM.SFO"
                ).is_file():
                    metadata_only += 1
                continue
            candidates = (game_dir / "PARAM.SFO", game_dir / "PS3_GAME" / "PARAM.SFO")
            for sfo in candidates:
                if not sfo.is_file():
                    continue
                try:
                    fields = read_sfo(sfo)
                except (OSError, ValueError) as error:
                    print(f"warning: skipped {sfo}: {error}", file=sys.stderr)
                    continue
                title = fields.get("TITLE", "").strip()
                serial = fields.get("TITLE_ID", "").strip()
                if title:
                    title, serial = TITLE_OVERRIDES.get(
                        relative_game_dir.as_posix(), (title, serial)
                    )
                    games[relative_game_dir] = (title, serial)
                    break
    # Packages are valid RPCS3 installers. They have no PARAM.SFO until the
    # first launch installs them, so only explicitly verified package entries
    # belong in the local metadata sidecar.
    for relative_path, metadata in TITLE_OVERRIDES.items():
        path = Path(relative_path)
        if path.suffix.lower() == ".pkg" and (platform_dir / path).is_file():
            games[path] = metadata
    return games, metadata_only


def build_xml(platform_dir: Path, games: dict[Path, tuple[str, str]]) -> ElementTree:
    root = Element("gameList")
    for game_dir, (title, serial) in sorted(games.items(), key=lambda item: item[1][0].casefold()):
        game = SubElement(root, "game")
        SubElement(game, "path").text = f"./{game_dir.as_posix()}"
        SubElement(game, "name").text = title
        SubElement(game, "sortname").text = title
        metadata = METADATA_OVERRIDES.get(serial, {})
        SubElement(game, "desc").text = metadata.get(
            "desc", f"PlayStation 3 title ID: {serial}" if serial else ""
        )
        for field in (
            "releasedate",
            "developer",
            "publisher",
            "family",
            "genre",
            "players",
        ):
            if value := metadata.get(field):
                SubElement(game, field).text = value
        cover_override = COVER_OVERRIDES.get(game_dir.as_posix())
        if cover_override and (platform_dir / cover_override).is_file():
            SubElement(game, "cover").text = f"./{cover_override}"
        else:
            # Prefer the title's own icon as a local, offline cover fallback.
            # Disc dumps keep it in PS3_GAME; installed titles keep it at
            # their root.
            for icon in (
                platform_dir / game_dir / "ICON0.PNG",
                platform_dir / game_dir / "PS3_GAME" / "ICON0.PNG",
            ):
                if icon.is_file():
                    SubElement(game, "cover").text = (
                        f"./{icon.relative_to(platform_dir).as_posix()}"
                    )
                    break
        screenshot_override = SCREENSHOT_OVERRIDES.get(game_dir.as_posix())
        if screenshot_override and (platform_dir / screenshot_override).is_file():
            SubElement(game, "screenshot").text = f"./{screenshot_override}"
            continue
        # PIC1.PNG is the title-provided XMB background and is a useful,
        # authentic gallery image. Prefer only the title-root copy: save-data
        # and nested content can contain unrelated per-level artwork.
        for screenshot in (
            platform_dir / game_dir / "PIC1.PNG",
            platform_dir / game_dir / "PS3_GAME" / "PIC1.PNG",
        ):
            if screenshot.is_file():
                SubElement(game, "screenshot").text = (
                    f"./{screenshot.relative_to(platform_dir).as_posix()}"
                )
                break
    tree = ElementTree(root)
    indent(tree, space="  ")
    return tree


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("platform_dir", type=Path, help="PS3 platform directory")
    parser.add_argument("--output", type=Path, help="defaults to <platform_dir>/gamelist.xml")
    parser.add_argument("--force", action="store_true", help="replace an existing manifest")
    parser.add_argument("--dry-run", action="store_true", help="report entries without writing")
    args = parser.parse_args()

    platform_dir = args.platform_dir.resolve()
    if not platform_dir.is_dir():
        parser.error(f"not a directory: {platform_dir}")
    output = args.output or platform_dir / "gamelist.xml"
    games, metadata_only = find_games(platform_dir)
    if not games:
        print("no titled PARAM.SFO files found", file=sys.stderr)
        return 1

    print(f"found {len(games)} launchable PS3 titles")
    if metadata_only:
        print(f"skipped {metadata_only} metadata-only PS3 folders")
    if args.dry_run:
        for path, (title, serial) in sorted(games.items()):
            print(f"{path}: {title} ({serial or 'no title ID'})")
        return 0
    if output.exists() and not args.force:
        parser.error(f"refusing to overwrite existing {output}; use --force after review")

    tree = build_xml(platform_dir, games)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("wb", dir=output.parent, delete=False) as temp:
        temp_path = Path(temp.name)
        tree.write(temp, encoding="utf-8", xml_declaration=True)
        temp.write(b"\n")
    os.replace(temp_path, output)
    print(f"wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
