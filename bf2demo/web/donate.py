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

import base64
import hashlib
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
FORMATS["TON"] = re.compile(r"[A-Za-z0-9_-]{48}")


def _base58check(address: str) -> Optional[bytes]:
    """The payload (version byte + hash) of a Base58Check address, or ``None`` when the checksum is wrong."""
    number = 0
    for char in address:
        number = number * 58 + BASE58.index(char)
    raw = b"\x00" * (len(address) - len(address.lstrip("1"))) + number.to_bytes((number.bit_length() + 7) // 8, "big")
    body, check = raw[:-4], raw[-4:]
    return body if hashlib.sha256(hashlib.sha256(body).digest()).digest()[:4] == check else None


def _bech32_ok(address: str) -> bool:
    charset = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
    hrp, _, data = address.lower().rpartition("1")
    values = [charset.find(c) for c in data]
    if not hrp or min(values, default=-1) < 0:
        return False
    check = 1
    for value in [ord(c) >> 5 for c in hrp] + [0] + [ord(c) & 31 for c in hrp] + values:
        top = check >> 25
        check = (check & 0x1FFFFFF) << 5 ^ value
        for i, generator in enumerate((0x3B6A57B2, 0x26508E6D, 0x1EA119FA, 0x3D4233DD, 0x2A1462B3)):
            check ^= generator if (top >> i) & 1 else 0
    return check in (1, 0x2BC830A3)              # bech32 / bech32m


def _ton_ok(address: str) -> bool:
    try:
        raw = base64.urlsafe_b64decode(address)
    except ValueError:
        return False
    crc = 0
    for byte in raw[:34]:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return len(raw) == 36 and crc == int.from_bytes(raw[34:], "big")


def _tron_ok(address: str) -> bool:
    body = _base58check(address)
    return body is not None and len(body) == 21 and body[0] == 0x41


def _btc_ok(address: str) -> bool:
    return _bech32_ok(address) if address.lower().startswith("bc1") else _base58check(address) is not None


def _ltc_ok(address: str) -> bool:
    return _bech32_ok(address) if address.lower().startswith("ltc1") else _base58check(address) is not None


# a typo almost always breaks the checksum: these are verified, not only matched against the character set
CHECKSUMS = {"TRON": _tron_ok, "TRC20": _tron_ok, "BTC": _btc_ok, "LTC": _ltc_ok, "TON": _ton_ok}
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
        checksum = CHECKSUMS.get(network.upper())
        if (shape is not None and not shape.fullmatch(address)) or (checksum is not None and not checksum(address)):
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


def github_link(file: Optional[str]) -> str:
    """The project's address (``"github": "https://github.com/..."`` in the same file), or ``""``; only ``https`` links are accepted."""
    if not file:
        return ""
    with open(file, encoding="utf-8") as fh:
        value = str((json.load(fh) or {}).get("github") or "").strip()
    if value and not re.fullmatch(r"https://[^\s<>\"'`]{4,200}", value):
        raise ValueError(f"the 'github' link must be an https address: {value!r}")
    return value


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
