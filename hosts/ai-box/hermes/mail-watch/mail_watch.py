"""mail-watch: wake Hermes when an email arrives at the agent's Gmail.

Polls the inbox over IMAP (app password), without marking anything read. Each new
message goes one of three ways, each a route on the Hermes webhook platform:

- mail-trusted: From is a trusted sender and Gmail's DMARC check passed -> a full
  agent run, delivered (and mirrored) into Alex's Discord chat.
- mail-flagged: anyone else, and the local Gemma says it needs Hermes -> an agent
  run with the webhook platform's restricted tools (untrusted content).
- mail-ignored: Gemma says it doesn't -> one Discord line, no LLM, so Alex can
  judge the classification.

Config comes from the environment (the hermes-secrets env file). State (UIDVALIDITY
and the last UID handled) lives in STATE; the first run starts from the newest
message instead of processing the backlog.
"""

import email
import email.policy
import email.utils
import hashlib
import hmac
import html
import imaplib
import json
import os
import re
import sys
import time
import urllib.request
from email.message import EmailMessage
from pathlib import Path
from typing import Any

USER = "ailex.agent.bot@gmail.com"
STATE = Path(
    os.environ.get("MAIL_WATCH_STATE", "/var/lib/hermes/.hermes/mail-watch/state.json")
)
WEBHOOK = os.environ.get("MAIL_WATCH_WEBHOOK", "http://127.0.0.1:8644/webhooks")
LLM = os.environ.get("MAIL_WATCH_LLM", "http://127.0.0.1:8080/v1/chat/completions")
MODEL = os.environ.get("MAIL_WATCH_MODEL", "gemma-4-26b-a4b")
POLL_S = int(os.environ.get("MAIL_WATCH_POLL_S", "60"))
BODY_MAX = 12000


def log(*a: object) -> None:
    print(*a, flush=True)


def trusted_senders() -> set[str]:
    # MAIL_TRUSTED holds free text (a vault note); every address in it is trusted.
    return {
        m.lower()
        for m in re.findall(
            r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", os.environ.get("MAIL_TRUSTED", "")
        )
    }


def load_state() -> dict[str, Any]:
    try:
        return dict(json.loads(STATE.read_text()))
    except (OSError, ValueError):
        return {}


def save_state(s: dict[str, Any]) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(s))
    tmp.replace(STATE)


def text_of(msg: EmailMessage) -> str:
    part = msg.get_body(preferencelist=("plain", "html"))
    if part is None:
        return ""
    try:
        t = part.get_content()
    except (LookupError, ValueError):
        t = part.get_payload(decode=True).decode("utf-8", "replace")  # type: ignore[union-attr]
    if part.get_content_subtype() == "html":
        t = re.sub(r"(?is)<(script|style).*?</\1>", " ", t)
        t = html.unescape(re.sub(r"<[^>]+>", " ", t))
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n\s*\n+", "\n\n", t).strip()
    return t[:BODY_MAX] + ("\n[... truncated]" if len(t) > BODY_MAX else "")


