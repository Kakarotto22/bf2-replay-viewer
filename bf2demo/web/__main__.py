"""``python -m bf2demo.web --demos DIR [--demos DIR2] [--port 8080]``"""

from __future__ import annotations

import argparse

from .app import create_app


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="bf2demo.web", description="Browser viewer for .bf2demo recordings.")
    parser.add_argument("--demos", action="append", default=[], metavar="DIR",
                        help="folder searched (recursively) for .bf2demo files; repeatable")
    parser.add_argument("--maps", action="append", default=[], metavar="DIR",
                        help="folder with your own high resolution maps named <level>.jpg or <level>.png (e.g. BF2 Editor mega map renders); repeatable")
    parser.add_argument("--cache", metavar="DIR", help="parse cache folder (default: ~/.bf2demo-viewer-cache)")
    parser.add_argument("--build-assets", action="store_true",
                        help="build the viewer's own asset store from your game install now (icons, fonts, names: ~0.3 MB) and exit")
    parser.add_argument("--no-upload", action="store_true", help="refuse uploads (use this when the viewer is reachable by others)")
    parser.add_argument("--max-parse", type=int, default=2, metavar="N", help="recordings parsed at the same time (default 2)")
    parser.add_argument("--donate-telegram", metavar="@NAME", help="Telegram username shown in the support section (hidden when not given)")
    parser.add_argument("--donate-file", metavar="FILE", help="JSON file with the payment methods of the support section (wallets, payment links); see deploy/donate.example.json")
    parser.add_argument("--warm", action="store_true", help="parse every recording of --demos now (one after the other) and exit: run it when publishing so visitors never wait")
    parser.add_argument("--behind-proxy", action="store_true", help="a reverse proxy (Caddy, nginx) is in front: take the visitor's address from X-Forwarded-For for the rate limits")
    parser.add_argument("--host", default="127.0.0.1", help="bind address (default: local only)")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args(argv)
    if args.build_assets:
        import os
        from . import maps
        from .assets import GameAssets
        cache = args.cache or os.path.join(os.path.expanduser("~"), ".bf2demo-viewer-cache")
        root = maps.game_root()
        if root is None:
            print("no Battlefield 2 install found (set BF2_GAME_ROOT)")
            return 1
        print(GameAssets(root, os.path.join(os.path.abspath(cache), "game")).build_store())
        return 0
    app = create_app(args.demos, args.cache, args.maps, allow_upload=not args.no_upload, max_parse=args.max_parse,
                     donate_telegram=args.donate_telegram, donate_file=args.donate_file, behind_proxy=args.behind_proxy)
    if args.warm:
        done = app.config["STORE"].warm()
        print(f"{done} recording(s) parsed")
        return 0
    print(f"bf2demo viewer on http://{args.host}:{args.port}/")
    app.run(host=args.host, port=args.port, threaded=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
