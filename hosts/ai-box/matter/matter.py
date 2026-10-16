"""Tiny CLI for the local Matter controller (python-matter-server, ws://127.0.0.1:5580).

matter nodes                  list paired devices (id, vendor/product, on/off state)
matter on|off|toggle NODE     switch an On/Off device (endpoint 1 by default)
matter status NODE            print "on" or "off"
matter commission [--network-only]
                              pair a device; reads the setup code from stdin,
                              so it never appears in argv or shell history:
                                op read 'op://ai-assistant/<item>/setup_code' | matter commission
matter remove NODE            unpair a device
matter wifi SSID              Wi-Fi network for devices paired over Bluetooth; reads
                              the password from stdin:
                                op read 'op://ai-assistant/<wifi item>/password' | matter wifi SSID
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any

import websockets

URL = "ws://127.0.0.1:5580/ws"
ON_OFF_CLUSTER = 6
ON_OFF_ATTRIBUTE = 0


class Matter:
    def __init__(self, ws: websockets.ClientConnection) -> None:
        self.ws = ws
        self.next_id = 0

    async def call(self, command: str, timeout: float = 30, **args: Any) -> Any:
        self.next_id += 1
        message_id = str(self.next_id)
        await self.ws.send(
            json.dumps({"message_id": message_id, "command": command, "args": args})
        )
        async with asyncio.timeout(timeout):
            while True:
                reply = json.loads(await self.ws.recv())
                if reply.get("message_id") != message_id:
                    continue  # server info and event pushes
                if "error_code" in reply:
                    raise SystemExit(
                        f"{command} failed: {reply.get('details') or reply['error_code']}"
                    )
                return reply.get("result")


def on_off(node: dict[str, Any], endpoint: int) -> bool | None:
    value = node.get("attributes", {}).get(
        f"{endpoint}/{ON_OFF_CLUSTER}/{ON_OFF_ATTRIBUTE}"
    )
    return None if value is None else bool(value)


async def run(args: argparse.Namespace) -> None:
    async with websockets.connect(URL, max_size=None) as ws:
        await ws.recv()  # server_info
        matter = Matter(ws)
        if args.cmd == "nodes":
            for node in await matter.call("get_nodes"):
                attrs = node.get("attributes", {})
                state = on_off(node, args.endpoint)
                print(
                    f"{node['node_id']}\t{attrs.get('0/40/1', '?')} {attrs.get('0/40/3', '?')}"
                    f"\tavailable={node.get('available')}"
                    f"\t{'on' if state else 'off' if state is not None else '-'}"
                )
        elif args.cmd in ("on", "off", "toggle"):
            await matter.call(
                "device_command",
                node_id=args.node,
                endpoint_id=args.endpoint,
                cluster_id=ON_OFF_CLUSTER,
                command_name=args.cmd.capitalize(),
                payload={},
            )
            print(f"node {args.node}: {args.cmd} sent")
        elif args.cmd == "status":
            value = await matter.call(
                "read_attribute",
                node_id=args.node,
                attribute_path=f"{args.endpoint}/{ON_OFF_CLUSTER}/{ON_OFF_ATTRIBUTE}",
            )
            state = (
                value.get(f"{args.endpoint}/{ON_OFF_CLUSTER}/{ON_OFF_ATTRIBUTE}")
                if isinstance(value, dict)
                else value
            )
            print("on" if state else "off")
        elif args.cmd == "commission":
            code = sys.stdin.readline().strip().replace("-", "")
            if not code:
                raise SystemExit("commission: pipe the setup code on stdin")
            node = await matter.call(
                "commission_with_code",
                timeout=300,
                code=code,
                network_only=args.network_only,
            )
            print(f"commissioned: node {node['node_id']}")
        elif args.cmd == "wifi":
            password = sys.stdin.readline().rstrip("\n")
            if not password:
                raise SystemExit("wifi: pipe the Wi-Fi password on stdin")
            await matter.call(
                "set_wifi_credentials", ssid=args.ssid, credentials=password
            )
            print(f"Wi-Fi credentials set for {args.ssid}")
        elif args.cmd == "remove":
            await matter.call("remove_node", node_id=args.node)
            print(f"node {args.node}: removed")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="matter",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--endpoint", type=int, default=1, help="device endpoint (default 1)"
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("nodes")
    for name in ("on", "off", "toggle", "status", "remove"):
        sub.add_parser(name).add_argument("node", type=int)
    sub.add_parser("wifi").add_argument("ssid")
    commission = sub.add_parser("commission")
    commission.add_argument(
        "--network-only",
        action="store_true",
        help="skip Bluetooth (device already on the network, e.g. shared from another app)",
    )
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
