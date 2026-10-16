"""LSB-first bit stream reader/writer for Refractor 2 network data.

Refractor 2 serializes network events into a bit stream where the first bit
read from a byte is its least-significant bit, and multi-bit fields are
assembled with the first bit as the field's least-significant bit. Reading
eight bits therefore yields the byte value and reading 32 bits yields a
little-endian 32-bit integer, but reads may begin and end at arbitrary bit
offsets.

The reader never raises on exhaustion; it returns zero bits and marks the
stream as over-read so callers can detect corruption and stop cleanly.
"""

from __future__ import annotations

import struct
from typing import Optional, Tuple

Vec3 = Tuple[float, float, float]


class BitStreamError(Exception):
    """Raised for invalid stream construction."""


class BitStream:
    """A forward-only, LSB-first bit reader over a byte buffer."""

    __slots__ = ("_data", "_nbits", "_pos", "_overrun")

    def __init__(self, data: bytes, bit_pos: int = 0) -> None:
        if bit_pos < 0:
            raise BitStreamError("bit_pos must be non-negative")
        self._data = data
        self._nbits = len(data) * 8
        self._pos = bit_pos
        self._overrun = False

    # -- state -------------------------------------------------------------
    @property
    def bit_pos(self) -> int:
        return self._pos

    @property
    def bits_remaining(self) -> int:
        return self._nbits - self._pos

    @property
    def overrun(self) -> bool:
        """True if a read ran past the end of the buffer."""
        return self._overrun

    def at_end(self) -> bool:
        return self._pos >= self._nbits

    def align(self) -> int:
        """Advance to the next byte boundary; returns skipped bit count."""
        skip = (-self._pos) % 8
        if skip:
            self._pos += skip
        return skip

    # -- primitives --------------------------------------------------------
    def read_bits(self, count: int) -> int:
        """Read ``count`` bits LSB-first and return them as an integer."""
        if count < 0:
            raise BitStreamError("count must be non-negative")
        if count == 0:
            return 0
        pos = self._pos
        end = pos + count
        if end <= self._nbits:
            # fast path: one slice of the covering bytes, shifted to the start bit (no per-byte loop)
            self._pos = end
            return (int.from_bytes(self._data[pos >> 3:(end + 7) >> 3], "little") >> (pos & 7)) & ((1 << count) - 1)
        value = 0
        remaining = count
        out_shift = 0
        pos = self._pos
        data = self._data
        nbits = self._nbits
        while remaining > 0:
            if pos >= nbits:
                self._overrun = True
                self._pos = pos
                return value
            byte_index = pos >> 3
            bit_index = pos & 7
            avail = 8 - bit_index
            take = avail if avail < remaining else remaining
            mask = (1 << take) - 1
            chunk = (data[byte_index] >> bit_index) & mask
            value |= chunk << out_shift
            out_shift += take
            pos += take
            remaining -= take
        self._pos = pos
        return value

    def read_bool(self) -> bool:
        return self.read_bits(1) != 0

    def read_uint8(self) -> int:
        return self.read_bits(8)

    def read_uint16(self) -> int:
        return self.read_bits(16)

    def read_uint32(self) -> int:
        return self.read_bits(32)

    def read_int(self, count: int) -> int:
        """Read ``count`` bits as a two's-complement signed integer."""
        value = self.read_bits(count)
        sign_bit = 1 << (count - 1)
        if value & sign_bit:
            value -= 1 << count
        return value

    def read_float32(self) -> float:
        return struct.unpack("<f", self.read_bits(32).to_bytes(4, "little"))[0]

    def read_bytes(self, count: int) -> bytes:
        """Read ``count`` whole bytes (requires byte alignment for accuracy)."""
        raw = self.read_bits(count * 8)
        return raw.to_bytes(count, "little")

    def read_string8(self) -> str:
        """Read a length-prefixed (uint8 length) byte string."""
        length = self.read_uint8()
        return self.read_bytes(length).decode("latin1")

    def read_string32(self) -> str:
        """Read a length-prefixed (uint32 length) byte string."""
        length = self.read_uint32()
        return self.read_bytes(length).decode("latin1")

    # -- vectors -----------------------------------------------------------
    def read_vec3(self, mode: Optional[int] = None) -> Vec3:
        """Read a 3-component vector.

        Mode 0 is three raw 32-bit IEEE-754 floats. Modes 1-3 are quantized
        forms whose exact bounding box and sign/presence layout are supplied
        by the caller (see :func:`read_compressed_vector`). When ``mode`` is
        None it is read from the next two bits.
        """
        if mode is None:
            mode = self.read_bits(2)
        if mode == 0:
            return (self.read_float32(), self.read_float32(), self.read_float32())
        raise BitStreamError(f"unsupported vec3 mode {mode}")

    def read_compressed_vector(self, mode: int) -> Vec3:
        """Quantized vector modes 1-3 (layout pinned during RE verification)."""
        raise BitStreamError(f"compressed vec3 mode {mode} not yet verified")

    # -- writer ------------------------------------------------------------
    def write_bits(self, value: int, count: int) -> None:
        """Append ``count`` bits LSB-first (used by tests/fixtures)."""
        if count < 0:
            raise BitStreamError("count must be non-negative")
        if self._pos != self._nbits:
            raise BitStreamError("writer only supports append-only buffers")
        if count == 0:
            return
        byte_index = self._nbits >> 3
        bit_index = self._nbits & 7
        total = bit_index + count
        need = (total + 7) // 8
        buf = bytearray(self._data) + bytearray(need)
        pos = self._nbits
        for i in range(count):
            if (value >> i) & 1:
                buf[pos >> 3] |= 1 << (pos & 7)
            pos += 1
        self._data = bytes(buf)
        self._nbits = pos
        self._pos = pos
