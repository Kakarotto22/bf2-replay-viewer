# Contributing

Thanks for helping. Please:

* **Do not add game content**: no textures, icons, fonts, maps, level files, sounds, game executables or decompiler output (see `NOTICE.md`).
* **Do not add recordings with real player names** unless the players and the server owner agreed; record your own on a test server instead.
* Every decoded field needs evidence (a recording that checks it bit for bit, or a documented reading of the game's behaviour). Mark unknown
  fields visibly (`unk_*`, `flag_*`) instead of guessing. `scripts/bit_coverage.py DEMO` must stay at 100 %.
* Run the tests: `python -m unittest discover -s tests -t .` (tests that need a missing recording are skipped).
* Code, comments and commit messages in English.
