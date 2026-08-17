"""
Tests de la traduction preset Zenkai -> config Fleasion (features/fleasion/
config_writer.py) — dossier de déploiement redirigé vers un dossier
temporaire, jamais le vrai %LocalAppData%\\FleasionNT de l'utilisateur.
"""
import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from features.fleasion import config_writer
from features.fleasion.preset_store import MODE_ID, MODE_LOCAL, MODE_REMOVE, FleasionPresetEntry, FleasionRule


class TestConfigWriter(unittest.TestCase):
    def setUp(self):
        self._deploy_dir = tempfile.mkdtemp(prefix="zenkai_fleasion_deploy_test_")
        self._patcher = patch.object(config_writer, "get_fleasion_deploy_dir", return_value=self._deploy_dir)
        self._patcher.start()
        self._presets_dir = tempfile.mkdtemp(prefix="zenkai_fleasion_presets_test_")
        self._presets_patcher = patch(
            "features.fleasion.preset_store.get_fleasion_presets_dir", return_value=self._presets_dir,
        )
        self._presets_patcher.start()

    def tearDown(self):
        self._patcher.stop()
        self._presets_patcher.stop()
        shutil.rmtree(self._deploy_dir, ignore_errors=True)
        shutil.rmtree(self._presets_dir, ignore_errors=True)

    def _make_entry(self) -> FleasionPresetEntry:
        return FleasionPresetEntry(
            id="preset123", name="Test Preset",
            rules=[
                FleasionRule(asset_ids="111", mode=MODE_ID, target="222", enabled=True),
                FleasionRule(asset_ids="333", mode=MODE_REMOVE, target="", enabled=True),
            ],
        )

    def test_deploy_writes_config_with_active_status(self):
        entry = self._make_entry()
        deployed_path = config_writer.deploy_preset(entry, active=True)
        self.assertTrue(os.path.isfile(deployed_path))
        with open(deployed_path, encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(len(data), 2)
        self.assertTrue(data[0]["status"])
        self.assertTrue(data[1]["status"])
        self.assertEqual(data[0]["assetIds"], "111")
        self.assertEqual(data[0]["replaceWith"], "222")

    def test_disabled_rule_never_active_even_when_preset_active(self):
        entry = self._make_entry()
        entry.rules[0].enabled = False
        deployed_path = config_writer.deploy_preset(entry, active=True)
        with open(deployed_path, encoding="utf-8") as f:
            data = json.load(f)
        self.assertFalse(data[0]["status"])  # rule disabled
        self.assertTrue(data[1]["status"])  # other rule still enabled

    def test_undeploy_sets_all_statuses_false_without_deleting_file(self):
        entry = self._make_entry()
        deployed_path = config_writer.deploy_preset(entry, active=True)
        config_writer.undeploy_preset(entry)
        self.assertTrue(os.path.isfile(deployed_path))
        with open(deployed_path, encoding="utf-8") as f:
            data = json.load(f)
        self.assertFalse(data[0]["status"])
        self.assertFalse(data[1]["status"])

    def test_undeploy_noop_when_never_deployed(self):
        entry = self._make_entry()
        config_writer.undeploy_preset(entry)  # ne doit jamais lever
        self.assertFalse(os.path.isfile(config_writer._deployed_config_path(entry)))

    def test_remove_deployed_preset_deletes_file_and_assets(self):
        entry = self._make_entry()
        deployed_path = config_writer.deploy_preset(entry, active=True)
        config_writer.remove_deployed_preset(entry)
        self.assertFalse(os.path.isfile(deployed_path))

    def test_deploy_copies_local_asset_file_and_rewrites_target(self):
        entry = FleasionPresetEntry(
            id="preset456", name="Local Preset",
            rules=[FleasionRule(asset_ids="999", mode=MODE_LOCAL, target="/hit.ogg", enabled=True)],
        )
        from features.fleasion.preset_store import preset_assets_dir
        assets_dir = preset_assets_dir(entry)
        with open(os.path.join(assets_dir, "hit.ogg"), "wb") as f:
            f.write(b"fake audio")

        deployed_path = config_writer.deploy_preset(entry, active=True)
        with open(deployed_path, encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data[0]["replaceWith"], "/hit.ogg")

        deployed_assets = config_writer._deployed_assets_dir(entry)
        self.assertTrue(os.path.isfile(os.path.join(deployed_assets, "hit.ogg")))

    def test_deploy_always_regenerated_never_stale(self):
        """Un déploiement précédent ne doit jamais laisser un ancien fichier
        d'asset traîner une fois qu'une règle Local a été retirée."""
        from features.fleasion.preset_store import preset_assets_dir
        entry = FleasionPresetEntry(
            id="preset789", name="Preset",
            rules=[FleasionRule(asset_ids="1", mode=MODE_LOCAL, target="/old.png", enabled=True)],
        )
        assets_dir = preset_assets_dir(entry)
        with open(os.path.join(assets_dir, "old.png"), "wb") as f:
            f.write(b"x")
        config_writer.deploy_preset(entry, active=True)
        deployed_assets = config_writer._deployed_assets_dir(entry)
        self.assertTrue(os.path.isfile(os.path.join(deployed_assets, "old.png")))

        entry.rules = []  # règle Local retirée
        config_writer.deploy_preset(entry, active=True)
        self.assertFalse(os.path.isfile(os.path.join(deployed_assets, "old.png")))


if __name__ == "__main__":
    unittest.main()
