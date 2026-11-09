ARG WEBSTATION_IMAGE=lscr.io/linuxserver/webstation@sha256:eec9b7bb0571da05534daa08edde5ccf0e212a635794f29ea5f39f1c70a7ffb5
FROM ${WEBSTATION_IMAGE}

# Battlefield 3/4 currently expose an RPCS3 main-memory tiling bug as displaced
# tiles, bands, and mosaic-like corruption during gameplay.  Use the successful
# Linux x86-64 CI artifact from the exact experimental RPCS3 commit below.  The
# artifact is fetched through nightly.link because GitHub requires an API token
# for direct Actions-artifact downloads; its bytes are still verified against
# the SHA-256 digest published by GitHub for artifact 13576025915.
#
# Upstream PR: https://github.com/RPCS3/rpcs3/pull/19785
# Head commit: 8cb131662a1dabb4b7086a771ee4730e461efa5b
ARG RPCS3_BATTLEFIELD_ARTIFACT_URL=https://nightly.link/RPCS3/rpcs3/actions/artifacts/13576025915.zip
ARG RPCS3_BATTLEFIELD_ARTIFACT_SHA256=4d0b426248d1014268cb3c78ce879ce45a00e4468fa251cd072d180652ed17af
ARG RPCS3_BATTLEFIELD_APPIMAGE=rpcs3-v0.0.43-20572-3aa5b10e_linux64.AppImage
RUN set -eux; \
    work_dir=/tmp/rpcs3-battlefield; \
    artifact="$work_dir/artifact.zip"; \
    mkdir -p "$work_dir"; \
    curl -fsSL -o "$artifact" "$RPCS3_BATTLEFIELD_ARTIFACT_URL"; \
    echo "$RPCS3_BATTLEFIELD_ARTIFACT_SHA256  $artifact" | sha256sum -c -; \
    unzip -q "$artifact" -d "$work_dir"; \
    test -f "$work_dir/$RPCS3_BATTLEFIELD_APPIMAGE"; \
    chmod +x "$work_dir/$RPCS3_BATTLEFIELD_APPIMAGE"; \
    cd "$work_dir"; \
    "./$RPCS3_BATTLEFIELD_APPIMAGE" --appimage-extract >/dev/null; \
    test "$(readlink squashfs-root)" = "./AppDir"; \
    test -x AppDir/usr/bin/rpcs3; \
    rm -rf /opt/rpcs3; \
    mv AppDir /opt/rpcs3; \
    rm -rf "$work_dir"

# Selkies 2.1 natively maps a token's ordered slot list to that page's local
# Gamepad API devices. WebStation Broker PR #134 exposes that support in its
# room and token model; pin the exact upstream commit rebased onto v0.15.3.
# The one local policy below gives the host slots 1 and 2 by default, so couch
# co-op works through ordinary Play without first opening the multiplayer UI.
ARG ROMM_BROKER_MULTISLOT_COMMIT=cc7a86415d8bc7b2008d9dc2bb449c08df4f3ad4
ARG ROMM_BROKER_MULTISLOT_SHA256=2dc366a433db9efd6704bcab9aec8cd323e359307164a350cb0cdacf79d32792
RUN set -eux; \
    test "$(/lsiopy/bin/python3 -c 'import importlib.metadata as m; print(m.version("webstation-broker"))')" = "0.15.3"; \
    source_dir=/tmp/romm-broker-multislot; \
    archive=/tmp/romm-broker-multislot.tar.gz; \
    curl -fsSL -o "$archive" \
        "https://github.com/romm-streaming/romm-broker/archive/${ROMM_BROKER_MULTISLOT_COMMIT}.tar.gz"; \
    echo "${ROMM_BROKER_MULTISLOT_SHA256}  $archive" | sha256sum -c -; \
    mkdir -p "$source_dir"; \
    tar -xzf "$archive" --strip-components=1 -C "$source_dir"; \
    /lsiopy/bin/python3 - "$source_dir/webstation_broker/session.py" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text()
old = '        "controller_slot": 1,\n'
new = '        "controller_slot": [1, 2],\n'
if text.count(old) != 1:
    raise SystemExit(f"expected one upstream controller-slot default in {path}")
path.write_text(text.replace(old, new))
PY
RUN set -eux; \
    source_dir=/tmp/romm-broker-multislot; \
    cd "$source_dir/frontend"; \
    npm ci --no-audit --no-fund; \
    npm test; \
    npm run build; \
    install -m 0644 "$source_dir/webstation_broker/session.py" \
        /lsiopy/lib/python3.14/site-packages/webstation_broker/session.py; \
    install -m 0644 "$source_dir/webstation_broker/room.py" \
        /lsiopy/lib/python3.14/site-packages/webstation_broker/room.py; \
    rm -rf /usr/share/webstation-broker/www; \
    install -d /usr/share/webstation-broker/www; \
    cp -a "$source_dir/frontend/dist/." /usr/share/webstation-broker/www/; \
    rm -rf "$source_dir" /tmp/romm-broker-multislot.tar.gz

# Infinity Blade's community PC ports are Windows applications. Keep the
# upstream WebStation image intact and add only Wine plus the small tools used
# by the one-time runtime setup script. Both architectures are installed
# because IB1 is 64-bit while IB2's documented direct executable is Win32.
RUN dpkg --add-architecture i386 \
    && apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install --no-install-recommends -y \
        cabextract \
        winbind \
        wine \
        wine32:i386 \
        wine64 \
        winetricks \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* \
    # WebStation's base image owns this directory with its build-time UID.
    # A configured PUID changes the abc account at runtime, causing wlroots to
    # reject the directory and preventing labwc/Xwayland (and Wine) starting.
    && install -d -o root -g root -m 1777 /tmp/.X11-unix

# WebStation regenerates labwc's user configuration from this template on
# every container start. Match only the three known Wine executables and put
# their normal game windows into compositor fullscreen as soon as they map.
# This fills Selkies' locked 1280x720 canvas without teaching the individual
# ports about browser dimensions or resizing their renderers after startup.
RUN sed -i '/<\/windowRules>/i\    <windowRule identifier="ib?.exe" type="normal" serverDecoration="no">\n      <action name="ToggleFullscreen" />\n    </windowRule>' \
        /defaults/labwc.xml
