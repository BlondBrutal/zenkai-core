"""
Tests (pytest) de l'obfuscation légère du fichier de licence (features/
license/crypto_utils.py) — pas de mock nécessaire, fonctions pures.
"""
import pytest

from features.license.crypto_utils import deobfuscate, obfuscate


def test_round_trip():
    original = "ZK-1234-5678-ABCD"
    assert deobfuscate(obfuscate(original)) == original


def test_obfuscated_text_differs_from_plain_text():
    original = "some-license-key"
    assert obfuscate(original) != original


def test_empty_string_round_trip():
    assert deobfuscate(obfuscate("")) == ""


def test_unicode_round_trip():
    original = "clé-héhé-日本語-🔑"
    assert deobfuscate(obfuscate(original)) == original


def test_output_is_valid_base64_ascii():
    import base64
    encoded = obfuscate("test")
    # Ne doit jamais lever : la sortie est toujours du base64 ASCII valide.
    base64.b64decode(encoded.encode("ascii"))


def test_deobfuscate_garbage_raises_rather_than_silently_corrupting():
    with pytest.raises(Exception):
        deobfuscate("not-valid-base64!!!")


def test_same_input_always_produces_same_output():
    # Déterministe (pas de sel/nonce aléatoire) : nécessaire pour que
    # license_store puisse comparer des fichiers réécrits d'une session à
    # l'autre sans divergence inattendue.
    assert obfuscate("stable-input") == obfuscate("stable-input")
