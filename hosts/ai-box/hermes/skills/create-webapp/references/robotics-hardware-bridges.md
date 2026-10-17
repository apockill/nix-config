# Robotics & Local Hardware Bridges in Webapps

Only rules learned from problems actually hit on ai-box (mostly Vector + Wire-Pod). Add a rule here only after hitting the problem.

## Network: Escape Pod / Wire-Pod
- Vector (firmware `2.0.1.6076ep`) looks for `escapepod.local` over mDNS and talks TLS on 443 with the Escape Pod cert. ai-box publishes the alias via Avahi (`environment.etc."avahi/hosts"`) and Caddy serves 443 with that cert (`vector.nix`).
- If the 443 proxy is missing (e.g. after switching to a branch without it), every SDK call fails with `StatusCode.UNAUTHENTICATED` (401). Restore the proxy; don't re-pair.
- Port 8084 must be open to Vector, or the token exchange fails with `dial tcp …:8084: i/o timeout`. Open device ports by source IP (the device's address), not LAN-wide.

## Legacy SDK on modern Python (`anki_vector`)
Each of these broke the vendored SDK:
- `TypeError: Descriptors cannot be created directly` from `_pb2.py`: `export PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python` in `start.sh`.
- `asyncio.Event(loop=...)` (removed in 3.10): use `asyncio.Event()`.
- `collections.Iterable` in `annotate.py`: use `collections.abc.Iterable`. It raised on the first frame and silently killed the camera stream task.
- Pillow 10 removed `ImageDraw.textsize`: use `draw.textbbox((0, 0), text, font=font)`.

## Behavior control, sleep and wake
- A client that only requests control per command leaves every idle moment to Vector's own behaviors, and he wanders off the charger and free-plays. Hold control continuously (reserve it, with a watchdog that re-acquires it when Vector takes it back), and show the owner in the UI.
- Never wake with Wire-Pod's `explore_start` intent: it's the Explore app intent, and since control is released during sleep, Vector drives off and free-plays. Wake by requesting behavior control (allow a generous timeout while sleep behaviors exit), then set a head angle.
- Sleep = `intent_system_sleep` via Wire-Pod plus `release_control()`; firmware can't sleep while a client holds control.
- While asleep the camera stops sending frames. A stale-frame watchdog or a UI reconnect loop on 0 FPS sends RPCs that wake Vector. Keep an `is_sleeping` flag and pause both.
- Long behaviors outlast short timeouts: Return to Charger can search for well over 30 s. Don't expire running commands early, and don't misread motion during them as Vector acting on his own.

## Verifying on hardware
- HTTP 200 proves nothing. Check telemetry before and after (head angle, lift, pose, `on_charger`). The panel once showed a 0 FPS feed whose frame stayed identical while the head moved 55°, so compare frames, not just their presence.
- Vector's camera has no IR or illuminator; in a dark room it drops to ~4-12 FPS with near-black frames. Judge camera health by frame rate and pixel variance, verify motion by telemetry, and mark vision checks "telemetry only, lighting" to redo in light.

## Matter desk devices (`sites/matter`, matter.js server)
- Bluetooth pairing runs without root: start the matter.js server with `--ble-proxy` and connect the Bleak-based `matter-ble-proxy` (PyPI; deps `bleak`, `aiohttp`) to its `/ble` WebSocket as hermes. BlueZ's shipped D-Bus policy lets any user talk to `org.bluez`, so the host needs only `hardware.bluetooth.enable` (plus `/var/lib/bluetooth` declared `host`). The server's own noble mode would need `CAP_NET_RAW`/`CAP_NET_ADMIN`.
- Run the server with `MATTER_STORAGE_DRIVER=file`. The default `wal` driver writes `set_wifi_credentials` in plain text to `config/wal/*.jsonl`, and `remove_wifi_credentials` only appends a delete, so the password stays in the backed-up fabric dir forever. With `file`, removal deletes `config/values.wifiCredentials`. Switching drivers migrates the store in place (the plug stays paired) but keeps the old wal under `.migrations/`; delete that.
- Pairing a reset device: have the server, proxy and pairing command ready before the user factory-resets it (the BLE window is short). Send `set_wifi_credentials`, then `commission_with_code` (takes about a minute over BLE), then remove the credentials. Read the setup code and Wi-Fi password from 1Password by item ID inside the process, never via argv.
- Match a device kind by the presence of its device type on an endpoint, not the exact list: the Kasa plug's endpoint 1 is On/Off Plug-in Unit (0x010A) *and* Electrical Sensor (0x0510).
- Verify switching by reading the On/Off attribute back (`1/6/0`) and with Vector's camera, sampling the frame's mean brightness (`ImageStat` on a `box vector camera snapshot`) **about 2 s after switching**: auto-exposure compensates within ~30 s, so a frame taken after a 15 s hold barely differs (on ≈132, off ≈126) while a quick one is unmistakable (off drops ≈126 → ≈49). If in doubt, look at the frames: with the light on, the wall and desk blow out to white. Do both directions twice, then restart the server and switch again to prove the fabric persists.

## Dashboard layout (Alex's rule)
- "Never scroll away from the video to control the robot." ≥900 px: video pinned left, Drive/Actuators/Behaviors right. Narrow: cap the video (~38vh, 16:9) so the D-pad shows without scrolling; secondary panels (face, speech, settings) at the bottom, collapsed.
