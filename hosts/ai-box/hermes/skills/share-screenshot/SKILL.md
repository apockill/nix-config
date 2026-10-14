---
name: share-screenshot
description: "Use when capturing, saving, or sharing screenshots to Discord chat or other messaging platforms."
version: 1.0.0
author: Alex Thiele + Hermes Agent
platforms: [linux]
---

# Sharing Screenshots via Messaging Platforms

Hermes delivers native images to Discord and other messaging platforms when a valid `MEDIA:<path>` tag is included in the assistant's final response text.

## Hard Rules

1. **The Delivery Allowlist:**
   Hermes gateway enforces a strict security sandbox that denylists paths starting with `/var/lib` (including `/var/lib/hermes/workspace/`). Any file in a denied directory is silently dropped:
   ```text
   WARNING gateway.platforms.base: Skipping MEDIA directive path (denied by the delivery policy)
   ```
   To bypass this, all deliverable screenshots MUST be saved to or copied into:
   ```
   /var/lib/hermes/.hermes/browser_screenshots/
   ```
   (which corresponds to `~/.hermes/browser_screenshots/`). This directory is an explicitly allowlisted safe root in Hermes core.

2. **The Output Directive:**
   Append the tag on its own line at the very end of your response:
   ```
   MEDIA:/var/lib/hermes/.hermes/browser_screenshots/<filename>.png
   ```

3. **Pre-Flight Verification:**
   Before emitting the tag, always verify that the file actually exists on disk and is non-empty (`test -s <path>`).

4. **MANDATORY VISUAL INSPECTION (Never Send Broken UI Screenshots):**
   Before including `MEDIA:<path>` or reporting that a UI task is done, **YOU MUST inspect the image yourself with `vision_analyze`**.
   Check every critical element:
   - **Login Wall Check:** When testing apps on `*.alexthiele.io`, ensure the browser is NOT sitting on the Cloudflare Access login screen ("Log in to Alex's Homelab"). Always inject the `CF_Authorization` cookie via CDP before navigating, and verify `window.location.href` does not contain `cloudflareaccess.com`.
   - **No Hallucination:** Never ask leading questions in vision analysis that assume what the screen contains. Objectively verify the actual text, title, and visual content on screen.
   - Are video streams, canvases, and feeds rendering actual live frames (not black boxes, 'DISCONNECTED', '0 FPS', or 'NO SIGNAL')?
   - Are telemetry gauges and percentages showing plausible live data?
   - Are there any layout glitches, overflow banners, or error toasts?
   **Strict Rule:** Never claim a feature is done or share a screenshot if the image itself shows a login wall, error, disconnection, or broken element. Fix the bug first before contacting Alex.

## Standard Capture Workflow

```python
import base64

# 1. Capture via CDP
res = cdp("Page.captureScreenshot", format="png")
output_path = "/var/lib/hermes/.hermes/browser_screenshots/my_screenshot.png"

# 2. Save directly to the allowlisted cache directory
with open(output_path, "wb") as f:
    f.write(base64.b64decode(res["data"]))

# 3. Output in final response:
# MEDIA:/var/lib/hermes/.hermes/browser_screenshots/my_screenshot.png
```
