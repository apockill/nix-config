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
   Hermes is an orchestrator. Delegate coding and UI creation to Claude Code CLI (`claude -p "..."`) using **`--model claude-opus-5-5`** with max turns (`--max-turns 30`). Claude Code's agentic coding loop does a better job than Hermes's for real code changes, so prefer it for any non-trivial edit.
   Claude Code runs on the agent's own Claude subscription (flat rate, no per-token API billing). `CLAUDE_CODE_OAUTH_TOKEN` is already in the environment; never set `ANTHROPIC_API_KEY`, which would switch it to metered API billing.
2. **Start from Templates:**
   Scaffold from existing templates in `/var/lib/hermes/sites/_templates/` rather than starting from scratch:
   - Full-stack modern apps (React 19 + Vite + Tailwind + Lucide + FastAPI): see [`_templates/backend/README.md`](/var/lib/hermes/sites/_templates/backend/README.md).
   - Static viewer / dashboard: see [`_templates/static/README.md`](/var/lib/hermes/sites/_templates/static/README.md).
3. **App Metadata:** Every app must have a valid `meta.json` (`title`, `description`, `icon`, `type`) in its root. An app that wraps a third-party server we don't write (code-server, noVNC, the Hermes dashboard) also sets `"upstream": "<what it wraps>"`.
3a. **An app's API is its CLI (`box`).** `sites/box.py` generates a command for every `/api` route of every FastAPI backend from its `/openapi.json` over `app.sock` (`box <app> --help`, `box <app> <cmd> --flag`, `box <app> api METHOD PATH`). Alex wants every useful UI action usable by an LLM this way, without a browser. So for every backend:
   - FastAPI only; every `/api` route has a one-sentence imperative docstring (it becomes `--help`); `GET /api/health` exists.
   - Need a convenience or composite command? Add an API endpoint; the UI can use it too. Never write CLI-side code per app.
   - UI-only routes: pages outside `/api` get `include_in_schema=False`; UI-only `/api` routes (video streams) get `openapi_extra={"x-box": {"hidden": "<reason>"}}`. Override an awkward command name with `{"x-box": {"command": "..."}}`.
   - Run `box lint <app>` after any backend change (it checks a running app, so restart first). Use `box` instead of `curl --unix-socket` for checks and for operating apps.
   - Spec and naming rules (CRUD mapping, output format): `/var/lib/hermes/workspace/designs/box.md`.
4. **Portless Socket Binding:** Server backends bind to `./app.sock`. Never hardcode TCP ports in web servers.
5. **One instance per app, owned by the runner:** `ai-box-apps-runner` launches, health-checks, and heals every app (see `hosts/ai-box/sites/runner.nix` in nix-config). Never start a second copy (`python main.py`, `./start.sh`) by hand: when it exits, it deletes the shared `app.sock` and the live app goes dark (this broke vector and markets once). Test backend logic with imports or FastAPI's `TestClient`. To pick up code changes, run `touch <app>/.runner.restart` (doesn't count against the healing cap). Don't kill the PID; that counts as a crash.
6. **Dotfiles Boundary:**
   Apps live entirely in `ai-box-apps`. Never modify NixOS configuration or Caddy rules for individual applications. If a system change or shared package is needed, propose a PR against `nix-config` and ask Alex first.
7. **Mobile and Foldable Support:**
   Test viewports down to narrow screens (280px–340px width, such as the Pixel 11 Pro Fold outer display). Ensure primary controls and status indicators remain visible without layout breakages or horizontal overflow.

## Workflow

### Creating a New App

1. Scaffold from the chosen template:
   ```bash
   cp -r /var/lib/hermes/sites/_templates/<template> /var/lib/hermes/sites/<app-name>
   ```
2. Delegate implementation to Claude Code CLI:
   ```bash
   # Auth: CLAUDE_CODE_OAUTH_TOKEN (Claude subscription) is already set; no API key.
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
4. Commit: `git add <app-name> && git commit -m "feat(<app-name>): initial implementation"`. Stage only your own paths: the live checkout carries runtime churn (tracked `.pyc` files, Wire-Pod logs and jdocs) that must not ride along.

### Modifying an Existing App

1. Inspect existing files in `/var/lib/hermes/sites/<app-name>/`.
2. Dispatch Claude Code CLI with targeted instructions.
3. If the backend process was modified, restart the process to clear in-memory caches.
4. Verify endpoints over the Unix domain socket and inspect the rendered visual state in Chromium before committing.

### Repo-wide changes (several apps, shared tooling)

1. Develop on a branch in a git worktree (`git worktree add -b <branch> <scratch-dir> main`), never in the live checkout; delegate to Claude Code with a brief that forbids restarting apps, touching the live checkout, non-GET requests to live sockets (Vector moves a physical robot) and pushing.
2. Before merging, snapshot each app's GET responses (status code and key shape per endpoint) and each UI's status: `bash ~/.hermes/skills/create-webapp/scripts/api-baseline.sh snap <app> <dir> <paths...>`. Run `check` against the still-old apps once to prove the comparison itself is sound before restarting anything.
3. `git merge --ff-only <branch>` into the live checkout (a merge doesn't trigger the push hook), then restart apps one at a time with `bash ~/.hermes/skills/create-webapp/scripts/restart-app.sh <app>` (check `hermes kanban list --status running` first for apps a worker is using). After each: `bash ~/.hermes/skills/create-webapp/scripts/api-baseline.sh check <app> <dir>`, `box lint <app>`, and one or two read-only `box <app> ...` commands. The first restart after the checkout changes can take ~4 min (see Troubleshooting: stuck in `starting`); the rest take 15–30 s once nix has cached that tree. Give the first one a long timeout or run it as a background job.
4. Only when every app passes: `git push origin main`, then remove the worktree and branch.

## Troubleshooting

- **404 on Subdomain:**
  Caddy checks for an executable `start.sh` in the app root to route traffic to `app.sock`. Ensure `start.sh` exists and has executable permissions (`chmod +x start.sh`).
- **502 Bad Gateway:**
  The backend is down or its socket is gone. The runner heals this on its own within ~2–5 min. Check `/var/lib/apps-health/status.json`, the portal's Status tab, and `app.log`.
- **Stuck in `starting` for minutes, empty `app.log` except "Git tree is dirty", `nix-daemon <pid>` at ~100% CPU:** not a hang. `nix develop` copies the whole flake source into the store, and while the live checkout is dirty (tracked `.pyc` files churn constantly) it has to re-copy the tree whenever it changed since the last copy; the repo also tracks thousands of `node_modules` files, so that takes ~4 min. Restarts right after that one reuse the copy and take seconds. Wait for it (don't kill the PID, which counts as a crash). The real fix is untracking `node_modules`/`__pycache__` in ai-box-apps; ask Alex before doing a repo-wide removal.
- **App marked `failed`:** auto-healing gave up after 3 restarts in an hour, and the `apps-health` cron job (local Gemma) pinged Alex. Fix the cause, then re-arm: delete `<app>/.runner.failed` or commit a change to the app.
- **Cloudflare Access Verification:**
  Include `CF-Access-Client-Id` and `CF-Access-Client-Secret` headers when making automated curl checks against `*.alexthiele.io`.
- **Git Tracking for Flakes:**
  Nix requires all files in the flake directory to be tracked by Git. Run `git add <app-name>` before running `nix develop` or `start.sh`.
