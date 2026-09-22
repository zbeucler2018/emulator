# Setup

## Prerequisites

Use an Ubuntu application host with Docker Engine + Compose, Tailscale, `cifs-utils`, `rsync`, `curl`, and `util-linux` installed. The host must already be joined to the intended tailnet.

## 1. Mount the Corsair share

Create the NAS share and directories once on Corsair:

```text
games/
  .emulator-nas-marker
  roms/
  saves/romm-assets/
  backups/romm-assets/
```

The marker is a deliberate, non-secret sentinel. Do not create it on the application host. Its absence makes the deployment refuse to start.

On Ubuntu, create a root-only credentials file such as `/etc/samba/credentials/corsair-games`:

```ini
username=YOUR_SAMBA_USER
password=YOUR_SAMBA_PASSWORD
domain=WORKGROUP
```

Set its mode to `0600`, then add a CIFS entry like this to `/etc/fstab` (replace host/share values):

```fstab
//corsair/games /mnt/games cifs credentials=/etc/samba/credentials/corsair-games,_netdev,x-systemd.automount,x-systemd.requires=network-online.target,uid=1000,gid=1000,file_mode=0660,dir_mode=0770,vers=3.0 0 0
```

Mount it and prove the check passes:

```bash
sudo systemctl daemon-reload
sudo mount /mnt/games
findmnt -T /mnt/games
```

Use the actual Docker-running user's UID/GID for the mount options if they differ. Do not put a Samba password into `/etc/fstab`, `.env`, or Git.

## 2. Configure the application

```bash
cd /home/service/repos/emulator
cp .env.example .env
chmod 600 .env
```

Set `ROMM_BASE_URL` to the tailnet URL that Tailscale Serve reports. Generate unique values for the three required secrets; the two MariaDB passwords must be different.

Create the replaceable, local application-data directory once. This must be on the Ubuntu host's local filesystem, not the NAS mount:

```bash
sudo install -d -o "$USER" -g "$(id -gn)" -m 0750 /srv/emulator
```

Run the validation and start the services:

```bash
scripts/preflight.sh
docker compose --env-file .env up -d
```

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

Put the root URL (without `/streaming`) into `ROMM_BASE_URL` and restart RomM if it changed:

```bash
docker compose --env-file .env up -d romm
```

`tailscale serve` is private to the tailnet. Do **not** substitute `tailscale funnel`, and retain tailnet ACLs for least-privilege access.

## 4. First scan and iPhone test

Open the Tailscale Serve URL from iPhone Chrome, Safari, or Firefox. Create the first RomM account (it is the administrator), then scan the library. Test one GBA game first:

1. Launch it, use the game’s own save feature, and wait for the save-sync indication.
2. Create an explicit state as a convenience snapshot.
3. Close the browser, reopen RomM, select the save, and verify resume.
4. Run `scripts/backup-saves.sh` and verify an asset snapshot appears on Corsair.

Pair a Bluetooth controller in iOS and use EmulatorJS's control settings to confirm the browser Gamepad API mapping. Keep touch controls enabled as the fallback.

## Automated start and backup

The included [systemd unit](../systemd/emulator.service) waits for remote filesystems and Tailscale, then runs the configured mount preflight before starting Compose. This keeps it compatible with the `.env` mount path rather than hard-coding a particular NAS location. Install it as root after reviewing paths:

```bash
sudo install -m 0644 systemd/emulator.service /etc/systemd/system/emulator.service
sudo systemctl daemon-reload
sudo systemctl enable --now emulator.service
```

Schedule `scripts/backup-saves.sh` using a systemd timer or cron at a cadence appropriate for the save-loss window you accept (hourly is a practical starting point). The backup script retains the newest 20 snapshots by default.
