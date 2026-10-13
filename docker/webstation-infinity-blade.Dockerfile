ARG WEBSTATION_IMAGE=lscr.io/linuxserver/webstation@sha256:c9d31abdd27a87634d80552283eb2d9aa8d11f1adc29d43618babafa037b927b
FROM ${WEBSTATION_IMAGE}

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
