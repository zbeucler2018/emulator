# Setup

## Prerequisites

Use an Ubuntu application host with Docker Engine + Compose, Tailscale, `rsync`, `curl`, and `util-linux` installed. The host must already be joined to the intended tailnet.

## 1. Mount the local game disk

The dedicated ext4 disk is mounted at `/mnt/games`; this deployment uses the
copied Sophia tree below it:

```text
/mnt/games/Sophia/games/
  .emulator-nas-marker
  <platform>/
  saves/romm-assets/
  backups/romm-assets/
```

The marker is a deliberate, non-secret sentinel copied with the library. Its
absence makes the deployment refuse to start.

Mount the filesystem by UUID so reconnecting another USB/SATA device cannot
change which disk backs the library:

```fstab
UUID=eb6fa217-103b-415e-b16d-f97143f90c7a /mnt/games ext4 defaults,nofail 0 2
```

Mount it and prove the check passes:

```bash
sudo systemctl daemon-reload
sudo mount /mnt/games
findmnt -T /mnt/games
```

The deployment user must be able to write the RomM asset and backup directories;
game content remains read-only inside the application containers.

## 2. Configure the application

```bash
cd /home/service/repos/emulator
cp .env.example .env
chmod 600 .env
```

Set `ROMM_BASE_URL` to the tailnet URL that Tailscale Serve reports. Generate unique values for the three required secrets; the two MariaDB passwords must be different.

Create the replaceable application-data directory once. Keep it outside the game-library tree:

```bash
sudo install -d -o "$USER" -g "$(id -gn)" -m 0750 /srv/emulator
```

Run the validation and start the services:

```bash
scripts/preflight.sh
docker compose --env-file .env up -d
```

The standard Compose build now creates a thin Wine-enabled derivative of the
pinned WebStation image. This changes no upstream emulator or Selkies package.
To add the separately supplied Infinity Blade ports and initialize their
DirectX/VC++ Wine prefix, follow [Infinity Blade through RomM](infinity-blade.md).

## 3. Publish only inside Tailscale

RomM is deliberately bound to `127.0.0.1:8080`; Webstation is deliberately bound to `127.0.0.1:3010`. Configure the private HTTPS proxy with both routes:

```bash
sudo tailscale serve --https=443 --bg http://127.0.0.1:8080
sudo tailscale serve --https=443 --set-path=/streaming --bg http://127.0.0.1:3010/streaming
sudo tailscale serve status
```

This produces two tailnet-only HTTPS endpoints:

```text
https://<machine>.<tailnet>.ts.net/             -> RomM
https://<machine>.<tailnet>.ts.net/streaming/   -> Webstation/Selkies
```

The `/streaming` handler must proxy to `http://127.0.0.1:3010/streaming`, including the second `/streaming`. Tailscale removes the matched handler path before proxying; omitting it on the backend target makes Webstation receive `/` and display its default nginx welcome page instead of the streamed desktop.

Webstation defaults to Selkies' WebSocket transport, carried through the same
tailnet-only HTTPS route. This avoids a WebRTC late-keyframe failure observed
when Wine replaces Infinity Blade's long-lived splash window with the game.
The existing `TAILSCALE_IPV4` and `SELKIES_WEBRTC_UDP_MUX_PORT` settings keep
the optional WebRTC mux bound only to Box's Tailscale address if that transport
is enabled again; it is never exposed on the LAN or public internet.

Skate 3 keeps a large RPCS3 installation cache at
`dev_hdd0/game/BLUS30464_INSTALL`. WebStation's generic RPCS3 save exporter
would otherwise mistake it for game-save data. The included scoped override
excludes that cache while retaining Skate 3's actual CellSaveData directory
(`BLUS30464-ALIAS_SKATER`) for normal save synchronization.

Do not publish Webstation's container port 3001. RomM 5.3's admin desktop
session uses the same broker claim and tokenized `/streaming/` room as a game
session; a separate desktop URL is neither needed nor protected by RomM's
session ownership.

Put the root URL (without `/streaming`) into `ROMM_BASE_URL` and restart RomM if it changed:

```bash
docker compose --env-file .env up -d romm
```

