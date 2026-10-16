# Security policy

The viewer runs on public servers, so security reports are welcome and taken seriously.

**Report privately, please:** write to the maintainer on Telegram (see the *Support* section of [README.md](README.md)) or use GitHub's
*Report a vulnerability* button of this repository. Include the steps to reproduce and, if you can, a recording that triggers it. Please do not open a
public issue before a fix is out.

**What the project already does** (and tests in `tests/test_web_security.py`):

* no file outside the viewer's own folders can be read or written (names are checked, not only cleaned);
* a content security policy allows only the site's own scripts, so a name inside a recording cannot run code;
* recordings are limited when decompressed, uploads are off by default, limited per visitor and cleaned by a storage quota;
* errors shown to visitors never contain server paths.

**Out of scope:** the game itself, EA's servers, and any recording you chose to publish.
