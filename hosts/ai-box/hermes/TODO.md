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

## Next

- [ ] **Say hi.** Confirm Discord works both ways, and send Alex a message on
      a schedule (a one-shot cron job) to prove you can reach out on your own.
- [ ] **First PR.** Run `gh auth setup-git`, set your git identity (see
      AGENTS.md), and open a small PR (e.g. tick this item) to prove the loop:
      branch, build, PR, Alex merges, `ai-box-switch`.
- [ ] **Browser with a live view.** A visible Chromium on a virtual display
      (Xvfb or similar) with a persistent profile, exposed to Hermes over CDP
      (`browser.cdp_url`) and to Alex through noVNC. When you're blocked on a
      login or CAPTCHA, send Alex the live-view link. Note: Playwright's
      downloaded browsers don't run on NixOS; use nixpkgs' `chromium`.
- [ ] **Host web pages.** Caddy serving `/var/lib/hermes/sites/<name>` with no
      rebuild per change; verify locally first, then publicly. Public access
      through a new Cloudflare Tunnel behind Cloudflare Access, plus an Access
      service token so you can load your own public pages (the old setup
      couldn't, so it never verified its work). Alex needs to log in to
      `cloudflared` once for this.
- [ ] **Local model for scheduled jobs.** llama.cpp (CUDA, sm_87) serving
      Gemma 4 26B-A4B as a NixOS service, set as `cron.model` /
      `cron.model_provider`. It must serve at least 64K context.
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
