"""The support section: payment methods are validated when the server starts (a wallet address with a typo must never be published)."""

from __future__ import annotations

import json
import os
import tempfile
import unittest

from bf2demo.web import donate
from bf2demo.web.app import create_app

TRON = "TLsV52sRDL79HXGGm9yzwKibb6BeruhUzy"
EVM = "0xde0B295669a9FD93d5F28D9Ec85E40f4cb697BAe"
BTC = "bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq"


class DonateTest(unittest.TestCase):
    def test_methods_are_normalised(self):
        got = donate.build(None, self.file({"telegram": "@my_name", "methods": [
            {"label": "USDT", "network": "TRC20", "address": TRON}, {"label": "ETH", "network": "erc20", "address": EVM},
            {"label": "BTC", "network": "BTC", "address": BTC}, {"label": "PayPal", "url": "https://paypal.me/me"},
            {"label": "Bank", "kind": "text", "note": "ask me on Telegram"}]}))
        self.assertEqual(got["telegram"], "my_name")
        self.assertEqual([m["kind"] for m in got["methods"]], ["crypto", "crypto", "crypto", "link", "text"])
        self.assertEqual(got["methods"][0], {"kind": "crypto", "label": "USDT", "network": "TRC20", "address": TRON})

    def test_a_wrong_address_or_link_stops_the_start(self):
        for bad in ({"label": "USDT", "network": "TRC20", "address": TRON[:-1]},            # one character short
                    {"label": "USDT", "network": "TRC20", "address": EVM},                    # an EVM address on the Tron network
                    {"label": "ETH", "network": "ERC20", "address": EVM.replace("0x", "0X")},
                    {"label": "PayPal", "url": "http://paypal.me/me"},                        # plain http
                    {"label": "PayPal", "url": "javascript:alert(1)"},
                    {"label": "x<script>", "address": TRON}, {"label": "Bank", "kind": "text"}, {"address": TRON}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                donate.build(None, self.file({"methods": [bad]}))

    def test_a_typo_breaks_the_checksum_and_is_refused(self):
        good = {"TRC20": TRON, "BTC": BTC, "LTC": "LNcxFVLTSRmeKCjuMw4CKCFbXrGofoBnCt", "TON": "EQBKk3CMgQUdhAC1XV4m2Ou_H-sWmSp3ayr2G5gHTCtsaMMx"}
        for network, address in good.items():
            donate.method({"label": "x", "network": network, "address": address})                       # the real address passes
            typo = address[:-2] + ("b" if address[-2] != "b" else "c") + address[-1]                   # one character changed in the middle of the tail
            with self.subTest(network=network), self.assertRaises(ValueError):
                donate.method({"label": "x", "network": network, "address": typo})

    def test_unknown_networks_are_kept_as_they_are(self):
        got = donate.build(None, self.file({"methods": [{"label": "XYZ", "network": "XYZCOIN", "address": "xyz-" + "a" * 46}]}))
        self.assertEqual(got["methods"][0]["network"], "XYZCOIN")

    def test_the_page_gets_them_from_the_api(self):
        path = self.file({"telegram": "@my_name", "methods": [{"label": "USDT", "network": "TRC20", "address": TRON}]})
        client = create_app([], os.path.join(os.path.dirname(path), "cache"), donate_file=path).test_client()
        doc = client.get("/api/game").get_json()["donate"]
        self.assertEqual(doc["methods"][0]["address"], TRON)
        self.assertEqual(doc["telegram"], "my_name")
        self.assertIsNone(create_app([], os.path.join(os.path.dirname(path), "c2"), donate_file=False).test_client().get("/api/game").get_json()["donate"])

    def test_the_example_file_cannot_be_published_unchanged(self):
        with self.assertRaises(ValueError):
            donate.build(None, os.path.join(os.path.dirname(__file__), "..", "deploy", "donate.example.json"))

    def test_a_donate_json_in_a_known_folder_is_found_without_any_option(self):
        path = self.file({"telegram": "@my_name"})
        folder = os.path.dirname(path)
        self.assertEqual(donate.default_file(os.path.join(folder, "none"), folder), path)
        self.assertIsNone(donate.default_file(os.path.join(folder, "none")))
        self.assertEqual(donate.default_file(folder, os.path.join(folder, "other")), path)       # the first folder that has one wins

    def test_qr_can_be_switched_off_per_method(self):
        got = donate.build(None, self.file({"methods": [{"label": "Bank", "kind": "text", "note": "ask", "qr": False}, {"label": "USDT", "network": "TRC20", "address": TRON}]}))
        self.assertIs(got["methods"][0]["qr"], False)
        self.assertNotIn("qr", got["methods"][1])

    def file(self, document):
        folder = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(folder, ignore_errors=True))
        path = os.path.join(folder, "donate.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(document, fh)
        return path


if __name__ == "__main__":
    unittest.main()