`tailscale serve` is private to the tailnet. Do **not** substitute `tailscale funnel`, and retain tailnet ACLs for least-privilege access.

### Prometheus scrape for Selkies

Webstation's Selkies server exposes Prometheus text metrics through the already
private streaming handler. No additional host port or Tailscale Serve route is
required. From a Prometheus host that can reach this machine over the tailnet,
configure:

For a direct authenticated Selkies scrape, configure:

```yaml
scrape_configs:
  - job_name: romm-selkies
    scheme: https
    metrics_path: /streaming/stream/api/metrics
    authorization:
      credentials: <value of SELKIES_MASTER_TOKEN from emulator/.env>
    static_configs:
      - targets: ["<machine>.<tailnet>.ts.net"]
```

`SELKIES_MASTER_TOKEN` is a privileged Selkies API credential, so store it in
Prometheus' secret mechanism rather than committing it to a Prometheus config.
The endpoint is unavailable until Webstation has been recreated with
`SELKIES_ENABLE_METRICS_HTTP=true`.

For a Prometheus server that is trusted by your tailnet, the included
`selkies-metrics` sidecar can instead inject the Selkies token privately. Start
it and publish the loopback listener through Tailscale Serve:

```bash
docker compose --env-file .env up -d selkies-metrics
sudo tailscale serve --https=443 --set-path=/metrics --bg http://127.0.0.1:3011/metrics
```

Then Prometheus needs no credential:

```yaml
scrape_configs:
  - job_name: romm-selkies
    scheme: https
    metrics_path: /metrics
    static_configs:
      - targets: ["<machine>.<tailnet>.ts.net"]
```

The proxy's host port must remain bound to `127.0.0.1`, and `/metrics` must
remain a tailnet-only Tailscale Serve route. Do not use Funnel for metrics.

## 4. Configure Webstation from RomM

Sign in with an administrator account and open
`/administration?tab=streaming` (**Administration → Emulator Streaming**).
In the container fleet, select **Desktop** for **Emulation station**. This
claims the same single Webstation display used by games and opens RomM's
`/stream/desktop` view with no game loaded.

Use the **Dolphin Emulator** icon on that desktop. Its launcher and streamed
game sessions both pass through `scripts/dolphin-mii-wrapper.sh`. The wrapper
keeps Dolphin's live database at:

```text
/config/.local/share/dolphin-emu/Wii/shared2/menu/FaceLib/RFL_DB.dat
```

as a hard link to the persistent shared copy at:

```text
/config/.romm-shared/dolphin-wii/RFL_DB.dat
```

On the host that shared copy is
`/srv/emulator/webstation/.romm-shared/dolphin-wii/RFL_DB.dat`. The broker may
still clear and restore `Wii/` before each game, preserving per-user/per-game
save isolation; unlinking the live hard link cannot delete the shared copy.
The wrapper recreates the link immediately before Dolphin starts and syncs an
atomic Dolphin rewrite back after it exits.

## 5. First scan and iPhone test

Open the Tailscale Serve URL from iPhone Chrome, Safari, or Firefox. Create the first RomM account (it is the administrator), then scan the library. Test one GBA game first:

1. Launch it, use the game’s own save feature, and wait for the save-sync indication.
2. Create an explicit state as a convenience snapshot.
3. Close the browser, reopen RomM, select the save, and verify resume.
4. Run `scripts/backup-saves.sh` and verify an asset snapshot appears on the game disk.

Pair a Bluetooth controller in iOS and use EmulatorJS's control settings to confirm the browser Gamepad API mapping. Keep touch controls enabled as the fallback.

## Automated start and backup

The included [systemd unit](../systemd/emulator.service) waits for local filesystems and Tailscale, then runs the configured mount preflight before starting Compose. The preflight verifies the `.env` path, filesystem type and marker before Docker starts. Install it as root after reviewing paths:

```bash
sudo install -m 0644 systemd/emulator.service /etc/systemd/system/emulator.service
sudo systemctl daemon-reload
sudo systemctl enable --now emulator.service
```

Schedule `scripts/backup-saves.sh` using a systemd timer or cron at a cadence appropriate for the save-loss window you accept (hourly is a practical starting point). The backup script retains the newest 20 snapshots by default.
