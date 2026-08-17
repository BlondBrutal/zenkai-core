"""
Tests (pytest) de l'identifiant machine stable (features/license/
hardware_id.py) — le registre Windows est TOUJOURS mocké, jamais lu pour de
vrai (voir CLAUDE.md, convention déjà utilisée pour fastflags/protocol.py).
"""
import hashlib
from unittest.mock import MagicMock, patch

from features.license.hardware_id import get_hardware_id


def test_hash_is_stable_for_same_machine_guid():
    with patch("winreg.OpenKey"), patch(
        "winreg.QueryValueEx", return_value=("11111111-2222-3333-4444-555555555555", 1)
    ):
        first = get_hardware_id()
        second = get_hardware_id()
    assert first == second


def test_hash_differs_for_different_machine_guid():
    with patch("winreg.OpenKey"), patch(
        "winreg.QueryValueEx", return_value=("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee", 1)
    ):
        result_a = get_hardware_id()
    with patch("winreg.OpenKey"), patch(
        "winreg.QueryValueEx", return_value=("ffffffff-0000-1111-2222-333333333333", 1)
    ):
        result_b = get_hardware_id()
    assert result_a != result_b


def test_returns_sha256_hex_digest_of_machine_guid():
    guid = "deadbeef-dead-beef-dead-beefdeadbeef"
    expected = hashlib.sha256(guid.encode("utf-8")).hexdigest()
    with patch("winreg.OpenKey"), patch("winreg.QueryValueEx", return_value=(guid, 1)):
        result = get_hardware_id()
    assert result == expected


def test_never_raises_when_registry_unreadable():
    with patch("winreg.OpenKey", side_effect=OSError("clé introuvable")):
        result = get_hardware_id()
    assert result == "unknown"
