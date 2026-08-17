"""
Identifiant machine stable pour le verrouillage "1 clé = 1 appareil"
(Partie 4.5 du brief). Basé sur le MachineGuid Windows
(HKLM\\SOFTWARE\\Microsoft\\Cryptography\\MachineGuid) — un identifiant
généré une seule fois à l'installation de Windows, JAMAIS l'IP ou l'adresse
MAC qui peuvent changer (réseau différent, carte réseau remplacée...).

Le GUID brut n'est jamais envoyé au serveur : on envoie un hash SHA-256, à
la fois pour ne jamais exposer un identifiant Windows interne en clair sur
le réseau et parce que seul un identifiant STABLE (même hash à chaque appel
sur la même machine) compte pour le serveur, pas sa valeur d'origine.
"""
import hashlib
import logging
import winreg

logger = logging.getLogger("zenkaiontop.license")

_MACHINE_GUID_HIVE = winreg.HKEY_LOCAL_MACHINE
_MACHINE_GUID_SUBKEY = "SOFTWARE\\Microsoft\\Cryptography"
_MACHINE_GUID_VALUE = "MachineGuid"


def get_hardware_id() -> str:
    """Retourne un identifiant stable (hash hexadécimal) pour cette machine.
    Ne lève jamais : une chaîne fixe "unknown" en repli si le registre est
    illisible (improbable, mais ne doit jamais empêcher l'app de démarrer)."""
    try:
        with winreg.OpenKey(_MACHINE_GUID_HIVE, _MACHINE_GUID_SUBKEY, 0, winreg.KEY_READ) as key:
            machine_guid, _ = winreg.QueryValueEx(key, _MACHINE_GUID_VALUE)
    except OSError as exc:
        logger.error("Impossible de lire MachineGuid (%s), identifiant machine indisponible", exc)
        return "unknown"

    return hashlib.sha256(machine_guid.encode("utf-8")).hexdigest()
