# Recovery

## NAS unavailable

Do not start or restart the stack while `/mnt/games` is missing. `scripts/mount-check.sh` should fail; that is the safe outcome. Restore CIFS connectivity, verify the NAS marker, then start services.

An already-loaded browser game may keep running, but its newer progress is not durable until RomM successfully receives it. Once the NAS is restored, reopen the game and verify the server-side save timestamp before assuming the progress survived.

## Rebuild the application host

1. Reinstall Docker, Compose, Tailscale, SMB client tools, `rsync`, and `curl`.
2. Recreate the root-only SMB credential file and mount `/mnt/games`.
3. Restore this repository and `.env` from a secure backup; do not regenerate `ROMM_AUTH_SECRET_KEY` unless starting a new authentication domain.
4. Restore `/srv/emulator` from its local backup if you need existing accounts, metadata, and artwork. The ROMs and RomM assets already remain on Corsair.
5. Run `scripts/preflight.sh`, start Compose, restore Tailscale Serve, and verify `scripts/health-check.sh`.

If `/srv/emulator` is not recoverable, the NAS still preserves ROMs plus RomM asset files, but the replacement database will not automatically know the old accounts/asset associations. Restore the database whenever possible; this is why the local app data needs its own backup.

## Recover an older save

Save snapshots live at `/mnt/games/backups/romm-assets/snapshots/<UTC timestamp>/`. First stop RomM or ensure the player is not actively syncing. Copy the specific older asset file out of a snapshot to a temporary safe location, then use RomM's save upload UI to import it for the matching ROM and user. This avoids guessing RomM's internal asset identifiers or overwriting a newer active asset directly.

## Upgrade safely

1. Run `scripts/backup-saves.sh` and back up `/srv/emulator`.
2. Pin `ROMM_IMAGE` to the candidate tag/digest in `.env` rather than relying on `latest`.
3. Run `docker compose pull && docker compose up -d`.
4. Test a GBA launch, native save, save-state creation, and reopen/resume flow before considering the upgrade complete.

Avoid changing emulator cores for games whose save states matter. Native `.sav`/`.srm` files are usually portable; states are core-specific.
