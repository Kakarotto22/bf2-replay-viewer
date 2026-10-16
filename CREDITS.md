# Credits and sources

Everything in `bf2demo/` was written for this project from the behaviour of the game's own programs and from recordings. Where a public source
helped, it is listed here. Licenses are those the projects declare on their pages at the time of writing.

## Reference material and cross-checks (not copied)

| source | license | how it was used |
|---|---|---|
| [OpenBattlefield2](https://github.com/Moxnatiy/OpenBattlefield2) (Moxnatiy) | MIT | an independent reverse-engineering effort of the same game version; its notes on the network protocol, events and score manager were used to cross-check our decoders. No code was copied. |
| [Refractor 2 BitStream Emulator](https://github.com/matthias-hoste/Refractor-2-BitStream-Emulator) (matthias-hoste) | GPL-3.0 | read as a reference for the bit order of the engine's bit stream; that project credits **aluigi**'s *BF2Loop* for the original read / write routines. `bf2demo/bitstream.py` is an independent Python implementation written from the game's programs; no code of that project is included. |
| [BF2 technical reference](https://bftech.darkstormstudios.co.uk/) | n/a | documentation of file formats and of the game's Python / console interface. |

## Thanks

This project stands on the work and generosity of others:

* **[BF2Rangers](https://bf2rangers.wixsite.com/site)** - the Battlefield 2 community and server (played through GameRanger) whose rounds were
  the real-world test material: their recordings, many players and long matches showed what the decoder had to handle. Their recordings are used
  privately for validation and are **not** redistributed here. Thank you for keeping the game alive and for the matches.
* **[kr4uzi / gamespy-emulator](https://github.com/kr4uzi/gamespy-emulator)** - a reverse-engineered GameSpy emulator with native Battlefield 2
  support. Emulators like it are what let the game's servers run again; no code of it is included here (its repository declares no license).
* **[Moxnatiy](https://github.com/Moxnatiy)** (OpenBattlefield2), **[matthias-hoste](https://github.com/matthias-hoste)** (Refractor 2 BitStream Emulator)
  and **aluigi** (BF2Loop): the independent reverse-engineering notes and bit-stream work that confirmed our decoders.
* **The authors of [bftech.darkstormstudios.co.uk](https://bftech.darkstormstudios.co.uk/)** - the BF2 technical reference.
* **The author of the *High Definition Minimap* pack (ModDB)** - the sharp level renders the viewer can use when you download them yourself.
* **2F4Y.com** - for the public archive of recordings that helped to test long, crowded rounds.
* **The Ghidra, Flask, Pillow and gunicorn teams** - the open-source tools this project is built with.
* **DICE and EA** - for making *Battlefield 2* (this project is not affiliated with them).

If you are listed here and would like different wording, or you are missing, please open an issue.

## Bundled third-party code

* [qrcode-generator](https://github.com/kazuhikoarase/qrcode-generator) 1.4.4 by Kazuhiko Arase (MIT) in `bf2demo/web/static/js/vendor/`: draws the QR codes of the
  support dialog in the browser. Its license text is next to it. *QR Code* is a registered trademark of DENSO WAVE INCORPORATED.

## Tools used (not included)

* [Ghidra](https://ghidra-sre.org/) (NSA, Apache-2.0) for static analysis; `scripts/ghidra/*.java` are small scripts for it.
* The parser uses only the Python standard library. The viewer uses [Flask](https://flask.palletsprojects.com/) (BSD-3-Clause),
  [Pillow](https://python-pillow.org/) (HPND) and, on a server, [gunicorn](https://gunicorn.org/) (MIT): installed with pip, not bundled.

## Optional third-party content (never bundled)

* *High Definition Minimap* pack (ModDB): 8192 px renders of the game's levels. The viewer can use it if **you** download it from its author
  and run `scripts/import_hd_maps.py`. It is not part of this repository and is not mirrored by it. Please credit and thank its author.
* Maps, icons, fonts and level data: the property of EA and its licensors, read from your own copy of the game (see `NOTICE.md`).

## Author and support

By Kakarotto. If this project helped you, you can support it: see the *Support* section of `README.md`.
