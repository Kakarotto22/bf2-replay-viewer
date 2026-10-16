"""Print the disassembly of every function whose symbol contains SUBSTRING (from re_work/ia32.asm).

usage: python scripts/asm_fn.py "world::Soldier::getIsSwimming(" [max_lines]
"""
import re, sys
sub, limit = sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 60
on = 0
for line in open("re_work/ia32.asm", encoding="latin1"):
    if re.match(r"^[0-9a-f]{8} <", line):
        on = limit if sub in line else 0
        if on: print(line.rstrip())
    elif on:
        print(line.rstrip()[:100]); on -= 1
