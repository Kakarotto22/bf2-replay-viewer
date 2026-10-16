"""Development helper: minimal BF2 ModManager-style rcon client.

Protocol (``admin/default.py`` on the server): the server greets with
``### Digest seed: <seed>``; the client logs in with
``\\x02login <md5(seed + password)>`` and then sends ``\\x02exec <console cmd>``.
Responses end with ``\\x04``.

Usage::

    python scripts/rcon.py [--host 127.0.0.1] [--port 4711] [--password re] CMD [CMD ...]

Example: ``python scripts/rcon.py "demo.recordDemo test_spawn"``
"""

from __future__ import annotations

import argparse
import hashlib
import socket


def _read_until(sock: socket.socket, marker: bytes, timeout: float = 10.0) -> bytes:
    """Read until ``marker``; a timeout returns what arrived (commands without console output never send the marker)."""
    sock.settimeout(timeout)
    buf = b""
    try:
        while marker not in buf:
            chunk = sock.recv(4096)
            if not chunk:
                break
            buf += chunk
    except socket.timeout:
        pass
    return buf


def run(commands, host="127.0.0.1", port=4711, password="re", reply_timeout=10.0):
    out = []
    with socket.create_connection((host, port), timeout=10) as sock:
        greeting = _read_until(sock, b"Digest seed: ")
        if b"\n" not in greeting.split(b"Digest seed: ", 1)[1]:
            greeting += _read_until(sock, b"\n")
        seed = greeting.split(b"Digest seed: ", 1)[1].split(b"\n", 1)[0].strip().decode()
        digest = hashlib.md5((seed + password).encode()).hexdigest()
        sock.sendall(f"\x02login {digest}\n".encode())
        out.append(_read_until(sock, b"\x04").decode("latin1").strip("\x04\n"))
        for cmd in commands:
            sock.sendall(f"\x02exec {cmd}\n".encode())
            out.append(_read_until(sock, b"\x04").decode("latin1").strip("\x04\n"))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=4711)
    ap.add_argument("--password", default="re")
    ap.add_argument("--reply-timeout", type=float, default=10.0, help="seconds to wait for each command's reply")
    ap.add_argument("commands", nargs="+")
    args = ap.parse_args(argv)
    for line in run(args.commands, args.host, args.port, args.password, args.reply_timeout):
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
