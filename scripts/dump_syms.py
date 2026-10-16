"""Development helper: dump serialization symbols from the bf2_ia32 ELF.

This is a build/reverse-engineering aid, not part of the runtime parser. It
parses the ELF symbol table (``.symtab`` / ``.strtab``) of the provided binary
and prints matching symbols so event ``deSerialize``/``serialize`` functions
can be located for verification in Ghidra/REA.

Usage::

    python scripts/dump_syms.py extracted_bin/bf2_ia32 [keyword ...]

With no keywords a small default set of event/BitStream terms is used.
"""

from __future__ import annotations

import struct
import sys

DEFAULT_KEYWORDS = (
    "Event",
    "deSerialize",
    "serialize",
    "BitStream",
    "ControlPoint",
    "SpawnPoint",
    "DemoHeader",
)


def _read_shdr(data: bytes, is64: bool) -> dict:
    if is64:
        e_shoff = struct.unpack_from("<Q", data, 0x28)[0]
        e_shentsize = struct.unpack_from("<H", data, 0x3A)[0]
        e_shnum = struct.unpack_from("<H", data, 0x3C)[0]
        e_shstrndx = struct.unpack_from("<H", data, 0x3E)[0]
    else:
        e_shoff = struct.unpack_from("<I", data, 0x20)[0]
        e_shentsize = struct.unpack_from("<H", data, 0x2E)[0]
        e_shnum = struct.unpack_from("<H", data, 0x30)[0]
        e_shstrndx = struct.unpack_from("<H", data, 0x32)[0]
    sections = []
    for i in range(e_shnum):
        off = e_shoff + i * e_shentsize
        if is64:
            fields = struct.unpack_from("<IIQQQQIIQQ", data, off)
        else:
            fields = struct.unpack_from("<IIIIIIIIII", data, off)
        name, sh_type, _flags, _addr, offset, size, _link, _info, _align, entsize = fields
        sections.append(
            {
                "name_off": name,
                "type": sh_type,
                "offset": offset,
                "size": size,
                "entsize": entsize,
            }
        )
    return {"sections": sections, "shstrndx": e_shstrndx}


def dump_symbols(path: str):
    data = open(path, "rb").read()
    if data[:4] != b"\x7fELF":
        raise ValueError("not an ELF file")
    is64 = data[4] == 2
    info = _read_shdr(data, is64)
    sections = info["sections"]

    def section_name(idx):
        shstr = sections[info["shstrndx"]]
        base = shstr["offset"] + sections[idx]["name_off"]
        end = data.find(b"\x00", base)
        return data[base:end].decode("latin1")

    symtab_idx = next(i for i, s in enumerate(sections) if section_name(i) == ".symtab")
    strtab_idx = next(i for i, s in enumerate(sections) if section_name(i) == ".strtab")
    symtab = sections[symtab_idx]
    strtab = sections[strtab_idx]

    def sym_name(off):
        base = strtab["offset"] + off
        end = data.find(b"\x00", base)
        return data[base:end].decode("latin1", "replace")

    count = symtab["size"] // symtab["entsize"]
    out = []
    for i in range(count):
        off = symtab["offset"] + i * symtab["entsize"]
        if is64:
            st_name, st_value, st_size, st_info, _other, st_shndx = struct.unpack_from(
                "<IBBHQQ", data, off
            )
        else:
            st_name, st_value, st_size, st_info, _other, st_shndx = struct.unpack_from(
                "<IIIBBH", data, off
            )
        out.append((st_value, st_size, sym_name(st_name)))
    return out


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    path = argv[1]
    keywords = argv[2:] or list(DEFAULT_KEYWORDS)
    symbols = dump_symbols(path)
    print(f"{len(symbols)} symbols in {path}")
    for kw in keywords:
        hits = [s for s in symbols if kw.lower() in s[2].lower()]
        print(f"\n=== {kw} ({len(hits)}) ===")
        for value, size, name in hits:
            print(f"  0x{value:08x} {size:6d}  {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