def classify(sender: str, subject: str, body: str) -> tuple[bool, str]:
    prompt = (
        "You triage email for Hermes, an AI assistant that works for Alex. Hermes has its own Gmail.\n"
        "Decide whether this email needs Hermes' attention: a real person writing to Hermes or about "
        "Alex's projects, an account/security notice that needs action, a reply in a thread Hermes "
        "started, or anything time-sensitive. Newsletters, marketing, promotions, routine receipts and "
        "automated notifications that need no action do NOT.\n"
        'Answer with JSON only: {"needs_hermes": true|false, "reason": "<= 12 words"}\n\n'
        f"From: {sender}\nSubject: {subject}\n\n{body[:4000]}"
    )
    req = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "max_tokens": 400,
    }
    r = urllib.request.Request(
        LLM, json.dumps(req).encode(), {"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(r, timeout=180) as resp:
        out = json.loads(resp.read())["choices"][0]["message"]["content"] or ""
    m = re.search(r"\{.*\}", out, re.S)
    if not m:
        return True, f"unparseable classifier reply: {out[:80]!r}"
    try:
        d = json.loads(m.group(0))
    except ValueError:
        return True, f"unparseable classifier reply: {out[:80]!r}"
    return bool(d.get("needs_hermes")), str(d.get("reason", ""))[:200]


def post(route: str, payload: dict[str, Any]) -> None:
    body = json.dumps(payload).encode()
    ts = str(int(time.time()))
    sig = hmac.new(
        os.environ["WEBHOOK_SECRET"].encode(), f"{ts}.".encode() + body, hashlib.sha256
    ).hexdigest()
    r = urllib.request.Request(
        f"{WEBHOOK}/{route}",
        body,
        {
            "Content-Type": "application/json",
            "X-Webhook-Timestamp": ts,
            "X-Webhook-Signature-V2": sig,
            "X-Request-ID": f"mail-{payload['uid']}-{payload['uidvalidity']}",
        },
    )
    with urllib.request.urlopen(r, timeout=30) as resp:
        log(f"  -> {route}: HTTP {resp.status}")


def handle(uid: int, uidvalidity: int, raw: bytes, trusted: set[str]) -> None:
    msg = email.message_from_bytes(raw, policy=email.policy.default)
    assert isinstance(msg, EmailMessage)
    sender = str(msg.get("From", ""))
    addr = (email.utils.parseaddr(sender)[1] or "").lower()
    subject = str(msg.get("Subject", "(no subject)"))
    auth = " ".join(str(h) for h in msg.get_all("Authentication-Results", []))
    dmarc = bool(re.search(r"\bdmarc=pass\b", auth))
    body = text_of(msg)
    payload: dict[str, Any] = {
        "uid": uid,
        "uidvalidity": uidvalidity,
        "from": sender,
        "subject": subject,
        "date": str(msg.get("Date", "")),
        "body": body,
        "dmarc": "pass" if dmarc else "not pass",
    }
    log(f"uid {uid}: {addr!r} {subject[:60]!r} dmarc={payload['dmarc']}")
    if addr in trusted and dmarc:
        post("mail-trusted", payload)
        return
    needs, reason = classify(sender, subject, body)
    payload["reason"] = reason
    log(f"  gemma: needs_hermes={needs} ({reason})")
    post("mail-flagged" if needs else "mail-ignored", payload)


def run_once(state: dict[str, Any]) -> None:
    pw = os.environ["MAIL_APP_PASSWORD"]
    trusted = trusted_senders()
    m = imaplib.IMAP4_SSL("imap.gmail.com", 993)
    try:
        m.login(USER, pw)
        m.select("INBOX", readonly=True)
        uv = int(m.response("UIDVALIDITY")[1][0])
        typ, data = m.uid("search", "ALL")
        uids = [int(u) for u in data[0].split()] if data and data[0] else []
        if state.get("uidvalidity") != uv or "last_uid" not in state:
            state.update(uidvalidity=uv, last_uid=max(uids, default=0))
            save_state(state)
            log(
                f"baseline: uidvalidity {uv}, last uid {state['last_uid']} ({len(uids)} messages skipped)"
            )
            return
        for uid in sorted(u for u in uids if u > state["last_uid"]):
            typ, d = m.uid("fetch", str(uid), "(BODY.PEEK[])")
            raw = next((p[1] for p in d if isinstance(p, tuple)), None)
            if raw:
                handle(uid, uv, raw, trusted)
            state["last_uid"] = uid
            save_state(state)
    finally:
        try:
            m.logout()
        except (OSError, imaplib.IMAP4.error):
            pass


def main() -> None:
    state = load_state()
    log(
        f"mail-watch: {USER}, poll {POLL_S}s, {len(trusted_senders())} trusted sender(s)"
    )
    while True:
        try:
            run_once(state)
        except Exception as e:  # keep polling through network/IMAP/webhook hiccups
            log(f"error: {type(e).__name__}: {e}")
        if "--once" in sys.argv:
            return
        time.sleep(POLL_S)


if __name__ == "__main__":
    main()
