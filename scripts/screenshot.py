"""Take a screenshot of the running viewer with headless Edge / Chrome (optionally as a phone). Needs ``pip install aiohttp``.

    python scripts/screenshot.py "http://127.0.0.1:8080/#/demo/<id>?t=900" out.png                      # desktop 1440 x 900
    python scripts/screenshot.py "http://127.0.0.1:8080/#/demo/<id>?t=900&board=1" board.png --size 1440x900
    python scripts/screenshot.py "http://127.0.0.1:8080/#/demo/<id>?t=900" phone.png --phone              # 390 x 844 at 2x, touch
    python scripts/screenshot.py "http://127.0.0.1:8080/?lang=ar#/demo/<id>?t=900" phone-ar.png --phone

The page is opened through the browser's DevTools protocol, so the phone mode is a real emulated device (viewport, pixel ratio, touch), not
just a narrow window. ``--wait`` is the time in seconds to let the recording load and the artwork arrive (a long round needs more).
Pick the browser with ``--browser PATH`` or the environment variable ``BF2_BROWSER``.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request

CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe", r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe", "/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
]


def find_browser(explicit: str | None) -> str:
    for path in [explicit, os.environ.get("BF2_BROWSER"), *CANDIDATES, shutil.which("chromium"), shutil.which("google-chrome"), shutil.which("msedge")]:
        if path and os.path.isfile(path):
            return path
    raise SystemExit("no Edge / Chrome found: pass --browser PATH or set BF2_BROWSER")


async def shoot(args, port: int) -> None:
    import aiohttp
    for _ in range(100):
        try:
            tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json"))
            break
        except OSError:
            await asyncio.sleep(0.2)
    else:
        raise SystemExit("the browser did not start")
    ws_url = next(t["webSocketDebuggerUrl"] for t in tabs if t["type"] == "page")
    width, height = (390, 844) if args.phone else tuple(int(v) for v in args.size.lower().split("x"))
    async with aiohttp.ClientSession() as session, session.ws_connect(ws_url, max_msg_size=0) as ws:
        counter = 0

        async def call(method, **params):
            nonlocal counter
            counter += 1
            mine = counter
            await ws.send_json({"id": mine, "method": method, "params": params})
            while True:
                message = await ws.receive_json()
                if message.get("id") == mine:
                    return message.get("result", message)

        await call("Page.enable")
        await call("Emulation.setDeviceMetricsOverride", width=width, height=height, deviceScaleFactor=args.dpr or (2 if args.phone else 1), mobile=args.phone)
        await call("Emulation.setTouchEmulationEnabled", enabled=args.phone)
        await call("Page.navigate", url=args.url)
        await asyncio.sleep(args.wait)
        shot = await call("Page.captureScreenshot", format="png")
        with open(args.out, "wb") as fh:
            fh.write(base64.b64decode(shot["data"]))
    print(f"{args.out}: {width}x{height}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Screenshot of the viewer with headless Edge / Chrome.")
    parser.add_argument("url")
    parser.add_argument("out")
    parser.add_argument("--size", default="1440x900", help="WIDTHxHEIGHT of a desktop window (default 1440x900)")
    parser.add_argument("--phone", action="store_true", help="emulate a 390 x 844 phone with touch at 2x")
    parser.add_argument("--dpr", type=float, default=0, help="device pixel ratio (default 1, phone 2)")
    parser.add_argument("--wait", type=float, default=12, help="seconds to wait before the shot (default 12)")
    parser.add_argument("--browser", help="path of msedge / chrome / chromium")
    args = parser.parse_args()
    port = 9400 + os.getpid() % 500
    profile = tempfile.mkdtemp(prefix="bf2shot-")
    process = subprocess.Popen([find_browser(args.browser), "--headless=new", "--disable-gpu", f"--remote-debugging-port={port}", f"--user-data-dir={profile}",
                                "--no-first-run", "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        asyncio.run(shoot(args, port))
    finally:
        process.terminate()
        shutil.rmtree(profile, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
