"""
Tests de la logique de licence (features/license). Simule le Worker
d'activation avec un petit serveur HTTP local (stdlib uniquement, pas de
vrai Cloudflare Worker requis pour tester) qui reproduit la décision
prise par cloudflare-worker/worker.js (not_found/deactivated/already_used/
valid), et isole le stockage local dans un dossier temporaire.
"""
import json
import os
import shutil
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest.mock import patch

from features.license import license_manager
from features.license.license_manager import LicenseStatus, validate_key_format
from features.license.license_store import load_license, save_license


class _FakeRegistryState:
    """Contenu actuellement "connu" du faux Worker (mutable entre les
    requêtes, comme le Gist réel modifié par le vrai worker.js)."""

    def __init__(self, data: dict):
        self.data = data


def _make_handler(state: _FakeRegistryState):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            if self.path != "/activate":
                self.send_response(404)
                self.end_headers()
                return

            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length) or b"{}")
            key = (body.get("key") or "").strip().upper()
            hardware_id = (body.get("hardware_id") or "").strip()

            entry = state.data.get(key)
            if entry is None:
                payload = {"status": "not_found"}
            elif not entry.get("actif", False):
                payload = {"status": "deactivated"}
            elif not entry.get("hardware_id"):
                entry["hardware_id"] = hardware_id
                payload = {"status": "valid", "nom": entry.get("nom", "")}
            elif entry["hardware_id"] == hardware_id:
                payload = {"status": "valid", "nom": entry.get("nom", "")}
            else:
                payload = {"status": "already_used"}

            response = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(response)

        def log_message(self, format, *args):
            pass  # silence les logs du serveur de test

    return Handler


class LicenseManagerTests(unittest.TestCase):
    def setUp(self):
        self._temp_dir = tempfile.mkdtemp(prefix="zenkai_license_test_")
        self._license_path = os.path.join(self._temp_dir, "license.dat")

        self._registry_state = _FakeRegistryState({
            "ZK-AAAA-BBBB-CCCC": {"nom": "Kevin", "actif": True, "hardware_id": None},
            "ZK-DEAD-DEAD-DEAD": {"nom": "Banni", "actif": False, "hardware_id": None},
        })
        self._server = HTTPServer(("127.0.0.1", 0), _make_handler(self._registry_state))
        self._server_thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._server_thread.start()
        self._activate_url = f"http://127.0.0.1:{self._server.server_port}/activate"

        self._patches = [
            patch("features.license.license_store.get_license_path", return_value=self._license_path),
            patch.object(license_manager, "_license_config", return_value={
                "activate_url": self._activate_url,
                "grace_days": 3,
                "network_timeout_seconds": 0.5,
            }),
            patch.object(license_manager, "get_hardware_id", return_value="hw-this-device"),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self._server.shutdown()
        self._server_thread.join(timeout=2)
        self._server.server_close()
        shutil.rmtree(self._temp_dir, ignore_errors=True)

    def test_validate_key_format(self):
        self.assertTrue(validate_key_format("ZK-AAAA-BBBB-CCCC"))
        self.assertTrue(validate_key_format("zk-aaaa-bbbb-cccc"))
        self.assertFalse(validate_key_format("ZK-AAAA-BBBB"))
        self.assertFalse(validate_key_format("NOT-A-KEY"))

    def test_valid_key_saves_local_cache(self):
        result = license_manager.check_key_online("ZK-AAAA-BBBB-CCCC")
        self.assertEqual(result.status, LicenseStatus.VALID)
        self.assertEqual(result.nom, "Kevin")

        local = load_license()
        self.assertIsNotNone(local)
        self.assertEqual(local["key"], "ZK-AAAA-BBBB-CCCC")
        self.assertEqual(local["nom"], "Kevin")

    def test_first_activation_locks_hardware_id_on_server(self):
        license_manager.check_key_online("ZK-AAAA-BBBB-CCCC")
        self.assertEqual(
            self._registry_state.data["ZK-AAAA-BBBB-CCCC"]["hardware_id"], "hw-this-device"
        )

    def test_same_device_rechecking_stays_valid(self):
        license_manager.check_key_online("ZK-AAAA-BBBB-CCCC")  # première activation
        result = license_manager.check_key_online("ZK-AAAA-BBBB-CCCC")  # revérification
        self.assertEqual(result.status, LicenseStatus.VALID)

    def test_other_device_is_blocked_already_used(self):
        license_manager.check_key_online("ZK-AAAA-BBBB-CCCC")  # verrouillée sur "hw-this-device"

        with patch.object(license_manager, "get_hardware_id", return_value="hw-other-device"):
            result = license_manager.check_key_online("ZK-AAAA-BBBB-CCCC")
        self.assertEqual(result.status, LicenseStatus.ALREADY_USED)
        # Réponse définitive du serveur : pas de cache local exploitable pour
        # ce deuxième appareil, donc pas de grâce hors-ligne possible non plus.
        self.assertIsNone(load_license())

    def test_unknown_key_is_not_found_and_not_saved(self):
        result = license_manager.check_key_online("ZK-0000-0000-0000")
        self.assertEqual(result.status, LicenseStatus.NOT_FOUND)
        self.assertIsNone(load_license())

    def test_deactivated_key_blocks_and_clears_local_cache(self):
        # Une clé désactivée ne doit jamais rester sauvegardée localement,
        # pour fermer toute fenêtre de grâce hors-ligne restante.
        result = license_manager.check_key_online("ZK-DEAD-DEAD-DEAD")
        self.assertEqual(result.status, LicenseStatus.DEACTIVATED)
        self.assertIsNone(load_license())

    def test_offline_grace_after_successful_check(self):
        first = license_manager.check_key_online("ZK-AAAA-BBBB-CCCC")
        self.assertEqual(first.status, LicenseStatus.VALID)

        self._server.shutdown()  # simule une coupure internet
        result = license_manager.check_saved_license()
        self.assertEqual(result.status, LicenseStatus.VALID_OFFLINE_GRACE)
        self.assertEqual(result.nom, "Kevin")
        self.assertGreaterEqual(result.days_left, 1)

    def test_offline_grace_expired_after_three_days(self):
        stale_check = (datetime.now(timezone.utc) - timedelta(days=4)).isoformat()
        save_license({"key": "ZK-AAAA-BBBB-CCCC", "nom": "Kevin", "last_check_ok": stale_check})

        self._server.shutdown()
        result = license_manager.check_saved_license()
        self.assertEqual(result.status, LicenseStatus.OFFLINE_EXPIRED)

    def test_registry_unreachable_with_no_local_key_blocks(self):
        self._server.shutdown()
        result = license_manager.check_key_online("ZK-AAAA-BBBB-CCCC")
        self.assertEqual(result.status, LicenseStatus.REGISTRY_ERROR)

    def test_no_key_saved(self):
        result = license_manager.check_saved_license()
        self.assertEqual(result.status, LicenseStatus.NO_KEY)


if __name__ == "__main__":
    unittest.main()
