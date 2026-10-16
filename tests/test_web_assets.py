"""Game artwork lookups of the web viewer: tweak parsing, icon keys, names and the archive allowlist."""

from __future__ import annotations

import unittest

from bf2demo.web import assets, maps

TWEAK = (
    "ObjectTemplate.activeSafe PlayerControlObject USTNK_M1A2\n"
    "ObjectTemplate.createComponent VehicleHud\n"
    "ObjectTemplate.vehicleHud.miniMapIcon Ingame\\Vehicles\\Icons\\Minimap\\mini_Tank.tga\n"
    'ObjectTemplate.vehicleHud.hudName "KILLMESSAGE_VEHICLE_m1a2"\n'
    "ObjectTemplate.activeSafe PlayerControlObject other\n"
    "ObjectTemplate.vehicleHud.miniMapIcon Ingame\\Vehicles\\Icons\\Minimap\\mini_Jeep.tga\n"
)


class ParsingTest(unittest.TestCase):
    def test_properties_belong_to_the_preceding_template(self):
        table = assets.parse_templates(TWEAK)
        self.assertEqual(table["ustnk_m1a2"]["minimapicon"], "Ingame\\Vehicles\\Icons\\Minimap\\mini_Tank.tga")
        self.assertEqual(table["ustnk_m1a2"]["hudname"], "KILLMESSAGE_VEHICLE_m1a2")
        self.assertEqual(table["other"]["minimapicon"], "Ingame\\Vehicles\\Icons\\Minimap\\mini_Jeep.tga")
        self.assertNotIn("hudname", table["other"])

    def test_icon_keys_ignore_case_extension_and_slash_style(self):
        self.assertEqual(assets.norm_icon("Ingame\\Vehicles\\Icons\\Minimap\\mini_Tank.tga"), "ingame/vehicles/icons/minimap/mini_tank")
        self.assertEqual(assets.norm_icon('"ingame/Kits/Icons/kit_Medic_outline"'), "ingame/kits/icons/kit_medic_outline")

    def test_localised_names_lose_colour_codes(self):
        self.assertEqual(assets.parse_strings("K  M1A2 Abrams \x1bC1001'MBT'\x1bC1001")["K"], "M1A2 Abrams 'MBT'")


class InstalledGameTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = maps.game_root()
        if root is None:
            raise unittest.SkipTest("no Battlefield 2 install")
        cls.game = assets.GameAssets(root)

    def test_vehicle_icon_resolves_tga_name_to_dds_member(self):
        info = self.game.vehicle_info("ustnk_m1a2")
        self.assertEqual(info["icon"], "ingame/vehicles/icons/minimap/mini_tank")      # .tga in the tweak, .dds in the archive
        self.assertEqual(info["name"], "M1A2 Abrams 'MBT'")

    def test_kit_icons_follow_the_kit_templates(self):
        icons = self.game.kit_icons()
        self.assertEqual(icons["support"], "ingame/kits/icons/kit_heavy_assault_outline")
        self.assertEqual(icons["assault"], "ingame/kits/icons/kit_light_assault_outline")

    def test_only_indexed_names_resolve(self):
        self.assertTrue(self.game.icon_png("Ingame\\Player\\Icons\\Minimap\\mini_Soldier.tga").startswith(b"\x89PNG"))
        for evil in ("../../etc/passwd", "ingame/../../../Init.con", "C:/Windows/win.ini", ""):
            self.assertIsNone(self.game.icon_png(evil), evil)


if __name__ == "__main__":
    unittest.main()
