"""Print the interesting lines (calls, field accesses) of a game event class from the dedicated server disassembly.

usage: python scripts/event_asm.py MissileInitEvent [deSerialize executeClient ...]   (re_work/ia32.asm = objdump of bf2_ia32)
"""
import re, sys
ASM = "re_work/ia32.asm"
cls, methods = sys.argv[1], sys.argv[2:] or ["deSerialize", "executeClient"]
want = [re.compile(r"^[0-9a-f]+ <dice::hfe::" + re.escape(cls) + "::" + m + r"\(") for m in methods]
cur = None
for line in open(ASM, encoding="latin1"):
    if re.match(r"^[0-9a-f]{8} <", line):
        cur = next((m for m, w in zip(methods, want) if w.match(line)), None)
        if cur: print("\n==", line.strip()[:150])
        continue
    if not cur: continue
    t = line.split("\t", 2)
    if len(t) < 2: continue
    ins = t[1].strip()
    if ins.startswith("call"):
        print("  call", re.sub(r"std::(allocator|char_traits)<[^>]*>", "", ins[4:].strip())[:130])
    elif re.search(r"0x[0-9a-f]+\(%e[a-z]{2}\)", ins) and not ins.startswith(("lea", "push", "cmp")):
        print("   ", ins[:90])
