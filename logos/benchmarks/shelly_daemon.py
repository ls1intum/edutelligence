#!/usr/bin/env python3
"""Shelly wall-power push daemon.

Polls Shelly Plug M Gen 3 devices every second, sums power per server,
and broadcasts the readings via UDP to a target host (e.g. the benchmark host).

The benchmark listens on the same port. If no one is listening, UDP packets
are silently dropped — that is fine.

Usage:
    python3 shelly_daemon.py TARGET_HOST [PORT] [--config PATH] [--tcp]

    TARGET_HOST  Hostname or IP to push readings to
    PORT         Target port (default: 9876)
    --config     Path to JSON config file with plug definitions
                 (default: shelly_plugs.json next to this script)
    --tcp        Stream newline-delimited JSON over a persistent TCP connection
                 instead of UDP datagrams. Use this when the network drops
                 inter-subnet UDP between the Pi and the benchmark host.
                 Must match the benchmark's --shelly-transport.

Config file format (shelly_plugs.json):
    {
        "server-a": ["192.168.1.10", "192.168.1.11"],
        "server-b": ["192.168.1.20", "192.168.1.21"]
    }

    Keys become server names in the UDP payload; values are lists of
    Shelly IP addresses whose apower readings are summed per server.
"""

import argparse
import json
import socket
import sys
import time
import urllib.request
from pathlib import Path
from typing import Optional

INTERVAL_S = 1.0
TIMEOUT_S = 2.0

_DEFAULT_CONFIG = Path(__file__).parent / "shelly_plugs.json"


def _read_watts(ip: str) -> float:
    url = f"http://{ip}/rpc/Switch.GetStatus?id=0"
    try:
        resp = urllib.request.urlopen(url, timeout=TIMEOUT_S)
        return float(json.loads(resp.read())["apower"])
    except Exception:
        return -1.0


def main() -> None:
    parser = argparse.ArgumentParser(description="Shelly wall-power push daemon")
    parser.add_argument("target_host", help="Hostname/IP to push UDP packets to")
    parser.add_argument("port", nargs="?", type=int, default=9876, help="UDP port (default: 9876)")
    parser.add_argument(
        "--config",
        type=Path,
        default=_DEFAULT_CONFIG,
        help="Path to JSON plug-config file (default: shelly_plugs.json next to this script)",
    )
    parser.add_argument(
        "--tcp",
        action="store_true",
        help="Stream newline-delimited JSON over a persistent TCP connection instead of UDP "
        "(use when inter-subnet UDP is firewalled). Must match the benchmark's --shelly-transport.",
    )
    args = parser.parse_args()

    if not args.config.exists():
        print(f"Config file not found: {args.config}", file=sys.stderr)
        print("Create a shelly_plugs.json with {server: [ip, ...]} entries.", file=sys.stderr)
        sys.exit(1)

    plugs: dict[str, list[str]] = json.loads(args.config.read_text())

    transport = "tcp" if args.tcp else "udp"
    sock: Optional[socket.socket] = None if args.tcp else socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    print(
        f"[shelly-daemon] config={args.config}  pushing to {args.target_host}:{args.port} "
        f"({transport}) every {INTERVAL_S:.1f}s",
        flush=True,
    )

    def _send(line: bytes) -> None:
        """Send one reading. UDP: fire-and-forget. TCP: (re)connect as needed."""
        nonlocal sock
        if not args.tcp:
            try:
                sock.sendto(line, (args.target_host, args.port))
            except OSError:
                pass  # network blip — keep going
            return
        try:
            if sock is None:
                sock = socket.create_connection((args.target_host, args.port), timeout=TIMEOUT_S)
            sock.sendall(line + b"\n")
        except OSError:
            # Connection dropped or refused — reset so the next tick reconnects.
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass
            sock = None

    while True:
        readings: dict[str, float] = {}
        total_w = 0.0
        all_ok = True

        for server, ips in plugs.items():
            server_w = 0.0
            for ip in ips:
                w = _read_watts(ip)
                if w < 0:
                    all_ok = False
                    break
                server_w += w
            if not all_ok:
                break
            readings[server] = round(server_w, 1)
            total_w += server_w

        if all_ok:
            payload = {**readings, "total": round(total_w, 1)}
            _send(json.dumps(payload).encode())

        time.sleep(INTERVAL_S)


if __name__ == "__main__":
    main()
