"""Bit-level readers shared by the object networkable decoders.

All of them mirror ``dice::hfe::io::BitStream`` of the 1.5.3153 server (addresses in the docstrings) and
return the decoded value together with the information needed to check that a ghost record is consumed
exactly. Compressed vectors are read *relative to an origin* in the game (the previous / baseline value);
callers that do not track baselines pass ``origin=None`` and get the raw delta units instead.
"""

from __future__ import annotations

import math
from typing import Optional, Tuple

from .bitstream import BitStream

Vec3 = Tuple[float, float, float]

#: ``BitStream::m_compressionVectorBitTable`` (0x0898cb64) and ``...Table2`` (0x0898cba0).
TABLE1 = (32, 20, 16, 12)
TABLE2 = (28, 24, 20, 16, 12, 10, 8, 0)
#: ``m_highCompressionVectorBitTable`` (0x0898cb74), used by ``readHighCompressedVector`` 0x08433260.
TABLE_HIGH = (32, 12, 10, 8)


def width_for(max_value: int) -> int:
    """Bits needed for values ``0..max_value`` (the ``while ((1 << n) - 1 < max)`` loop used everywhere)."""
    n = 0
    if max_value:
        while (1 << n) - 1 < max_value:
            n += 1
    return n


def _signed_components(bs: BitStream, bits: int):
    out = []
    for _ in range(3):
        negative = bs.read_bits(1) == 1
        magnitude = bs.read_bits(bits)
        out.append(-magnitude if negative else magnitude)
    return out


def _raw_vec(bs: BitStream) -> Vec3:
    import struct
    vals = []
    for _ in range(3):
        vals.append(struct.unpack("<f", struct.pack("<I", bs.read_bits(32)))[0])
    return tuple(vals)  # type: ignore[return-value]


def read_compressed_vector(bs: BitStream, scale: float, origin: Optional[Vec3] = None):
    """``readCompressedVector`` 0x08432d30: mode(2); 0 raw floats; else 3 x (sign + table1[mode]-1 bits) * scale + origin."""
    mode = bs.read_bits(2)
    if mode == 0:
        return _raw_vec(bs)
    comps = _signed_components(bs, TABLE1[mode] - 1)
    base = origin or (0.0, 0.0, 0.0)
    return tuple(scale * c + o for c, o in zip(comps, base))


def read_high_compressed_vector(bs: BitStream, scale: float, origin: Optional[Vec3] = None):
    """``readHighCompressedVector``: like ``readCompressedVector`` with the coarse table (12/10/8 bits)."""
    mode = bs.read_bits(2)
    if mode == 0:
        return _raw_vec(bs)
    comps = _signed_components(bs, TABLE_HIGH[mode] - 1)
    base = origin or (0.0, 0.0, 0.0)
    return tuple(scale * c + o for c, o in zip(comps, base))


def read_compressed_vector2(bs: BitStream, scale: float, origin: Optional[Vec3] = None):
    """``readCompressedVector2`` 0x08433820: mode(3); 0 raw floats; 7 = ``origin`` unchanged; else table2."""
    mode = bs.read_bits(3)
    if mode == 0:
        return _raw_vec(bs)
    base = origin or (0.0, 0.0, 0.0)
    if mode == 7:
        return base
    comps = _signed_components(bs, TABLE2[mode] - 1)
    return tuple(scale * c + o for c, o in zip(comps, base))


def read_unit_quaternion(bs: BitStream, bits: int = 14):
    """``readUnitQuaternion`` 0x08431d60: x, y, z, w each ``bits`` bits mapped to [-1, 1], then normalised."""
    vals = []
    for _ in range(4):
        raw = bs.read_bits(bits)
        vals.append(raw / ((1 << bits) - 1) * 2.0 - 1.0)
    w, x, y, z = vals              # the function stores the first value at +0xc (w), then x, y, z
    length = math.sqrt(x * x + y * y + z * z + w * w)
    if length >= 1e-3:
        return (x / length, y / length, z / length, w / length)
    return (0.0, 0.0, 0.0, 1.0)
