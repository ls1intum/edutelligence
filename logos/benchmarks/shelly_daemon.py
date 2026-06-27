#!/usr/bin/env python3
"""Shelly wall-power push daemon.

Polls Shelly Plug M Gen 3 devices every second, sums power per server,
and broadcasts the readings via UDP to a target host (e.g. the benchmark host).

The benchmark listens on the same port. If no one is listening, UDP packets
are silently dropped — that is fine.

Usage:
    python3 shelly_daemon.py TARGET_HOST [PORT] [--config PATH] [--tcp]
    python3 shelly_daemon.py --http URL [--insecure] [--config PATH]

    TARGET_HOST  Hostname or IP to push readings to (UDP/TCP modes)
    PORT         Target port (default: 9876)
    --config     Path to JSON config file with plug definitions
                 (default: shelly_plugs.json next to this script)
    --tcp        Stream newline-delimited JSON over a persistent TCP connection
                 instead of UDP datagrams. Use when the network drops
                 inter-subnet UDP between the Pi and the benchmark host.
    --http URL   HTTP(S) POST each reading to URL (e.g.
                 https://logos-test.aet.cit.tum.de/shelly-ingest). Use when only
                 HTTPS/443 passes the firewall — readings ride Traefik to the
                 benchmark's ingest sidecar. Must match --shelly-transport http.
    --insecure   With --http: skip TLS verification (internal telemetry).

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
import ssl
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
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
    parser.add_argument(
        "target_host",
        nargs="?",
        default=None,
        help="Hostname/IP to push readings to (UDP/TCP modes). Omit when using --http.",
    )
    parser.add_argument("port", nargs="?", type=int, default=9876, help="Target port (default: 9876)")
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
    parser.add_argument(
        "--http",
        metavar="URL",
        default=None,
        help="HTTP(S) POST each reading as a JSON body to URL (e.g. "
        "https://logos-test.aet.cit.tum.de/shelly-ingest). Use when only HTTPS/443 passes the "
        "firewall — readings ride Traefik. Must match the benchmark's --shelly-transport http.",
    )
    parser.add_argument(
        "--insecure",
        action="store_true",
        help="With --http: skip TLS certificate verification (internal telemetry).",
    )
    args = parser.parse_args()

    if not args.config.exists():
        print(f"Config file not found: {args.config}", file=sys.stderr)
        print("Create a shelly_plugs.json with {server: [ip, ...]} entries.", file=sys.stderr)
        sys.exit(1)
    if not args.http and not args.target_host:
        print("Error: provide TARGET_HOST (udp/tcp) or --http URL.", file=sys.stderr)
        sys.exit(1)

    plugs: dict[str, list[str]] = json.loads(args.config.read_text())

    transport = "http" if args.http else ("tcp" if args.tcp else "udp")
    sock: Optional[socket.socket] = socket.socket(socket.AF_INET, socket.SOCK_DGRAM) if transport == "udp" else None
    _ssl_ctx = ssl._create_unverified_context() if (args.http and args.insecure) else None
    dest = args.http if args.http else f"{args.target_host}:{args.port}"
    print(
        f"[shelly-daemon] config={args.config}  pushing to {dest} ({transport}) every {INTERVAL_S:.1f}s",
        flush=True,
    )

    def _send(line: bytes) -> None:
        """Send one reading. UDP: fire-and-forget. TCP: (re)connect. HTTP: POST."""
        nonlocal sock
        if transport == "http":
            try:
                req = urllib.request.Request(
                    args.http, data=line, headers={"Content-Type": "application/json"}, method="POST"
                )
                urllib.request.urlopen(req, timeout=TIMEOUT_S, context=_ssl_ctx).close()
            except Exception:
                pass  # endpoint down / blip — keep going
            return
        if transport == "udp":
            try:
                sock.sendto(line, (args.target_host, args.port))
            except OSError:
                pass  # network blip — keep going
            return
        # tcp
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

    # Read every plug concurrently so the loop period is bounded by the single
    # slowest plug (~RTT, < TIMEOUT_S) rather than the SUM of all plug RTTs.
    # Sequential reads of N plugs took N×RTT and, with the trailing full
    # time.sleep(INTERVAL_S) added on top, pushed the real cadence to ~3 s for a
    # 4-plug setup — so the benchmark only saw a wall-power sample every ~3 s.
    all_ips = [ip for ips in plugs.values() for ip in ips]
    pool = ThreadPoolExecutor(max_workers=max(1, len(all_ips)))

    while True:
        loop_start = time.monotonic()

        # Fan out all plug reads at once, then assemble per-server sums.
        watts_by_ip = dict(zip(all_ips, pool.map(_read_watts, all_ips)))
        readings: dict[str, float] = {}
        total_w = 0.0
        all_ok = True
        for server, ips in plugs.items():
            server_w = 0.0
            for ip in ips:
                w = watts_by_ip.get(ip, -1.0)
                if w < 0:
                    all_ok = False
                    break
                server_w += w
            if not all_ok:
                break
            readings[server] = round(server_w, 1)
            total_w += server_w

        if all_ok:
            # Per-server keys (e.g. "deimama", "deipapa") plus the aggregate let
            # the benchmark attribute wall energy per node, not just in total.
            payload = {**readings, "total": round(total_w, 1)}
            _send(json.dumps(payload).encode())

        # Deadline-based sleep keeps a true ~INTERVAL_S cadence: subtract the time
        # already spent polling instead of always sleeping a full interval on top.
        time.sleep(max(0.0, INTERVAL_S - (time.monotonic() - loop_start)))


if __name__ == "__main__":
    main()
