---
name: create-webapp
description: "Use when creating, modifying, deploying, or debugging web apps and dashboards on ai-box."
version: 1.0.0
author: Alex Thiele + Hermes Agent
platforms: [linux]
---

# Creating and Modifying Webapps on ai-box

This skill outlines the lifecycle, delegation patterns, and verification standards for web applications hosted on `ai-box` (`*.alexthiele.io`).

## Architecture Overview

- **Repository:** All apps live in the private repository [`ailex-agent/ai-box-apps`](https://github.com/ailex-agent/ai-box-apps), cloned locally to `/var/lib/hermes/sites/`.
- **Dynamic Routing:** Caddy automatically serves `/var/lib/hermes/sites/<name>` at `https://<name>.alexthiele.io` with zero Nix rebuilds.
- **Portless Backends:** Server backends (FastAPI, Node) bind to a local Unix domain socket at `./app.sock`. Caddy automatically proxies traffic to `app.sock` if it exists.
- **Root Portal:** `https://alexthiele.io` / `https://portal.alexthiele.io` dynamically live-scans all apps and renders the catalog.
- **Single-Directory Isolation:** Every project is 100% self-contained. Deleting an app is strictly `rm -rf /var/lib/hermes/sites/<name>`.
- **Automatic Sync:** A git post-commit hook automatically pushes commits to `origin/main`.

## Rule: 1 Commit == 1 Verified Change
Never commit code before proving it works. Never tell Alex something is done until verified with high confidence.
- **Visual Inspection Gate:** Always inspect captured screenshots using `vision_analyze` before sharing them or claiming a webapp is complete. Never report completion if video streams, canvases, or metrics show error states ('CAM STREAM DISCONNECTED', 'NO SIGNAL', 0 FPS, broken layouts). Fix the underlying bug first before reaching out.

## Golden Rules for AI Agents
1. **Always Delegate Coding to Claude Code CLI:**
   Hermes is an orchestrator, not a primary code generator. Use Claude Code CLI (`claude -p "..."`) for implementation, refactoring, and code edits.
2. **Always Use Templates:** Copy from `_templates/static` or `_templates/backend`.
3. **Always Include `meta.json`:** Every app must have `meta.json` (`title`, `description`, `icon`, `type`).
4. **Never Hardcode TCP Ports:** Always bind backends to `./app.sock`.
5. **Always Send Screenshots:** After creating or editing a webapp, verify it in Chromium and send a screenshot using the `/share-screenshot` skill.
6. **Dotfiles Boundary:** Changes to `nix-config` require proposing a PR and asking Alex first. Apps in `/var/lib/hermes/sites/` do not touch dotfiles.

---

## Workflow: Creating a New App

### 1. Choose the Template
- **Static App (Dashboard, Viewer, Report):**
  If the app only needs client-side HTML/JS or reads JSON updated by cron, use `_templates/static`.
  See [`/var/lib/hermes/sites/_templates/static/README.md`](_templates/static/README.md).
- **Backend App (Server, REST API, SQLite, Python):**
  If the app needs persistent server logic or a database, use `_templates/backend`.
  See [`/var/lib/hermes/sites/_templates/backend/README.md`](_templates/backend/README.md).

### 2. Scaffold Directory
```bash
cp -r /var/lib/hermes/sites/_templates/<static|backend> /var/lib/hermes/sites/<app-name>
```

### 3. Delegate Implementation to Claude Code CLI
Run Claude Code in headless print mode (`-p`) inside the app directory:
```bash
TOKEN=$(op item get "Anthropic API Key" --vault ai-assistant --fields label=credential --reveal)
export CLAUDE_CODE_OAUTH_TOKEN="$TOKEN"
cd /var/lib/hermes/sites/<app-name>

claude -p "Your detailed prompt describing the features, styling, and requirements..." \
  --model opus \
  --allowedTools "Read,Edit,Write,Bash" \
  --max-turns 15
```

### 4. Verify Before Reporting
1. **Socket / Service Test (for backends):**
   Ensure `./start.sh` starts and `curl -s --unix-socket ./app.sock http://localhost/` returns 200.
2. **Public Endpoint Test:**
   Test over Cloudflare Access using service token headers:
   ```bash
   set -a && . /run/hermes-secrets/env && set +a
   curl -s -I "https://<app-name>.alexthiele.io" \
     -H "CF-Access-Client-Id: $CF_ACCESS_CLIENT_ID" \
     -H "CF-Access-Client-Secret: $CF_ACCESS_CLIENT_SECRET"
   ```
3. **Visual In-Browser Test:**
   Navigate Chromium via CDP to `https://<app-name>.alexthiele.io`, confirm elements render, check console for errors, and save a screenshot under `/var/lib/hermes/.hermes/browser_screenshots/<app-name>.png`.

### 5. Commit and Share
Only after verification passes:
```bash
cd /var/lib/hermes/sites
git add <app-name>
git commit -m "feat(<app-name>): initial implementation"
```
Deliver the screenshot in your reply:
```
MEDIA:/var/lib/hermes/.hermes/browser_screenshots/<app-name>.png
```

---

## Workflow: Modifying an Existing App

1. Inspect existing files in `/var/lib/hermes/sites/<app-name>/`.
2. Dispatch Claude Code with the modification task:
   ```bash
   cd /var/lib/hermes/sites/<app-name>
   claude -p "Task description..." --allowedTools "Read,Edit,Write,Bash" --max-turns 10
   ```
3. Re-verify the live app via curl and browser CDP.
4. Commit: `git commit -m "feat(<app-name>): update description"` (auto-pushes to `main`).
5. Capture and share the updated screenshot via `MEDIA:`.

---

## Troubleshooting

- **404 Not Found on `<name>.alexthiele.io`:**
  - Verify directory name in `/var/lib/hermes/sites/` matches the subdomain exactly.
  - If backend: verify `app.sock` was created with correct permissions (`0666` or `0660` hermes:hermes).
  - If static: verify `index.html` exists in the folder root.
- **502 Bad Gateway:**
  - The backend server crashed or exited. Inspect `/var/lib/hermes/sites/<app-name>/app.log`.
- **403 Forbidden from Cloudflare:**
  - Include `CF-Access-Client-Id` and `CF-Access-Client-Secret` headers in curl, or inject the `CF_Authorization` cookie into CDP.
