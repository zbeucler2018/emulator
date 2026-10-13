# Real Wii Remotes through the Mac's BT500

The Mac runs VirtualHere **Server**, with the ASUS USB-BT500 attached. Box
runs the client and connects to the Mac's Tailscale IP, not its public/LAN IP.
Keep the server restricted to trusted clients/Tailscale in the Mac firewall;
the Box-side connection does not itself restrict the Mac server's listeners.
The powered IR bar stays beside the client display and needs only power.
Do not pair the remotes in macOS Bluetooth settings.

## Current test setup

- Mac Tailscale address: `100.101.42.41`, VirtualHere port `7575`.
- Local client: `virtualhere/vhclientx86_64` (not committed).
- Run interactively with sudo and `-e -c` pointing to a local client config.
  The server trial rejected daemon mode (`-n`); this test is not a boot service.
- Client API: `-t 'MANUAL HUB ADD,100.101.42.41:7575'`, then `-t LIST`.
  Use `-t 'USE,<device-address-from-LIST>'` for the BT500 only.
- Compose mounts `/dev/bus/usb` and permits character major 189, without
  privileged mode. It does not hard-code a bus/device number.
- `config/99-webstation-bt500.rules` is installed on Box at
  `/etc/udev/rules.d/99-webstation-bt500.rules`. It grants UID 1000 access only
  to USB ID `0b05:1d70` and reapplies after reconnects.
- Persistent Dolphin config:
  `/srv/emulator/webstation/.config/dolphin-emu/Dolphin.ini`.
  Under `[BluetoothPassthrough]`: `Enabled = True`, `VID = 2821`, `PID = 7536`.
  This explicitly selects ASUS instead of Box's Intel adapter.

## Pair and test

Open Dolphin through RomM's admin streaming desktop. In Controllers, use
Bluetooth passthrough. Start a Wii game, then use Dolphin's passthrough Sync
button and the red SYNC button inside the Wii Remote battery compartment.
Verify buttons, IR pointing and motion before testing accessories or multiple
remotes. A Realtek adapter firmware prompt may appear on first use.

For normal RomM launches, `Hotkeys.ini` in the same persistent config directory
sets `[Hotkeys]`, `Device = XInput2/0/Virtual core pointer` and
`Wii/Press Sync Button = F12`. Dolphin names the combined keyboard/mouse input
after the master pointer, not "Virtual core keyboard". Focus the stream and
press F12 (Fn+F12 if required by macOS), then the remote's red SYNC button.
Existing paired remotes may reconnect with a normal button press instead.
Edit this file only while Dolphin is stopped.

Keep VirtualHere and the Mac awake during play. Network latency/reconnection
and actual Wii Remote input still require hands-on validation. Prefer normal
in-game saves; do not assume passthrough works with emulator save states.

## Ordinary controller fallback

Stop Dolphin first, then select **Emulate the Wii's Bluetooth adapter** in
Controllers (equivalent to `Enabled = False`). Existing emulated Wii Remote
bindings are preserved. Passthrough mode requires the forwarded BT500;
disconnecting it does not automatically switch to the browser controller.

Pre-test config backup:
`/srv/emulator/webstation/.config/dolphin-emu/Dolphin.ini.before-bt500-20261012`.
Do not blindly restore it after pairing, as that would discard new link keys.
