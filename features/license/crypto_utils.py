"""
Obfuscation légère du fichier de licence local (license.dat).
Ce n'est PAS un chiffrement fort : l'objectif (Partie 4.4 du brief) est
seulement d'éviter que la clé traîne en clair sur le disque, pas de résister
à une rétro-ingénierie active du .exe (pas de DRM incassable recherché ici).
"""
import base64

_OBFUSCATION_PASSPHRASE = b"ZenkaiCore-local-license-v1"


def _xor(data: bytes, key: bytes) -> bytes:
    return bytes(b ^ key[i % len(key)] for i, b in enumerate(data))


def obfuscate(plain_text: str) -> str:
    scrambled = _xor(plain_text.encode("utf-8"), _OBFUSCATION_PASSPHRASE)
    return base64.b64encode(scrambled).decode("ascii")


def deobfuscate(obfuscated_text: str) -> str:
    scrambled = base64.b64decode(obfuscated_text.encode("ascii"))
    return _xor(scrambled, _OBFUSCATION_PASSPHRASE).decode("utf-8")
