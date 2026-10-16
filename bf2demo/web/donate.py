"""The support section: a Telegram username plus any number of payment methods (crypto wallets, payment links, plain text), each with an optional QR code.

The owner writes them once in a JSON file (``--donate-file`` / ``BF2VIEW_DONATE_FILE``, example: ``deploy/donate.example.json``)::

    {"telegram": "@name",
     "methods": [{"label": "USDT", "network": "TRC20", "address": "T..."},
                 {"label": "PayPal", "url": "https://paypal.me/name"},
                 {"label": "Bank transfer", "kind": "text", "note": "IBAN ... (write to me on Telegram first)"}]}

A wallet address with a typo sends money nowhere, so everything is checked when the server starts: an address must match the format of its
network (when the network is one we know) and a link must be ``https``. A mistake stops the start with a clear message instead of publishing it.
"""

from __future__ import annotations

import json
import os
import re
from typing import List, Optional

BASE58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
EVM = re.compile(r"0x[0-9a-fA-F]{40}")
# network name (upper case) -> address format; an unknown network is accepted as it is (the owner is trusted, only known formats are checked)
FORMATS = {
    **{name: EVM for name in ("ETH", "ERC20", "BSC", "BEP20", "POLYGON", "MATIC", "ARBITRUM", "OPTIMISM", "BASE", "AVAX", "EVM")},
    **{name: re.compile(r"T[%s]{33}" % BASE58) for name in ("TRON", "TRC20")},
    "BTC": re.compile(r"(bc1[ac-hj-np-z02-9]{11,87}|[13][%s]{25,34})" % BASE58),
    "LTC": re.compile(r"(ltc1[ac-hj-np-z02-9]{11,87}|[LM3][%s]{25,34})" % BASE58),
    "SOL": re.compile(r"[%s]{32,44}" % BASE58),
}
KINDS = ("crypto", "link", "text")
CONTROL = re.compile(r"[\x00-\x1f\x7f<>\"'`]")           # nothing that could break out of a page or a log line


def telegram_handle(value: Optional[str]) -> str:
    """``@name``, ``name`` or a ``t.me`` link -> ``name`` (a Telegram username is 5-32 letters, digits or underscores); ``""`` when unset."""
    text = (value or "").strip()
    for prefix in ("https://", "http://", "t.me/", "telegram.me/", "@"):
        if text.lower().startswith(prefix):
            text = text[len(prefix):]
    if not text:
        return ""
    if not re.fullmatch(r"[A-Za-z0-9_]{5,32}", text):
        raise ValueError(f"not a Telegram username: {value!r} (5-32 letters, digits or underscores)")
    return text


def _text(entry: dict, key: str, limit: int, required: bool = False) -> str:
    value = entry.get(key)
    value = "" if value is None else str(value).strip()
    if required and not value:
        raise ValueError(f"payment method {entry!r}: '{key}' is required")
    if len(value) > limit or CONTROL.search(value):
        raise ValueError(f"payment method {entry.get('label')!r}: '{key}' is too long or has forbidden characters")
    return value


def method(entry: dict) -> dict:
    """One validated payment method: ``{kind, label, network?, address?, url?, note?}``."""
    if not isinstance(entry, dict):
        raise ValueError(f"a payment method must be an object, got {entry!r}")
    label = _text(entry, "label", 40, required=True)
    kind = _text(entry, "kind", 10) or ("crypto" if entry.get("address") else "link" if entry.get("url") else "text")
    if kind not in KINDS:
        raise ValueError(f"payment method {label!r}: kind must be one of {KINDS}")
    out = {"kind": kind, "label": label}
    if entry.get("qr") is False:
        out["qr"] = False                                   # "qr": false hides the QR button of this method
    note = _text(entry, "note", 160)
    if note:
        out["note"] = note
    if kind == "crypto":
        address = _text(entry, "address", 120, required=True)
        network = _text(entry, "network", 24)
        shape = FORMATS.get(network.upper())
        if shape is not None and not shape.fullmatch(address):
            raise ValueError(f"payment method {label!r}: {address!r} is not a valid {network} address (check every character)")
        if network:
            out["network"] = network
        out["address"] = address
    elif kind == "link":
        url = _text(entry, "url", 300, required=True)
        if not re.fullmatch(r"https://[^\s/]+\.[^\s/]+(/\S*)?", url):
            raise ValueError(f"payment method {label!r}: the link must start with https:// ({url!r})")
        out["url"] = url
    elif not note:
        raise ValueError(f"payment method {label!r}: a text method needs a 'note'")
    return out


def default_file(*folders: str) -> Optional[str]:
    """``donate.json`` in the first of ``folders`` that has one (project root, then the cache folder): no option or variable needed."""
    for folder in folders:
        path = os.path.join(folder, "donate.json")
        if os.path.isfile(path):
            return path
    return None


def build(telegram: Optional[str] = None, file: Optional[str] = None) -> Optional[dict]:
    """The document the page shows (``{"telegram": name or "", "methods": [...]}``), or ``None`` when nothing is configured."""
    methods: List[dict] = []
    raw = {}
    if file:
        with open(file, encoding="utf-8") as fh:
            raw = json.load(fh)
        if not isinstance(raw, dict):
            raise ValueError("the donate file must hold a JSON object")
        methods = [method(entry) for entry in raw.get("methods") or []]
    handle = telegram_handle(telegram if telegram else raw.get("telegram"))
    if not handle and not methods:
        return None
    return {"telegram": handle, "methods": methods}


if __name__ == "__main__":                       # python -m bf2demo.web.donate donate.json  -> checks the file and prints what the page will show
    import sys
    try:
        document = build(None, sys.argv[1])
    except (ValueError, OSError, json.JSONDecodeError) as error:
        raise SystemExit(f"ERROR: {error}")
    print(json.dumps(document, indent=2, ensure_ascii=False) if document else "nothing configured")
