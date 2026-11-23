"""The gateway's boot on this system's config, run by the system build (./default.nix) with
Hermes's own interpreter. The throwaway HERMES_HOME holds the config.yaml nix writes. The
environment holds every variable hermes-secrets writes (dummy values), as systemd's
EnvironmentFile gives them to the gateway. The build fails if the gateway would serve several
profiles (it would then read secrets only from each profile's .env), or if Discord's or email's
secret isn't reachable the way the gateway reads it.

Usage: gateway-check.py <hermes-secrets's op template>
"""

import os
import re
import sys
from pathlib import Path

for line in Path(sys.argv[1]).read_text().splitlines():
    if m := re.fullmatch(r"([A-Z][A-Z0-9_]*)=(.*)", line.strip()):
        name, value = m.groups()
        os.environ[name] = "1234567890123456789" if "{{" in value else value

from agent.secret_scope import get_secret  # noqa: E402
from gateway.config import Platform, load_gateway_config  # noqa: E402
from hermes_cli.gateway_multiplex_mode import (  # noqa: E402
    explicit_multiplex_flag,
    resolve_multiplex_mode,
)
from tui_gateway.launch_profile_policy import (  # noqa: E402
    activate_multi_profile_hosting_eagerly,
)

home = Path(os.environ["HERMES_HOME"])
assert (
    explicit_multiplex_flag(home) is False
), "config.yaml sets no multiplex_profiles: false"
# The gateway's boot, in its order: multi-profile hosting, then the config and its verdict.
assert (
    not activate_multi_profile_hosting_eagerly()
), "the gateway would host several profiles"
config = load_gateway_config()
decision = resolve_multiplex_mode(config)
assert not decision.enabled, f"the gateway would multiplex profiles: {decision}"
connected = config.get_connected_platforms()
for platform, secret in (
    (Platform.DISCORD, "DISCORD_BOT_TOKEN"),
    (Platform.EMAIL, "EMAIL_PASSWORD"),
):
    assert platform in connected, f"{platform.value} isn't connected: {connected}"
    assert get_secret(secret) == os.environ[secret], f"the gateway can't read {secret}"
print("gateway check holds")
