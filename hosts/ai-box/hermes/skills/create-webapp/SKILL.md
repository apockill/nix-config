---
name: create-webapp
description: "Use when creating, modifying, deploying, or debugging web apps and dashboards on ai-box."
version: 1.0.0
author: Alex Thiele + Hermes Agent
platforms: [linux]
---

# Creating and Modifying Webapps on ai-box

This skill outlines the lifecycle, delegation patterns, and verification standards for web applications hosted on `ai-box` (`*.alexthiele.io`).

## Architecture

- **Repository:** All apps live in the private repository [`ailex-agent/ai-box-apps`](https://github.com/ailex-agent/ai-box-apps), cloned locally to `/var/lib/hermes/sites/`.
- **Dynamic Routing:** Caddy serves `/var/lib/hermes/sites/<name>` at `https://<name>.alexthiele.io` dynamically. When an executable `start.sh` is present, traffic routes to `./app.sock`. No custom Caddy configuration or Nix rebuilds are required.
- **Root Portal:** `https://alexthiele.io` / `https://portal.alexthiele.io` dynamically scans all app directories and renders the catalog.
- **Single-Directory Isolation:** Every project is self-contained. Deleting an app is strictly `rm -rf /var/lib/hermes/sites/<name>`.
- **Automatic Sync:** A git post-commit hook automatically pushes commits to `origin/main`.

## Verification and Quality Standard

- **Atomic Verified Commits:** 1 commit in `ai-box-apps` = 1 fully verified, functioning change. Never commit code before proving it works live.
- **Visual Verification Gate:** Always inspect the rendered page visually using `vision_analyze` and capture a screenshot (`MEDIA:/var/lib/hermes/.hermes/browser_screenshots/<app>.png`). Do not rely solely on DOM queries or HTTP status codes—DOM elements can be present in the tree while visually blank, clipped, or occluded.
- **Reporting Gate:** Never report an app or feature as complete until verified end-to-end with high confidence.

## Core Rules

1. **Delegate Coding to Claude Code CLI:**
   Hermes is an orchestrator. Delegate coding and UI creation to Claude Code CLI (`claude -p "..."`) using **`--model claude-opus-5-5`** with max turns (`--max-turns 30`).
2. **Start from Templates:**
   Scaffold from existing templates in `/var/lib/hermes/sites/_templates/` rather than starting from scratch:
   - Full-stack modern apps (React 19 + Vite + Tailwind + Lucide + FastAPI): see [`_templates/backend/README.md`](/var/lib/hermes/sites/_templates/backend/README.md).
   - Static viewer / dashboard: see [`_templates/static/README.md`](/var/lib/hermes/sites/_templates/static/README.md).
3. **App Metadata:** Every app must have a valid `meta.json` (`title`, `description`, `icon`, `type`) in its root.
4. **Portless Socket Binding:** Server backends bind to `./app.sock`. Never hardcode TCP ports in web servers.
5. **Dotfiles Boundary:**
   Apps live entirely in `ai-box-apps`. Never modify NixOS configuration or Caddy rules for individual applications. If a system change or shared package is needed, propose a PR against `nix-config` and ask Alex first.
6. **Mobile and Foldable Support:**
   Test viewports down to narrow screens (280px–340px width, such as the Pixel 11 Pro Fold outer display). Ensure primary controls and status indicators remain visible without layout breakages or horizontal overflow.

## Workflow

### Creating a New App

1. Scaffold from the chosen template:
   ```bash
   cp -r /var/lib/hermes/sites/_templates/<template> /var/lib/hermes/sites/<app-name>
   ```
2. Delegate implementation to Claude Code CLI:
   ```bash
   TOKEN=$(op item get "Claude" --vault ai-assistant --fields label=oauth_token --reveal)
   export CLAUDE_CODE_OAUTH_TOKEN="$TOKEN"
   cd /var/lib/hermes/sites/<app-name>

   claude -p "Your detailed prompt describing requirements..." \
     --model claude-opus-5-5 \
     --allowedTools "Read,Edit,Write,Bash" \
     --max-turns 30
   ```
3. Verify live operation:
   - For backends: verify `./start.sh` starts and `curl -s --unix-socket ./app.sock http://localhost/` returns 200.
   - For public routing: test over Cloudflare Access with service tokens.
   - For visuals: navigate Chromium via CDP, capture screenshot, and verify layout with `vision_analyze`.
4. Commit: `git add <app-name> && git commit -m "feat(<app-name>): initial implementation"`.

### Modifying an Existing App

1. Inspect existing files in `/var/lib/hermes/sites/<app-name>/`.
2. Dispatch Claude Code CLI with targeted instructions.
3. If the backend process was modified, restart the process to clear in-memory caches.
4. Verify endpoints over the Unix domain socket and inspect the rendered visual state in Chromium before committing.

## Troubleshooting

- **404 on Subdomain:**
  Caddy checks for an executable `start.sh` in the app root to route traffic to `app.sock`. Ensure `start.sh` exists and has executable permissions (`chmod +x start.sh`).
- **502 Bad Gateway:**
  The backend server exited or crashed on startup. Inspect `app.log` in the app directory for Python or Node tracebacks.
- **Cloudflare Access Verification:**
  Include `CF-Access-Client-Id` and `CF-Access-Client-Secret` headers when making automated curl checks against `*.alexthiele.io`.
- **Git Tracking for Flakes:**
  Nix requires all files in the flake directory to be tracked by Git. Run `git add <app-name>` before running `nix develop` or `start.sh`.
