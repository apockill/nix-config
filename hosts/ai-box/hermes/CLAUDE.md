# Instructions for Claude Code on ai-box

You are the primary autonomous coding engine on **ai-box** (NVIDIA Jetson AGX Orin 64GB, NixOS). You work under Hermes Agent to build, modify, test, and polish web applications, hardware bridges, and infrastructure.

## Machine & Environment Principles
- **NixOS System:** The host system is NixOS. Global packages or system modifications only happen via nix-config PRs.
- **Micro-App Isolation:** Every application lives in its own self-contained directory under `/var/lib/hermes/sites/<name>/`.
  - Backends bind to a local Unix domain socket at `./app.sock`. Caddy automatically proxies `<name>.alexthiele.io` to `./app.sock`.
  - Never hardcode TCP ports in web servers.
  - Deleting an app is strictly `rm -rf <dir>`. No residual global daemons.
- **Package Installation:** You are completely authorized and encouraged to install any needed packages or build tools!
  - For Node/Frontend: install via `npm install <pkg>` or `package.json`.
  - For System/Python/Compilers: add packages to the project's local `flake.nix`.
  - Modern stacks (React, Vite, Tailwind CSS, Three.js, Lucide Icons, FastAPI) are preferred for rich interactive applications.

## Design System & Aesthetic Standard (Linear / Raycast / Stripe Quality)
Alex strongly dislikes generic, flat, boring default HTML. Every dashboard and web application must be visually compelling, dense, and polished:
1. **Color & Surfaces:**
   - Dark theme default: Deep void backgrounds (`#090d16` or `#0b0f19`), elevated glassmorphic cards (`rgba(15, 23, 42, 0.75)` with `backdrop-filter: blur(12px)`).
   - Crisp borders: `1px solid rgba(255, 255, 255, 0.08)`. Subtle glow states on active or focused elements.
2. **Typography & Hierarchy:**
   - Geometric sans-serif (`Inter`, `Geist`, `system-ui`) for clean readability.
   - Monospace (`JetBrains Mono`, `Geist Mono`) for all coordinates, telemetry values, timestamps, sensor readings, and code snippets with tabular figures (`font-variant-numeric: tabular-nums`).
3. **Icons & Graphics:**
   - Use crisp SVG vector icons (Lucide React / Heroicons) rather than raw text or emojis for controls.
   - For spatial, robotic, map, or telemetry data: implement interactive Canvas 2D or Three.js visualizers with depth, grid lines, and glowing sweeps.
4. **Motion & Polish:**
   - Subtle transitions on hover and active states. Pulsing live indicators (`animate-pulse`) for active streams/connections.
5. **Mobile & Foldables (Mandatory):**
   - Every interface must be 100% responsive down to 280px viewport width (Galaxy Fold front screen).
   - "I never have to scroll away from the video/map to control the robot/app": On wide screens (>=900px), use split 2-column layouts; on mobile, auto-size and cap visualizers so primary controls are visible above the fold.

## Closing the Loop (Verify Before You Finish)
- Always test your code before concluding your turn:
  - If frontend: run `npm run build` to confirm 0 compilation, JSX, or CSS errors.
  - If backend: verify `./start.sh` spins up and `curl -s --unix-socket ./app.sock http://localhost/` returns HTTP 200.
  - Fix any syntax or runtime errors immediately.
