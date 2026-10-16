"""Behaviour check of the viewer on an emulated phone with real touch events (needs aiohttp and Edge / Chrome):

    python -X utf8 scripts/phone_check.py http://127.0.0.1:8080 DEMO_ID out.png

Checks: no horizontal overflow, no resize storm, touch-and-hold shows the name and letting go hides it, dragging pans, full screen mode, six rotations.
"""
import asyncio, json, subprocess, sys, os, base64, urllib.request, aiohttp
EDGE = os.environ.get("BF2_BROWSER") or r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
base, did = sys.argv[1], sys.argv[2]; out = sys.argv[3]
here = os.path.dirname(os.path.abspath(__file__)); prof = os.path.join(here, "pt.profile"); port = 9466
results = []
def check(name, ok, detail=""):
    results.append(ok); print(("PASS " if ok else "FAIL ") + name + (("  -> " + str(detail)) if detail != "" else ""))
async def main():
    for _ in range(50):
        try: tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json")); break
        except Exception: await asyncio.sleep(0.2)
    ws_url = [t for t in tabs if t["type"] == "page"][0]["webSocketDebuggerUrl"]
    errors = []
    async with aiohttp.ClientSession() as s, s.ws_connect(ws_url, max_msg_size=0) as ws:
        n = 0; pend = {}
        async def reader():
            async for m in ws:
                d = json.loads(m.data)
                if "id" in d and d["id"] in pend: pend[d["id"]].set_result(d)
                elif d.get("method") == "Runtime.exceptionThrown": errors.append(d["params"]["exceptionDetails"].get("exception", {}).get("description", "exception")[:200])
        task = asyncio.create_task(reader())
        async def call(method, **params):
            nonlocal n; n += 1; i = n; f = asyncio.get_event_loop().create_future(); pend[i] = f
            await ws.send_json({"id": i, "method": method, "params": params}); r = await f; return r.get("result", r)
        async def js(expr): 
            r = await call("Runtime.evaluate", expression=expr, awaitPromise=True, returnByValue=True); return r["result"].get("value")
        async def touch(kind, pts): await call("Input.dispatchTouchEvent", type=kind, touchPoints=[{"x": x, "y": y, "id": i} for i, (x, y) in enumerate(pts)])
        async def metrics(w, h, dpr=2.625): await call("Emulation.setDeviceMetricsOverride", width=w, height=h, deviceScaleFactor=dpr, mobile=True)
        await call("Page.enable"); await call("Runtime.enable")
        await metrics(412, 780); await call("Emulation.setTouchEmulationEnabled", enabled=True)
        await call("Page.navigate", url=f"{base}/#/demo/{did}?t=300"); await asyncio.sleep(10)
        # A. layout and idle stability
        r1 = await js("JSON.stringify([bf2.PERF.resizes, document.documentElement.scrollWidth, innerWidth, document.getElementById('timeline').width])")
        await asyncio.sleep(4); r2 = await js("JSON.stringify([bf2.PERF.resizes])")
        a = json.loads(r1); b = json.loads(r2)
        check("no horizontal overflow", a[1] <= a[2], f"scrollWidth {a[1]} vs {a[2]}")
        check("timeline canvas has a sane width", 300 < a[3] < 1400, a[3])
        check("no resize storm while idle (4 s)", b[0] == a[0], f"{a[0]} -> {b[0]}")
        # B. press-and-hold tip
        spot = await js("""(()=>{const cv=document.getElementById('map'), r=cv.getBoundingClientRect();
          for (let y=r.height*0.1;y<r.height*0.95;y+=6) for (let x=r.width*0.1;x<r.width*0.95;x+=6) { const t=bf2.pick(x,y,22); if (t && t.kind==='soldier') return JSON.stringify([r.left+x, r.top+y]); }
          for (let y=r.height*0.1;y<r.height*0.95;y+=6) for (let x=r.width*0.1;x<r.width*0.95;x+=6) { if (bf2.pick(x,y,22)) return JSON.stringify([r.left+x, r.top+y]); } return null})()""")
        check("found a unit to press", spot is not None)
        if spot:
            x, y = json.loads(spot)
            await touch("touchStart", [(x, y)]); await asyncio.sleep(0.3)
            shown = await js("JSON.stringify([!document.getElementById('tip').hidden, document.getElementById('tip').innerText.length])")
            check("the name shows while the finger is down", json.loads(shown)[0] and json.loads(shown)[1] > 0, shown)
            await touch("touchEnd", []); await asyncio.sleep(0.3)
            check("the name disappears when the finger lifts", await js("document.getElementById('tip').hidden"))
            await touch("touchStart", [(x, y)]); await asyncio.sleep(0.2)
            for k in range(1, 8): await touch("touchMove", [(x + k * 8, y)]); await asyncio.sleep(0.03)
            check("dragging hides the name (it is a pan)", await js("document.getElementById('tip').hidden"))
            await touch("touchEnd", []); await asyncio.sleep(0.2)
            check("the map did pan", await js("bf2.S.view.cx !== 0"))
        # C. full screen
        h0 = await js("document.getElementById('mapWrap').getBoundingClientRect().height")
        c0 = await js("bf2.PERF.resizes")
        await js("document.getElementById('btnFull').click()"); await asyncio.sleep(1.2)
        st = json.loads(await js("JSON.stringify({imm: document.body.classList.contains('immersive'), top: getComputedStyle(document.getElementById('topbar')).display, right: getComputedStyle(document.getElementById('right')).display, h: document.getElementById('mapWrap').getBoundingClientRect().height, res: bf2.PERF.resizes, sw: document.documentElement.scrollWidth, btn: document.getElementById('btnFull').textContent})"))
        check("full screen hides top bar and panels", st["imm"] and st["top"] == "none" and st["right"] == "none", st)
        check("the map gets much taller", st["h"] > h0 * 1.6, f"{h0:.0f} -> {st['h']:.0f}")
        check("only a few canvas rebuilds for the toggle", st["res"] - c0 <= 3, st["res"] - c0)
        check("no overflow in full screen", st["sw"] <= 412)
        shot = await call("Page.captureScreenshot", format="png"); open(out, "wb").write(base64.b64decode(shot["data"]))
        await js("document.getElementById('btnFull').click()"); await asyncio.sleep(1)
        check("leaving full screen restores the layout", await js("getComputedStyle(document.getElementById('topbar')).display") != "none")
        # D/E. rotation storm
        c1 = await js("bf2.PERF.resizes")
        for k in range(6):
            await metrics(780, 412) if k % 2 == 0 else await metrics(412, 780); await asyncio.sleep(0.4)
        await asyncio.sleep(1.5)
        after = json.loads(await js("JSON.stringify({res: bf2.PERF.resizes, sw: document.documentElement.scrollWidth, iw: innerWidth, tl: document.getElementById('timeline').width, mp: document.getElementById('map').width})"))
        check("six rotations: no overflow", after["sw"] <= after["iw"], after)
        check("six rotations: canvases stay sane", after["tl"] < 1400 and after["mp"] < 1400, after)
        check("six rotations: a bounded number of rebuilds", after["res"] - c1 <= 14, after["res"] - c1)
        check("no script errors", not errors, errors[:3])
        task.cancel()
    print(f"{sum(results)}/{len(results)} checks passed")
proc = subprocess.Popen([EDGE, "--headless=new", "--disable-gpu", f"--remote-debugging-port={port}", f"--user-data-dir={prof}", "--no-first-run", "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try: asyncio.run(main())
finally: proc.terminate()
