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
    && rm -rf /var/lib/apt/lists/*
