"""Development helper: decompile functions from the analysed Ghidra project.

Runs Ghidra headless (read-only, no re-analysis) against the persistent project
in ``re_work/ghidra`` and dumps C for each selector via
``scripts/ghidra/DumpDecomp.java``.

Usage::

    python scripts/decomp.py [--program bf2_ia32] OUT.c SELECTOR [SELECTOR ...]

Selectors are ``0x`` addresses, name substrings, or ``=ExactName``. Requires
``GHIDRA_INSTALL_DIR`` (default: the path REA reports) and a JDK 21
``JAVA_HOME``.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_DIR = os.path.join(ROOT, "re_work", "ghidra")
SCRIPT_DIR = os.path.join(ROOT, "scripts", "ghidra")
GHIDRA = os.environ.get("GHIDRA_INSTALL_DIR", r"<ghidra install folder>")
JAVA_HOME = os.environ.get("JAVA_HOME_21", r"C:\src\jdk-21.0.12.1")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--program", default="bf2_ia32", help="bf2_ia32 (server, symbols) or BF2.exe (client)")
    ap.add_argument("--script", default="DumpDecomp.java",
                    help="DumpDecomp.java (selectors = functions) or FindStringRefs.java (selectors = strings)")
    ap.add_argument("--timeout", type=int, default=None, help="per-function decompiler timeout in seconds")
    ap.add_argument("out")
    ap.add_argument("selectors", nargs="+")
    args = ap.parse_args(argv)

    env = dict(os.environ, JAVA_HOME=JAVA_HOME)
    cmd = [
        os.path.join(GHIDRA, "support", "analyzeHeadless.bat"),
        PROJECT_DIR, "bf2",
        "-process", args.program, "-noanalysis", "-readOnly",
        "-scriptPath", SCRIPT_DIR,
        "-postScript", args.script, os.path.abspath(args.out), "+".join(args.selectors),
    ]
    if args.timeout:
        cmd.append(str(args.timeout))
    proc = subprocess.run(cmd, env=env, stdin=subprocess.DEVNULL,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if proc.returncode != 0 or not os.path.isfile(args.out):
        sys.stderr.write(proc.stdout[-4000:])
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
