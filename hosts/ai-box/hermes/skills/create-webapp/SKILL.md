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
- **Dynamic Routing:** Caddy serves each running instance at `https://<address>.alexthiele.io` from its socket, `/run/sites/<address>/app.sock`, and a static app's files from `/var/lib/hermes/sites/apps/<name>`. An instance is declared in `/var/lib/hermes/sites/namespaces/<namespace>.yaml` (today's apps in `default.yaml`, named after their app); the apps runner (`box ns ...`) runs it under process-compose. No custom Caddy configuration or Nix rebuilds are required.
- **Root Portal:** `https://alexthiele.io` / `https://portal.alexthiele.io` dynamically scans all app directories and renders the catalog.
- **Single-Directory Isolation:** An app's code is self-contained in `apps/<name>`; its instances' state lives in `/var/lib/hermes/instances/<address>/` (`$SITES_STATE_DIR`). Deleting an app: drop its namespace entries, `rm -rf apps/<name>`, `box ns destroy <address>` for its state.
- **Pushing:** nothing pushes on its own; after committing to `main`, `git pull --ff-only` then `git push origin main` (the pre-push hook refuses commits that touch the spec's parts: those go through `box change`).

## Verification and Quality Standard

- **Atomic Verified Commits:** 1 commit in `ai-box-apps` = 1 fully verified, functioning change. Never commit code before proving it works live.
- **Visual Verification Gate:** Always inspect the rendered page visually using `vision_analyze` and capture a screenshot (`MEDIA:/var/lib/hermes/.hermes/browser_screenshots/<app>.png`). Do not rely solely on DOM queries or HTTP status codes—DOM elements can be present in the tree while visually blank, clipped, or occluded.
- **Reporting Gate:** Never report an app or feature as complete until verified end-to-end with high confidence.

## Core Rules

1. **Delegate Coding to Claude Code CLI:**
   Hermes is an orchestrator. Delegate coding and UI creation to Claude Code CLI (`claude -p "..."`) using **`--model claude-opus-5-5`** with max turns (`--max-turns 30`). Claude Code's agentic coding loop does a better job than Hermes's for real code changes, so prefer it for any non-trivial edit.
   Claude Code runs on the agent's own Claude subscription (flat rate, no per-token API billing). `CLAUDE_CODE_OAUTH_TOKEN` is already in the environment; never set `ANTHROPIC_API_KEY`, which would switch it to metered API billing.
2. **Start from Templates:**
   Scaffold from existing templates in `/var/lib/hermes/sites/templates/` rather than starting from scratch:
   - Full-stack modern apps (React 19 + Vite + Tailwind + Lucide + FastAPI): see [`templates/backend/README.md`](/var/lib/hermes/sites/templates/backend/README.md).
   - Static viewer / dashboard: see [`templates/static/README.md`](/var/lib/hermes/sites/templates/static/README.md).
3. **App Metadata:** Every app must have a valid `meta.json` (`title`, `description`, `icon`, `type`) in its root. An app that wraps a third-party server we don't write (code-server, noVNC, the Hermes dashboard) also sets `"upstream": "<what it wraps>"`.
3a. **An app's API is its CLI (`box`).** `sites/tools/box/box.py` generates a command for every `/api` route of every FastAPI backend from its `/openapi.json` over `app.sock` (`box <app> --help`, `box <app> <cmd> --flag`, `box <app> api METHOD PATH`). Alex wants every useful UI action usable by an LLM this way, without a browser. So for every backend:
   - FastAPI only; every `/api` route has a one-sentence imperative docstring (it becomes `--help`); `GET /api/health` exists.
   - Need a convenience or composite command? Add an API endpoint; the UI can use it too. Never write CLI-side code per app.
   - UI-only routes: pages outside `/api` get `include_in_schema=False`; UI-only `/api` routes (video streams) get `openapi_extra={"x-box": {"hidden": "<reason>"}}`. Override an awkward command name with `{"x-box": {"command": "..."}}`.
   - Run `box lint <app>` after any backend change (it checks a running app, so restart first). Use `box` instead of `curl --unix-socket` for checks and for operating apps.
   - Spec and naming rules (CRUD mapping, output format): `/var/lib/hermes/workspace/designs/box.md`.
4. **Portless Socket Binding:** Server backends bind to `$SITES_RUNTIME_DIR/app.sock` (the apps runner sets it; apps from the backend template do it through libs/appkit). Never hardcode TCP ports in web servers. Persistent data goes in `$SITES_STATE_DIR`.
5. **Instances are owned by the apps runner:** `ai-box-apps-runner` runs the repo's apps runner (`tools/runner`, over process-compose), which launches, health-checks and heals every declared instance. Never start a copy (`python main.py`, `./start.sh`) by hand: it has no runtime or state directory, and a copy of a live instance would take over its socket. Test backend logic with imports or FastAPI's `TestClient`. To pick up code changes, run `box restart <app>` (it waits until the app is back up; doesn't count against the healing cap). Don't kill the PID; that counts as a crash.
6. **Dotfiles Boundary:**
   Apps live entirely in `ai-box-apps`. Never modify NixOS configuration or Caddy rules for individual applications. If a system change or shared package is needed, propose a PR against `nix-config` and ask Alex first.
7. **Mobile and Foldable Support:**
   Test viewports down to narrow screens (280px–340px width, such as the Pixel 11 Pro Fold outer display). Ensure primary controls and status indicators remain visible without layout breakages or horizontal overflow.
8. **Apps that drive hardware** (Vector, other robots, devices on the LAN): read `references/robotics-hardware-bridges.md` first. Add a rule there only after actually hitting the problem.

## Workflow

### Creating a New App

1. Scaffold from the chosen template, and declare its instance:
   ```bash
   box template new <app-name> --template <template>
   # then add `  <app-name>: {app: <app-name>}` under instances: in namespaces/default.yaml
   ```
2. Delegate implementation to Claude Code CLI:
   ```bash
   # Auth: CLAUDE_CODE_OAUTH_TOKEN (Claude subscription) is already set; no API key.
   cd /var/lib/hermes/sites/apps/<app-name>

   claude -p "Your detailed prompt describing requirements..." \
     --model claude-opus-5-5 \
     --allowedTools "Read,Edit,Write,Bash" \
     --max-turns 30
   ```
3. Verify live operation:
   - For backends: verify the instance is up (`box ns list`) and `curl -s --unix-socket /run/sites/<address>/app.sock http://localhost/` returns 200.
   - For public routing: test over Cloudflare Access with service tokens.
   - For visuals: navigate Chromium via CDP, capture screenshot, and verify layout with `vision_analyze`.
4. Commit: `git add <app-name> && git commit -m "feat(<app-name>): initial implementation"`. Stage only your own paths: the live checkout carries runtime churn (tracked `.pyc` files, Wire-Pod logs and jdocs) that must not ride along.

### Modifying an Existing App

1. Inspect existing files in `/var/lib/hermes/sites/apps/<app-name>/`.
2. Dispatch Claude Code CLI with targeted instructions.
3. If the backend process was modified, restart the process to clear in-memory caches.
4. Verify endpoints over the Unix domain socket and inspect the rendered visual state in Chromium before committing.

### Repo-wide changes (several apps, shared tooling)

1. Develop on a branch in a git worktree (`git worktree add -b <branch> <scratch-dir> main`), never in the live checkout; delegate to Claude Code with a brief that forbids restarting apps, touching the live checkout, non-GET requests to live sockets (Vector moves a physical robot) and pushing.
2. Before merging, `box snapshot <app> -o <dir>/<app>.json` for each app (status, content type and JSON keys of every GET endpoint; GET only, so it's safe on hardware apps). Run `box diff <app> <file>` against the still-old apps once, to prove the comparison itself is clean before restarting anything.
3. `git merge --ff-only <branch>` into the live checkout (a merge doesn't trigger the push hook), then `box restart <app>` one app at a time (it waits for a new PID and `up`). Check `hermes kanban list --status running` first for apps a worker is using. After each: `box diff <app> <file>`, `box lint <app>`, and one or two read-only `box <app> ...` commands.
4. Only when every app passes: `git push origin main`, then remove the worktree and branch.
- **Moving an app's data:** move it by hand and write the repo as if it had always been that way. No migration code in `start.sh` or the app (Alex doesn't want vestigial code). Stop the instance first (`box ns down <namespace>`, or drop it from its namespace file), move the files within `/var/lib/hermes/instances/<address>/`, then bring it back up. Never move files under a running instance: it reopens paths and recreates empty files at the old location.

## Troubleshooting

- **404 on Subdomain:**
  Caddy routes an address to `/run/sites/<address>/app.sock` when that runtime directory exists. Check the instance is declared and running (`box ns check`, `box ns list`); a backend app no namespace file names doesn't run.
- **502 Bad Gateway:**
  The backend is down or its socket is gone. The runner heals this on its own within ~2–5 min. Check `/var/lib/apps-health/status.json`, the portal's Status tab, and `/run/sites/<address>/app.log`.
- **Never commit ignored artifacts** (`node_modules`, `__pycache__`): `nix develop` copies the tracked tree into the store whenever the checkout changed, and with ~24k `node_modules` files tracked plus `.pyc` churn, every first restart sat in `starting` for ~4 min (nix-daemon at 100% CPU). `git ls-files -ci --exclude-standard` lists offenders; untrack with `git rm --cached`.
- **App marked `failed`:** auto-healing gave up after 3 restarts in an hour, and the `apps-health` cron job (local Gemma) pinged Alex. Fix the cause, then re-arm: delete `/run/sites/<address>/.runner.failed` or commit a change to the app.
- **Cloudflare Access Verification:**
  Include `CF-Access-Client-Id` and `CF-Access-Client-Secret` headers when making automated curl checks against `*.alexthiele.io`.
- **Git Tracking for Flakes:**
  Nix requires all files in the flake directory to be tracked by Git. Run `git add <app-name>` before running `nix develop` or `start.sh`.
