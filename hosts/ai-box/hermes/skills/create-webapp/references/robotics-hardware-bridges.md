# Robotics & Local Hardware Bridges in Webapps

When building web applications on `ai-box` that communicate with local physical hardware (robots, embedded devices, serial/Bluetooth bridges):

## 1. Single-Directory Isolation for Daemons
- If the hardware requires a dedicated protocol server, daemon, or bridge (e.g. Wire-Pod for Anki Vector, ROS nodes, or serial-to-WebSocket proxies), compile and vendor the daemon directly inside `/var/lib/hermes/sites/<name>/<daemon>/`.
- Launch the daemon from `./start.sh` so that stopping, restarting, or deleting the app directory manages the entire hardware stack in one place with zero orphan daemons.

## 2. Port Binding & Caddy Reverse Proxy
- Embedded devices often hardcode standard ports (e.g. port 80 or 443 with pre-shared TLS certificates like `escapepod.local:443`).
- Unprivileged user accounts cannot bind ports < 1024 directly. Have the internal daemon bind to an unprivileged port (e.g. `8443`), and let host Caddy terminate or reverse-proxy port 443 with the device's TLS certificate.
- Ensure all auxiliary TCP/UDP ports required by the device protocol (e.g. port `8084` for discovery/token exchange) are explicitly allowed in the host firewall (`networking.firewall.allowedTCPPorts`), otherwise connections will silently time out (`i/o timeout`).
- **Heartbeat & Auth Invalidation Trap:** Devices on custom firmware (e.g. Vector on Escape Pod / Wire-Pod) periodically ping `https://escapepod.local:443` for cloud heartbeats. If the 443 reverse proxy drops (e.g. after an untested branch switch), the device's local security daemon invalidates all client session tokens, terminating subsequent RPCs with `StatusCode.UNAUTHENTICATED (401)`. Restore the port 443 proxy with `tls_insecure_skip_verify` to re-validate tokens.

## 3. Local Network Discovery (mDNS)
- Hardware looking for `.local` hostnames relies on mDNS multicast (UDP 5353).
- On NixOS, ensure mDNS aliases are published via Avahi (`environment.etc."avahi/hosts"`) or the Python `zeroconf` package inside the app's flake environment, advertising the host IP on the LAN interface.

## 4. Modern Python Compatibility for Legacy Device SDKs
- Legacy device SDKs (e.g. `anki_vector`) often use older protobuf and asyncio patterns that fail on Python 3.12+:
  - **Protobuf Descriptors:** Export `export PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python` in `./start.sh` if legacy `_pb2.py` files throw `TypeError: Descriptors cannot be created directly`.
  - **Asyncio Event Loop:** `asyncio.Event(loop=...)` was removed in Python 3.12. When vendoring older libraries, replace with `asyncio.Event()`.
  - **Connection Disconnect Handling:** Always wrap hardware disconnect routines (`robot.disconnect()`) in `try ... except Exception: pass`, as background control tasks often throw `CancelledError` during shutdown.
  - **Collections ABC Import Deprecation:** Python 3.10+ removed `collections.Iterable` in favor of `collections.abc.Iterable`. Legacy image annotation or data parsing libraries accessing `collections.Iterable` throw unhandled `AttributeError` on the first frame, silently terminating streaming background tasks. Replace with `collections.abc.Iterable`.
  - **Pillow 10+ Text Measurement:** `ImageDraw.textsize` was removed in Pillow 10.0+. Legacy SDKs overlaying HUD annotations or object labels crash with `AttributeError: 'ImageDraw' object has no attribute 'textsize'`. Replace with `draw.textbbox((0, 0), text, font=font)` to compute width and height (`bbox[2] - bbox[0], bbox[3] - bbox[1]`).

