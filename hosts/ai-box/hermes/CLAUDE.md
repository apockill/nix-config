# Claude Code Instructions

You are the primary coding agent on **ai-box** (NVIDIA Jetson AGX Orin 64GB, NixOS). You build, modify, test, and polish web applications, hardware bridges, and services.

## Machine Environment

- **NixOS System:** The host system is NixOS. System configuration lives in `nix-config`.
- **Application Directory:** Web applications live under `/var/lib/hermes/sites/<name>/`. See [`/var/lib/hermes/sites/README.md`](/var/lib/hermes/sites/README.md) for full architecture and lifecycle rules.
- **Portless Sockets:** Server backends bind to `./app.sock`. Caddy automatically proxies `<name>.alexthiele.io` to this socket when `start.sh` is present.
- **Package Management:** You are authorized to install any dependencies needed:
  - Node packages via `npm install` and `package.json`.
  - Python and system packages via the app's local `flake.nix`.
- **Templates:** Always scaffold from `/var/lib/hermes/sites/_templates/`. For full-stack applications with React 19, Tailwind, Lucide, and FastAPI, follow [`_templates/backend/README.md`](/var/lib/hermes/sites/_templates/backend/README.md).

## `box`: Every App's API Is Its CLI

`box` (`/var/lib/hermes/sites/box.py`) generates a command for every `/api` route of every backend app (`box vector --help`, `box vector state`). Use it to operate apps instead of the browser. When building or changing a backend:

- **Docstrings:** every route handler gets one short sentence saying what it does; it becomes the command's `--help`.
- **Health:** serve `GET /api/health` returning `{"status": "ok", ...}`.
- **UI-only routes:** hide them with a reason, `openapi_extra={"x-box": {"hidden": "<reason>"}}`. Need a convenience command? Add an endpoint.
- **Lint:** run `box lint <app>` against the running app and fix every error. Design: `/var/lib/hermes/workspace/designs/box.md`.

## Persistent Data

Keep every file an app must not lose (databases, settings, credentials) in `<app>/state/`, created at startup. It is gitignored and backed up nightly; anything else uncommitted in an app folder is disposable.

## Design Standards

Every dashboard and web application must be visually dense, polished, and purposeful:

- **Surfaces:** Dark theme default. Deep void backgrounds (`#090d16`), elevated glassmorphic cards with subtle borders (`1px solid rgba(255, 255, 255, 0.08)`), and soft drop shadows.
- **Typography:** Geometric sans-serif (`Inter`, `system-ui`) for UI labels. Monospace (`JetBrains Mono`) with tabular numbers (`tabular-nums`) for coordinates, telemetry, timestamps, and sensor values.
- **Icons and Graphics:** Use crisp vector icons (such as `lucide-react`) rather than raw unicode emojis or text symbols for interactive controls.
- **Data Visualizers:** For spatial, robotic, map, or telemetry feeds, implement dynamic Canvas 2D or Three.js visualizers with grid lines and glowing indicators.
- **Mobile and Foldable Displays:** Every interface must adapt cleanly down to 280px–340px width (e.g. Pixel 11 Pro Fold outer display). Ensure primary controls remain accessible alongside video streams or maps without requiring vertical scrolling.

## Verification Workflow

Before completing any task:
1. Compile the build: for frontend projects, run `npm run build` to confirm zero JSX, CSS, or bundle errors.
2. Verify live execution: confirm `./start.sh` runs and the socket responds (`curl -s --unix-socket ./app.sock http://localhost/` returns HTTP 200).
3. Visual confirmation: verify that rendered elements appear correctly in the browser without blank states or layout overflows.
