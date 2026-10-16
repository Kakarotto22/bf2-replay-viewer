"""List member functions of a class that read/write a given object offset (to name decoded ghost fields).

usage: python scripts/field_owners.py dice::hfe::Player 0x24c 0x11c ...   (needs re_work/ia32.asm)
Short accessors (<= 14 instructions) are marked with '*': those are the getters/setters that carry the field's real name.
"""
import re, sys
prefix, offsets = sys.argv[1], [int(x, 16) for x in sys.argv[2:]]
pats = {o: re.compile(r"[ ,]0x%x\(%%e[a-z]{2}\)" % o) for o in offsets}
hits = {o: [] for o in offsets}
name, body, seen = None, 0, set()
def flush():
    for o in seen: hits[o].append((name, body))
for line in open("re_work/ia32.asm", encoding="latin1"):
    if re.match(r"^[0-9a-f]{8} <", line):
        if name and name.startswith("<" + prefix + "::"): flush()
        name, body, seen = line.split(" ", 1)[1].strip().rstrip(":"), 0, set()
        continue
    body += 1
    if name and name.startswith("<" + prefix + "::"):
        for o, p in pats.items():
            if p.search(line): seen.add(o)
if name and name.startswith("<" + prefix + "::"): flush()
for o in offsets:
    print(f"\n0x{o:x}")
    for n, size in sorted(set(hits[o]), key=lambda t: t[1]):
        print(("  * " if size <= 14 else "    ") + n[:110].lstrip("<"), size)