## 5. Charger Hardware Interlocks & Peripheral State
- Wheeled robots (e.g. Vector) lock raw wheel motors while sitting on the charger contacts to prevent driving off charging pins unguided. Driving commands (D-pad, joystick, forward/reverse) received while `on_charger` is true must automatically invoke the robot's undocking behavior (`drive_off_charger`) first before executing wheel motions.
- **Accessory & Peripheral Communication (BLE Cubes):** Physical accessories (e.g. Vector's Light Cube) communicate over Bluetooth Low Energy and enter deep sleep when idle. They require active battery voltage checks (e.g. 1.5V Size N) and physical motion/tap to awaken the BLE radio. Commands requiring accessories (dock, roll, flash lights) will raise `DriverError` if disconnected or if the camera cannot visually locate the object marker; the UI must explicitly reflect connection/visibility status instead of failing silently.
- **Autonomous Play vs. Stationary Quiet Mode:** To keep autonomous robots quiet on their charger or desk for days without spontaneous wander-offs or chirps, maintain reserved behavior control in the driver. Releasing behavior control returns control to the robot's onboard exploration AI for active 'play' mode. Settings for roaming and volume/mute must persist to the app config and local robot jdocs.
- **Firmware Deep Sleep & Wake Controls:** Autonomous companion robots frequently twitch motors, chirp, and shift gaze even while parked unless placed into true dormant sleep. To eliminate ambient fidgeting and battery drain, trigger the robot's native sleep intent (e.g. `intent_system_sleep` via Wire-Pod `/api-sdk/cloud_intent?intent=intent_system_sleep&serial=<esn>`), which instructs firmware to lay the head down, turn off the OLED face display, and power down motor holding torque. Wake by re-acquiring behavior control and commanding a target head pitch (`set_head_angle`). Never wake with Wire-Pod's `explore_start` intent: it is Vector's "Explore" app intent, and once control has been released (always the case after sleep) Vector drives off the charger and free-plays. That combination is what users experience as the robot "going into play mode".
- **Sleep Watchdog & Stream Collision:** When hardware enters dormant sleep, camera sensors stop streaming frames and the device revokes external behavior control. If the backend has a frame watchdog (e.g. `_camera_watch` restarting on stale frames) or the frontend has an automatic stream reconnect loop on 0 FPS, these routines send RPCs that kick the hardware out of sleep. Drivers and UIs MUST maintain an explicit `is_sleeping` flag: suspend camera restart watchdogs and stream polling while sleeping, and display a calm sleep slate.
- **Sleep/Wake Behavior Control Sequencing:** Firmware cannot enter deep sleep if an external client continuously holds behavior control; the driver must explicitly call `conn.release_control()`. When waking, request control first and allow for the request to wait while sleep behaviors exit (time out generously, then retry), rather than kicking the robot with an activation intent.
- **Holding control:** a client that connects at the SDK's default priority and only requests control per command leaves every idle moment to the robot's own behaviors. To keep the robot under the panel's control, hold the control level continuously (reserve it, with a watchdog that re-acquires it when the robot takes it back) and surface the current owner in the UI ("Control: ours / Vector's").
- **Physical Motion Settling Time:** Multi-phase behaviors (e.g. undocking from charging contacts, searching for optical dock markers, or backing onto pins) take 10–20 seconds for the robot's physical motor and sensor loops to complete. Background tasks must not abort early; poll telemetry state flags (`on_charger`, `pose`, `action`) until the maneuver completes and physical displacement is confirmed.

## 6. Closed-Loop Hardware Verification
- Never declare a hardware control action working based solely on HTTP 200 response. Verify every action in closed loops:
  - **Actuator Movement:** Query telemetry before and after (e.g. head angle deg, lift height mm, odometry coordinates) to confirm physical displacement.
  - **Camera Perspective:** Capture snapshot before and after motion and compute cryptographic hashes (MD5/SHA256). Verify hashes differ to prove visual perspective changed.
  - **Docking / Undocking:** Verify state transition (`on_charger` flips `True` <-> `False`, `is_charging` updates).

- **Low light:** Vector's camera is an ordinary color camera with no IR and no illuminator; in a dark room it drops to roughly 4-8 FPS and frames look black. Judge camera health by frame rate and pixel variance rather than content, verify motion with telemetry (pose, wheel speeds, IMU, ToF distance, `on_charger`), and mark vision-only checks "verified by telemetry only, lighting" to redo with light.
- **Robot off the network:** a long run of Sleep/Wake or soak tests can drain the battery or strand the robot off its charger. If ping, ARP and Wire-Pod all lose it, block the task with a request for a human to put it back on the charger; don't keep retrying.

## 7. Desk Network & Smart Devices (Matter)

- The agent controls desk devices only, on its own Matter fabric. Never add whole-home ecosystems (Hue, Kasa, Google Home, SwitchBot). New desk devices should be Matter.
- Keep desk devices on the main home LAN. Google Wifi's guest network isolates guest clients from each other with no setting to disable it, so local protocols (Matter, Vector to Wire-Pod mDNS) break there; its "shared devices" only let guests reach selected main-network devices.
- Matter pairing order: controller running, then Wi-Fi credentials loaded (`set_wifi_credentials`, password piped from 1Password), and only then tell the user to factory-reset the device; the reset opens a pairing window of about 15 minutes. Read the setup code from 1Password via stdin, never argv.
- python-matter-server needs BlueZ (`hardware.bluetooth.enable`), `--bluetooth-adapter 0`, and `AF_BLUETOOTH` in the service's `RestrictAddressFamilies` for BLE pairing.

## 8. Zero-Scroll Dashboard Layout for Robotics
- Rule: "Never scroll away from the video to control the robot."
- Wide screens (>= 900px): Use a split 2-column layout with pinned/sticky video on the left and primary control panels (Drive, Actuators, Behaviors) on the right.
- Mobile / narrow screens: Auto-size and cap video height (max-height: ~38vh, aspect-ratio 16/9) so the D-pad and top controls are visible above the fold on frame 0.
- Inactive or secondary panels (OLED face editor, speech synthesis, settings) must be positioned at the bottom and collapsed by default.
