# ai-box setup: what's left

Picked up from Alex's setup session with Claude Code on 2026-10-11. Work
through these with Alex: each one is a PR to nix-config. Tick items off and
add new ones as you go, and keep this file in a PR like your other
instructions. The context lives in AGENTS.md, SOUL.md, and Alex's nix-config
repo (`hosts/ai-box/`).

## Done

- [x] NixOS on the NVMe (btrfs, hourly snapshots), JetPack 6
- [x] Hermes on Gemini (`gemini-flash-latest`), secrets from the
      `ai-assistant` vault, cron limited to web/vision/session_search
- [x] Discord chat and a GitHub account (ailex-agent) with write access to
      nix-config; `master` is protected
- [x] `ai-box-switch` plus an hourly autoUpgrade from `master`
- [x] **Say hi.** Confirm Discord works both ways, and send Alex a message on
      a schedule (a one-shot cron job) to prove you can reach out on your own.
- [x] **First PR.** Run `gh auth setup-git`, set your git identity (see
      AGENTS.md), and open a small PR (e.g. tick this item) to prove the loop:
      branch, build, PR, Alex merges, `ai-box-switch`.
- [x] **Local model for scheduled jobs.** llama.cpp (CUDA, sm_87) serving
      Gemma 4 26B-A4B as a NixOS service, set as `cron.model` /
      `cron.model_provider` with 256K context.
- [x] **Browser with a live view.** A visible Chromium on a virtual display
      (Xvfb) with a persistent profile (`/var/lib/hermes/browser-profile`),
      exposed to Hermes over CDP (`browser.cdp_url = "http://127.0.0.1:9222"`)
      and to Alex through noVNC (web-native HTML5 VNC viewer).
- [x] **Cloudflare Tunnel & Access setup.** Connect ai-box via Cloudflare Tunnel
      (token in `ai-assistant` vault). Expose noVNC (`browser.alexthiele.io`)
      and dynamic sites (`*.alexthiele.io`) behind Cloudflare Access. Authorize
      Alex's email, `ailex.agent.bot@gmail.com`, and an Access Service Token.
- [x] **Host web pages.** Caddy serving `/var/lib/hermes/sites/{subdomain}` for
      instant static web publishing with zero rebuilds. Hermes validates
      deployments through Cloudflare Access using its Service Token before
      reporting done.

## Next

- [ ] **Notes from the old agent (openclaw/"Alexnet")** as read-only reference
      under `/var/lib/hermes/reference/openclaw/`, not imported. Alex has the
      backup on his laptop (agilite); ask him to copy it over.
- [ ] **Telegram** (optional): Alex creates a bot with @BotFather and puts the
      token in the vault.
- [ ] **Rotate reused secrets:** the Gemini key and the Discord bot token came
      from the old setup, where they sat in plaintext. Ask Alex to rotate them;
      no config change is needed afterwards beyond
      `systemctl restart hermes-secrets hermes-agent`.
- [ ] **Change alex's password on ai-box.** It's still the public default, and
      it's also what sudo asks for. Remind Alex.
