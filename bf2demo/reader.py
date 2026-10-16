"""Demo container reader: Zlib streaming, header parsing, packet framing.

The ``.bf2demo`` container is a Zlib stream. Once inflated, it begins with a
fixed header (an ``int32`` engine version followed by three length-prefixed
strings) and is then a sequence of packets framed as ``<ii`` = ``(tick,
payload_length)`` followed by ``payload_length`` raw bytes.

Dirty or truncated recordings are recovered by salvaging as much of the Zlib
stream as possible; parsing then stops at the first incomplete packet.
"""

from __future__ import annotations

import struct
import zlib
from typing import List, Optional, Tuple

from .models import Demo, DemoHeader, DemoPacket

# Header sanity bounds (guards against mis-detecting a corrupt stream).
_MAX_HEADER_STRING = 1 << 20
_PACKET_HEADER = struct.Struct("<ii")
_INFLATE_CHUNK = 1 << 16


def inflate(data: bytes) -> Tuple[bytes, bool]:
    """Inflate a Zlib stream, salvaging as much as possible.

    Returns ``(output, recovered)`` where ``recovered`` is True when the stream
    could not be fully inflated and the output is a salvaged prefix.
    """
    try:
        return zlib.decompress(data), False
    except zlib.error:
        pass

    dec = zlib.decompressobj()
    out = bytearray()
    total = len(data)
    offset = 0
    while offset < total:
        end = min(offset + _INFLATE_CHUNK, total)
        try:
            out += dec.decompress(data[offset:end])
            offset = end
        except zlib.error:
            # Rebuild the inflater over the known-good prefix, then advance
            # byte-by-byte to squeeze out every recoverable byte.
            dec = zlib.decompressobj()
            out = bytearray()
            pos = 0
            while pos < offset:
                end2 = min(pos + _INFLATE_CHUNK, offset)
                out += dec.decompress(data[pos:end2])
                pos = end2
            pos = offset
            while pos < total:
                try:
                    out += dec.decompress(data[pos : pos + 1])
                except zlib.error:
                    break
                pos += 1
            return bytes(out), True

    try:
        out += dec.flush()
    except zlib.error:
        return bytes(out), True
    return bytes(out), False


def _read_i32(buf: bytes, offset: int) -> Tuple[int, int]:
    return struct.unpack_from("<i", buf, offset)[0], offset + 4


def _read_lpstring(buf: bytes, offset: int) -> Tuple[str, int]:
    length, offset = _read_i32(buf, offset)
    if length < 0 or length > _MAX_HEADER_STRING:
        raise ValueError(f"implausible header string length {length}")
    if offset + length > len(buf):
        raise ValueError("header string runs past end of stream")
    text = buf[offset : offset + length].decode("latin1")
    return text, offset + length


def parse_stream(stream: bytes, recovered: bool = False) -> Demo:
    """Parse an inflated demo stream into a :class:`Demo`."""
    if len(stream) < 4:
        raise ValueError("stream too short for a demo header")

    offset = 0
    version, offset = _read_i32(stream, offset)
    server_name, offset = _read_lpstring(stream, offset)
    recorded_at, offset = _read_lpstring(stream, offset)
    map_name, offset = _read_lpstring(stream, offset)

    header = DemoHeader(
        version=version,
        server_name=server_name,
        recorded_at=recorded_at,
        map_name=map_name,
    )

    packets: List[DemoPacket] = []
    truncated = False
    index = 0
    total = len(stream)
    while offset + _PACKET_HEADER.size <= total:
        tick, length = _PACKET_HEADER.unpack_from(stream, offset)
        body_start = offset + _PACKET_HEADER.size
        if length < 0 or body_start + length > total:
            truncated = True
            break
        packets.append(DemoPacket(index=index, tick=tick, data=stream[body_start : body_start + length]))
        index += 1
        offset = body_start + length

    trailing = total - offset
    notes: List[str] = []
    if recovered:
        notes.append("Zlib stream was partially recovered; packet stream may be truncated.")
    if truncated:
        notes.append("Final packet was incomplete and was dropped.")

    return Demo(
        header=header,
        packets=packets,
        truncated=truncated,
        trailing_bytes=trailing,
        recovered=recovered,
        notes=notes,
    )


def load_demo(path: str) -> Demo:
    """Load and parse a ``.bf2demo`` file from disk."""
    with open(path, "rb") as handle:
        raw = handle.read()
    stream, recovered = inflate(raw)
    return parse_stream(stream, recovered=recovered)


def load_demo_bytes(raw: bytes) -> Demo:
    """Load and parse a ``.bf2demo`` image already held in memory."""
    stream, recovered = inflate(raw)
    return parse_stream(stream, recovered=recovered)
